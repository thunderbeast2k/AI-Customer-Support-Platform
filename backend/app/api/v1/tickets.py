"""
Ticket Management API Endpoints.
Provides CRUD, agent assignment, activity histories, and AI-suggested responses.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User, UserRole
from app.models.ticket import TicketCategory, TicketPriority, TicketStatus
from app.schemas.ticket import (
    TicketCreate,
    TicketUpdate,
    TicketAssign,
    TicketNoteCreate,
    TicketResponse,
    TicketListResponse,
    TicketActivityResponse,
    TicketSuggestionResponse,
)
from app.api.deps import get_current_user, require_agent_or_admin
from app.services import ticket_service

router = APIRouter(prefix="/tickets", tags=["Support Ticket Management"])


def _format_ticket_response(ticket, activities=None) -> TicketResponse:
    """Helper to convert Ticket ORM entity into TicketResponse with author names."""
    act_responses = []
    if activities:
        for a in activities:
            author_name = a.author.full_name if a.author else "System"
            author_role = a.author.role.value if a.author else "system"
            act_responses.append(
                TicketActivityResponse(
                    id=a.id,
                    ticket_id=a.ticket_id,
                    author_id=a.author_id,
                    author_name=author_name,
                    author_role=author_role,
                    activity_type=a.activity_type,
                    old_value=a.old_value,
                    new_value=a.new_value,
                    note=a.note,
                    is_internal=a.is_internal,
                    created_at=a.created_at,
                )
            )

    return TicketResponse(
        id=ticket.id,
        ticket_code=ticket.ticket_code,
        title=ticket.title,
        description=ticket.description,
        customer_id=ticket.customer_id,
        customer_name=ticket.customer.full_name if ticket.customer else None,
        customer_email=ticket.customer.email if ticket.customer else None,
        assigned_agent_id=ticket.assigned_agent_id,
        assigned_agent_name=ticket.assigned_agent.full_name if ticket.assigned_agent else None,
        linked_conversation_id=ticket.linked_conversation_id,
        category=ticket.category,
        priority=ticket.priority,
        status=ticket.status,
        category_confidence=ticket.category_confidence,
        ai_summary=ticket.ai_summary,
        ai_suggested_response=ticket.ai_suggested_response,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        activities=act_responses,
    )


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Support Ticket",
    description="Submits a new support ticket and attaches it to the authenticated customer account.",
)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketResponse:
    ticket = ticket_service.create_ticket(db=db, customer=current_user, data=payload)
    return _format_ticket_response(ticket)


@router.get(
    "",
    response_model=TicketListResponse,
    summary="List Support Tickets",
    description="Lists support tickets with text search, priority, status, and category filtering. Customers are strictly restricted to their own tickets.",
)
def list_tickets(
    search: Optional[str] = Query(None, description="Search by ticket code, title, or description"),
    status: Optional[TicketStatus] = Query(None, description="Filter by status"),
    priority: Optional[TicketPriority] = Query(None, description="Filter by priority"),
    category: Optional[TicketCategory] = Query(None, description="Filter by category"),
    assigned_agent_id: Optional[int] = Query(None, description="Filter by assigned staff ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketListResponse:
    total, items = ticket_service.list_tickets(
        db=db,
        current_user=current_user,
        search=search,
        status_filter=status,
        priority_filter=priority,
        category_filter=category,
        assigned_agent_id=assigned_agent_id,
        skip=skip,
        limit=limit,
    )

    formatted_items = [_format_ticket_response(t) for t in items]
    return TicketListResponse(
        total=total,
        skip=skip,
        limit=limit,
        items=formatted_items,
    )


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Get Ticket Details",
    description="Fetches full ticket details and activity history. Private agent notes are withheld from customers.",
)
def get_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketResponse:
    ticket, activities = ticket_service.get_ticket_or_404(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
    )
    return _format_ticket_response(ticket, activities)


@router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    summary="Update Ticket",
    description="Modifies ticket attributes such as status, priority, or category and logs transition audit events.",
)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketResponse:
    ticket = ticket_service.update_ticket(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
        data=payload,
    )
    _, activities = ticket_service.get_ticket_or_404(db=db, ticket_id=ticket.id, current_user=current_user)
    return _format_ticket_response(ticket, activities)


@router.post(
    "/{ticket_id}/assign",
    response_model=TicketResponse,
    summary="Assign Ticket to Support Agent",
    description="Reassigns or unassigns a ticket. Restricted to support agents and administrators.",
)
def assign_ticket(
    ticket_id: int,
    payload: TicketAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_admin),
) -> TicketResponse:
    ticket = ticket_service.assign_ticket(
        db=db,
        ticket_id=ticket_id,
        agent_id=payload.assigned_agent_id,
        current_user=current_user,
    )
    _, activities = ticket_service.get_ticket_or_404(db=db, ticket_id=ticket.id, current_user=current_user)
    return _format_ticket_response(ticket, activities)


@router.post(
    "/{ticket_id}/notes",
    response_model=TicketActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Post Ticket Note or Reply",
    description="Adds a public reply or internal staff note. Customers cannot post internal notes.",
)
def add_note_or_reply(
    ticket_id: int,
    payload: TicketNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TicketActivityResponse:
    activity = ticket_service.add_ticket_activity(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
        data=payload,
    )
    return TicketActivityResponse(
        id=activity.id,
        ticket_id=activity.ticket_id,
        author_id=activity.author_id,
        author_name=current_user.full_name,
        author_role=current_user.role.value,
        activity_type=activity.activity_type,
        old_value=activity.old_value,
        new_value=activity.new_value,
        note=activity.note,
        is_internal=activity.is_internal,
        created_at=activity.created_at,
    )


@router.post(
    "/{ticket_id}/suggest-reply",
    response_model=TicketSuggestionResponse,
    summary="Generate AI-Suggested Reply",
    description="Analyzes ticket context and generates an editable draft response for support agents to review.",
)
def suggest_reply(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_agent_or_admin),
) -> TicketSuggestionResponse:
    return ticket_service.generate_suggested_reply(
        db=db,
        ticket_id=ticket_id,
        current_user=current_user,
    )
