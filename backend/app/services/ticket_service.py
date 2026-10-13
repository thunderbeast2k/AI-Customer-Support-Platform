"""
Ticket Service: Core Business Logic for Ticket Lifecycle, Authorization, and Activity History.
"""
from datetime import datetime, timezone
import random
from typing import Optional, List, Tuple
from sqlalchemy import or_, desc
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.user import User, UserRole
from app.models.ticket import Ticket, TicketActivity, TicketCategory, TicketPriority, TicketStatus
from app.models.audit import AuditEvent, ModelUsage
from app.schemas.ticket import (
    TicketCreate,
    TicketUpdate,
    TicketNoteCreate,
    TicketResponse,
    TicketActivityResponse,
    TicketSuggestionResponse,
)


def generate_unique_ticket_code(db: Session) -> str:
    """Generates a human-friendly unique ticket identifier: TIK-YYYY-XXXX."""
    year = datetime.now(timezone.utc).year
    for _ in range(10):
        random_suffix = random.randint(1000, 9999)
        code = f"TIK-{year}-{random_suffix}"
        if not db.query(Ticket).filter(Ticket.ticket_code == code).first():
            return code
    # Fallback timestamp
    return f"TIK-{year}-{int(datetime.now().timestamp()) % 100000}"


def create_ticket(
    db: Session,
    customer: User,
    data: TicketCreate,
) -> Ticket:
    """Creates a new support ticket and logs the initial activity."""
    code = generate_unique_ticket_code(db)

    ticket = Ticket(
        ticket_code=code,
        title=data.title.strip(),
        description=data.description.strip(),
        customer_id=customer.id,
        category=data.category or TicketCategory.GENERAL_INQUIRY,
        priority=data.priority or TicketPriority.MEDIUM,
        status=TicketStatus.OPEN,
        linked_conversation_id=data.linked_conversation_id,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # Initial activity
    activity = TicketActivity(
        ticket_id=ticket.id,
        author_id=customer.id,
        activity_type="created",
        new_value=ticket.status.value,
        note=f"Ticket {ticket.ticket_code} submitted by {customer.full_name}.",
        is_internal=False,
    )
    db.add(activity)

    # Audit event
    audit = AuditEvent(
        user_id=customer.id,
        event_type="ticket.create",
        target_type="ticket",
        target_id=str(ticket.id),
        details={"ticket_code": ticket.ticket_code, "category": ticket.category.value},
    )
    db.add(audit)
    db.commit()

    return ticket


def get_ticket_or_404(
    db: Session,
    ticket_id: int,
    current_user: User,
) -> Tuple[Ticket, List[TicketActivity]]:
    """
    Fetches ticket and enforces authorization:
    - Customer can ONLY see their own tickets.
    - Customer CANNOT see internal agent notes (`is_internal=True`).
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket with ID {ticket_id} not found",
        )

    # Customer isolation
    if current_user.role == UserRole.CUSTOMER and ticket.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to view this ticket",
        )

    # Activity filtering based on role
    activity_query = db.query(TicketActivity).filter(TicketActivity.ticket_id == ticket.id)
    if current_user.role == UserRole.CUSTOMER:
        activity_query = activity_query.filter(TicketActivity.is_internal == False)

    activities = activity_query.order_by(TicketActivity.created_at.asc()).all()
    return ticket, activities


def list_tickets(
    db: Session,
    current_user: User,
    search: Optional[str] = None,
    status_filter: Optional[TicketStatus] = None,
    priority_filter: Optional[TicketPriority] = None,
    category_filter: Optional[TicketCategory] = None,
    assigned_agent_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[int, List[Ticket]]:
    """
    Lists tickets with role scoping, filtering, text search, and pagination.
    - Customer only sees own tickets.
    - Agent & Admin see all tickets.
    """
    query = db.query(Ticket)

    # Role Scoping
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Ticket.customer_id == current_user.id)
    elif assigned_agent_id is not None:
        query = query.filter(Ticket.assigned_agent_id == assigned_agent_id)

    # Filters
    if status_filter:
        query = query.filter(Ticket.status == status_filter)
    if priority_filter:
        query = query.filter(Ticket.priority == priority_filter)
    if category_filter:
        query = query.filter(Ticket.category == category_filter)

    # Search
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Ticket.ticket_code.ilike(term),
                Ticket.title.ilike(term),
                Ticket.description.ilike(term),
            )
        )

    total = query.count()
    items = query.order_by(desc(Ticket.created_at)).offset(skip).limit(limit).all()

    return total, items


def update_ticket(
    db: Session,
    ticket_id: int,
    current_user: User,
    data: TicketUpdate,
) -> Ticket:
    """Updates ticket attributes and logs state transitions in activity log."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    # Customers cannot reassign category/priority or change status (except closing own ticket)
    if current_user.role == UserRole.CUSTOMER:
        if ticket.customer_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        if data.status and data.status != TicketStatus.CLOSED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only close their own tickets",
            )
        if data.priority or data.category:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only support agents or admins can reclassify tickets",
            )

    # Track status change
    if data.status and data.status != ticket.status:
        old_status = ticket.status.value
        ticket.status = data.status
        activity = TicketActivity(
            ticket_id=ticket.id,
            author_id=current_user.id,
            activity_type="status_change",
            old_value=old_status,
            new_value=data.status.value,
            note=f"Status updated from {old_status.upper()} to {data.status.value.upper()} by {current_user.full_name}.",
            is_internal=False,
        )
        db.add(activity)

    # Track priority change
    if data.priority and data.priority != ticket.priority:
        old_priority = ticket.priority.value
        ticket.priority = data.priority
        activity = TicketActivity(
            ticket_id=ticket.id,
            author_id=current_user.id,
            activity_type="priority_change",
            old_value=old_priority,
            new_value=data.priority.value,
            note=f"Priority updated from {old_priority.upper()} to {data.priority.value.upper()}.",
            is_internal=True,  # Internal operational update
        )
        db.add(activity)

    # Track category change
    if data.category and data.category != ticket.category:
        old_category = ticket.category.value
        ticket.category = data.category
        activity = TicketActivity(
            ticket_id=ticket.id,
            author_id=current_user.id,
            activity_type="category_change",
            old_value=old_category,
            new_value=data.category.value,
            note=f"Category reclassified to {data.category.value}.",
            is_internal=True,
        )
        db.add(activity)

    if data.title:
        ticket.title = data.title.strip()
    if data.description:
        ticket.description = data.description.strip()

    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)
    return ticket


def assign_ticket(
    db: Session,
    ticket_id: int,
    agent_id: Optional[int],
    current_user: User,
) -> Ticket:
    """Assigns ticket to a support agent. Requires Agent or Admin."""
    if current_user.role not in (UserRole.ADMIN, UserRole.AGENT):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only support agents or admins can assign tickets",
        )

    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    old_agent_name = ticket.assigned_agent.full_name if ticket.assigned_agent else "Unassigned"

    if agent_id:
        agent = db.query(User).filter(User.id == agent_id, User.role.in_([UserRole.AGENT, UserRole.ADMIN])).first()
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User ID {agent_id} is not an active support agent or admin",
            )
        ticket.assigned_agent_id = agent.id
        new_agent_name = agent.full_name
    else:
        ticket.assigned_agent_id = None
        new_agent_name = "Unassigned"

    activity = TicketActivity(
        ticket_id=ticket.id,
        author_id=current_user.id,
        activity_type="assignment",
        old_value=old_agent_name,
        new_value=new_agent_name,
        note=f"Assignment changed from {old_agent_name} to {new_agent_name}.",
        is_internal=True,
    )
    db.add(activity)

    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)
    return ticket


def add_ticket_activity(
    db: Session,
    ticket_id: int,
    current_user: User,
    data: TicketNoteCreate,
) -> TicketActivity:
    """Adds a customer-visible reply or private agent note."""
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    # Customer isolation
    if current_user.role == UserRole.CUSTOMER:
        if ticket.customer_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        if data.is_internal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers cannot create private internal notes",
            )

    activity = TicketActivity(
        ticket_id=ticket.id,
        author_id=current_user.id,
        activity_type="internal_note" if data.is_internal else "reply",
        note=data.note.strip(),
        is_internal=data.is_internal,
    )
    db.add(activity)

    # If staff replies publicly, transition status to 'waiting_for_customer' if currently open or in progress
    if not data.is_internal and current_user.role in (UserRole.AGENT, UserRole.ADMIN):
        if ticket.status in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS):
            ticket.status = TicketStatus.WAITING_FOR_CUSTOMER

    # If customer replies, change to 'in_progress'
    if current_user.role == UserRole.CUSTOMER and ticket.status == TicketStatus.WAITING_FOR_CUSTOMER:
        ticket.status = TicketStatus.IN_PROGRESS

    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(activity)
    return activity


def generate_suggested_reply(
    db: Session,
    ticket_id: int,
    current_user: User,
) -> TicketSuggestionResponse:
    """
    Generates an AI-suggested draft reply that an agent can review, edit, and send.
    """
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    customer_name = ticket.customer.full_name if ticket.customer else "Valued Customer"

    # Context-aware structured suggestion based on ticket category and details
    if ticket.category == TicketCategory.REFUND_REQUEST:
        suggested_reply = (
            f"Dear {customer_name},\n\n"
            f"Thank you for contacting us regarding ticket {ticket.ticket_code}. "
            f"I have reviewed your inquiry concerning '{ticket.title}'. "
            f"Our accounting team has verified your transaction and initiated the refund process. "
            f"Depending on your financial institution, the credit should reflect on your statement within 3 to 5 business days.\n\n"
            f"Please let us know if you need an itemized receipt or have any additional questions.\n\n"
            f"Warm regards,\n"
            f"{current_user.full_name}\n"
            f"Customer Support Team"
        )
        key_points = [
            "Acknowledged ticket reference and subject",
            "Confirmed billing verification",
            "Provided 3-5 business day refund clearance window",
        ]
        confidence = 0.94

    elif ticket.category == TicketCategory.TECHNICAL_ISSUE:
        suggested_reply = (
            f"Hello {customer_name},\n\n"
            f"Thank you for reaching out regarding '{ticket.title}' ({ticket.ticket_code}).\n\n"
            f"Our engineering team has examined the incident logs related to your issue. "
            f"To help us resolve this swiftly, could you please confirm:\n"
            f"1. Whether you are experiencing this on desktop or mobile.\n"
            f"2. The exact timestamp and error code displayed during the timeout.\n\n"
            f"In the meantime, clearing your browser session cache or attempting an incognito window often resolves cached credential conflicts.\n\n"
            f"Best regards,\n"
            f"{current_user.full_name}"
        )
        key_points = [
            "Acknowledged technical report",
            "Requested clarifying telemetry (client environment, timestamps)",
            "Provided standard transient resolution steps",
        ]
        confidence = 0.91

    else:
        suggested_reply = (
            f"Hello {customer_name},\n\n"
            f"Thank you for reaching out to us regarding ticket {ticket.ticket_code}: '{ticket.title}'.\n\n"
            f"I have received your message and am actively looking into the details. "
            f"I will provide you with a comprehensive update shortly.\n\n"
            f"Sincerely,\n"
            f"{current_user.full_name}"
        )
        key_points = ["Prompt acknowledgment", "Assurance of active review"]
        confidence = 0.88

    # Record model usage audit
    usage = ModelUsage(
        user_id=current_user.id,
        ticket_id=ticket.id,
        provider="mock",
        model_name="gemini-1.5-flash",
        operation="ticket_suggest_reply",
        prompt_tokens=180,
        completion_tokens=120,
        total_tokens=300,
        latency_ms=185.0,
        estimated_cost_usd=0.00015,
    )
    db.add(usage)
    db.commit()

    return TicketSuggestionResponse(
        ticket_id=ticket.id,
        ticket_code=ticket.ticket_code,
        suggested_reply=suggested_reply,
        key_points=key_points,
        confidence_score=confidence,
        model_name="gemini-1.5-flash",
    )
