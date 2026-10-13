"""
Chat Service: Manages Customer Conversations, Context Persistence, Citations, and AI Generation.
"""
from datetime import datetime, timezone
import time
from typing import Optional, List, Tuple
from sqlalchemy import desc
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.user import User, UserRole
from app.models.conversation import Conversation, ConversationStatus, Message, MessageSenderType
from app.models.ticket import Ticket, TicketActivity, TicketCategory, TicketPriority, TicketStatus
from app.models.audit import ModelUsage
from app.schemas.conversation import ConversationCreate, ConversationUpdate, EscalateConversationRequest
from app.services.ticket_service import generate_unique_ticket_code


def create_conversation(
    db: Session,
    customer: User,
    data: ConversationCreate,
) -> Conversation:
    """Initializes a new customer conversation."""
    title = data.title or "New Conversation"
    if data.initial_message and title == "New Conversation":
        # Derive initial title from snippet
        snippet = data.initial_message.strip()
        title = (snippet[:40] + "...") if len(snippet) > 40 else snippet

    conv = Conversation(
        customer_id=customer.id,
        title=title,
        status=ConversationStatus.ACTIVE,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # If initial message provided, process it immediately
    if data.initial_message:
        post_message_and_respond(
            db=db,
            conversation_id=conv.id,
            current_user=customer,
            content=data.initial_message,
        )
        db.refresh(conv)

    return conv


def get_conversation_or_404(
    db: Session,
    conversation_id: int,
    current_user: User,
) -> Conversation:
    """
    Fetches a conversation and guarantees customer data isolation.
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation with ID {conversation_id} not found",
        )

    # Customer data ownership isolation
    if current_user.role == UserRole.CUSTOMER and conv.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: You do not have permission to view this conversation",
        )

    return conv


def list_conversations(
    db: Session,
    current_user: User,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[int, List[Conversation]]:
    """
    Lists conversations. Customers see only their own sessions; agents/admins can browse all.
    """
    query = db.query(Conversation)
    if current_user.role == UserRole.CUSTOMER:
        query = query.filter(Conversation.customer_id == current_user.id)

    total = query.count()
    items = query.order_by(desc(Conversation.updated_at)).offset(skip).limit(limit).all()
    return total, items


def _synthesize_ai_response(
    query_text: str,
    history: List[Message],
    customer_name: str,
) -> Tuple[str, List[dict], dict]:
    """
    AI Response Engine: Generates grounded answers, citations, and insufficient-evidence fallbacks.
    """
    q_lower = query_text.lower()
    citations = []
    metadata = {
        "model": "gemini-1.5-flash",
        "provider": "mock_adapter",
        "tokens": 0,
        "latency_ms": 0.0,
    }

    start_time = time.perf_counter()

    # Case 1: Billing & Refund Policies
    if any(k in q_lower for k in ["refund", "billing", "charge", "invoice", "double bill", "cost", "cancel"]):
        content = (
            f"Hello {customer_name}, based on our official Billing & Refund Policy (Section 3.2), "
            f"subscription charges are processed on the 1st of each billing month. If you observe duplicate charges, "
            f"one is typically a temporary authorization hold that drops off within 24–72 hours.\n\n"
            f"If an actual duplicate payment cleared your bank account, we can issue an immediate refund back to "
            f"your original payment method, which settles in 3–5 business days.\n\n"
            f"Would you like me to open a support ticket for our billing team to process this refund for you?"
        )
        citations = [
            {
                "document_title": "Billing & Refund Policies 2026.pdf",
                "chunk_id": 1,
                "snippet": "Duplicate authorization holds are voided within 72 hours; confirmed errors are refunded within 3-5 business days.",
                "relevance_score": 0.94,
            },
            {
                "document_title": "Enterprise Subscription Terms.md",
                "chunk_id": 4,
                "snippet": "Billing cycle renewals take effect at 00:00 UTC on the anniversary date.",
                "relevance_score": 0.88,
            },
        ]
        tokens = 240

    # Case 2: Technical / SSO / Okta Integration
    elif any(k in q_lower for k in ["sso", "saml", "okta", "login", "timeout", "504", "error", "api key"]):
        content = (
            f"Regarding your inquiry on SAML / SSO authentication: timeouts during callback (such as HTTP 504) "
            f"are commonly caused by clock skew between your Identity Provider (e.g., Okta) and our authentication cluster, "
            f"or an expired X.509 signing certificate in your SAML app settings.\n\n"
            f"Recommended troubleshooting steps:\n"
            f"1. Verify the Assertion Consumer Service (ACS) URL in Okta matches: https://api.support.ai/v1/auth/sso/callback\n"
            f"2. Confirm your IdP certificate has not expired in the admin console.\n\n"
            f"If the issue persists, our technical engineering team can inspect the gateway logs for your tenant."
        )
        citations = [
            {
                "document_title": "SAML and Okta SSO Configuration Guide.md",
                "chunk_id": 2,
                "snippet": "ACS URL must match https://api.support.ai/v1/auth/sso/callback with SHA-256 certificate signing.",
                "relevance_score": 0.96,
            }
        ]
        tokens = 280

    # Case 3: Customer requesting human agent or escalation
    elif any(k in q_lower for k in ["human", "agent", "representative", "speak to someone", "escalate", "help me now"]):
        content = (
            f"I completely understand you would like to speak directly with a human support agent. "
            f"I can immediately escalate our conversation into a high-priority support ticket assigned to our on-duty team.\n\n"
            f"Click the 'Escalate to Support Ticket' button above or let me know, and an agent will follow up directly."
        )
        citations = []
        tokens = 110

    # Case 4: General Inquiries with safe fallback
    else:
        content = (
            f"Thank you for your question, {customer_name}. While I have searched our internal knowledge base, "
            f"I could not locate sufficiently high-confidence documentation to answer your specific request directly.\n\n"
            f"To make sure you get accurate assistance without guesswork, I recommend escalating this to a human support agent, "
            f"who will investigate and follow up with you."
        )
        citations = []
        tokens = 135

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    metadata["tokens"] = tokens
    metadata["latency_ms"] = elapsed_ms

    return content, citations, metadata


def post_message_and_respond(
    db: Session,
    conversation_id: int,
    current_user: User,
    content: str,
) -> Tuple[Message, Optional[Message]]:
    """
    Appends customer message to conversation, fetches context, and generates an AI response.
    """
    conv = get_conversation_or_404(db=db, conversation_id=conversation_id, current_user=current_user)

    # 1. Save customer message
    user_msg = Message(
        conversation_id=conv.id,
        sender_type=MessageSenderType.CUSTOMER if current_user.role == UserRole.CUSTOMER else MessageSenderType.AGENT,
        sender_id=current_user.id,
        content=content.strip(),
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Auto-rename title if it was placeholder
    if conv.title == "New Conversation":
        snippet = content.strip()
        conv.title = (snippet[:35] + "...") if len(snippet) > 35 else snippet

    # 2. If message was from customer, trigger AI response
    ai_msg = None
    if current_user.role == UserRole.CUSTOMER:
        recent_messages = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(desc(Message.created_at))
            .limit(10)
            .all()
        )
        recent_messages.reverse()

        ai_content, citations, metadata = _synthesize_ai_response(
            query_text=content,
            history=recent_messages,
            customer_name=current_user.full_name,
        )

        ai_msg = Message(
            conversation_id=conv.id,
            sender_type=MessageSenderType.AI,
            content=ai_content,
            citations=citations,
            metadata_json=metadata,
        )
        db.add(ai_msg)

        # Record token usage in model_usage table
        usage = ModelUsage(
            user_id=current_user.id,
            conversation_id=conv.id,
            provider="mock",
            model_name="gemini-1.5-flash",
            operation="chat_response",
            prompt_tokens=metadata.get("tokens", 100),
            completion_tokens=int(metadata.get("tokens", 100) * 0.6),
            total_tokens=metadata.get("tokens", 100),
            latency_ms=metadata.get("latency_ms", 150.0),
            estimated_cost_usd=0.00012,
        )
        db.add(usage)

    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    if ai_msg:
        db.refresh(ai_msg)

    return user_msg, ai_msg


def escalate_conversation_to_ticket(
    db: Session,
    conversation_id: int,
    current_user: User,
    data: EscalateConversationRequest,
) -> Ticket:
    """
    Creates a support ticket directly linked to an ongoing conversation.
    """
    conv = get_conversation_or_404(db=db, conversation_id=conversation_id, current_user=current_user)

    # Check if a ticket is already linked
    existing_ticket = db.query(Ticket).filter(Ticket.linked_conversation_id == conv.id).first()
    if existing_ticket:
        return existing_ticket

    # Collect customer message summary
    recent_msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(desc(Message.created_at))
        .limit(5)
        .all()
    )
    recent_msgs.reverse()

    summary_text = "\n".join([f"{m.sender_type.value}: {m.content}" for m in recent_msgs])
    if data.reason:
        summary_text = f"Escalation Reason: {data.reason}\n\nRecent Transcript:\n" + summary_text

    ticket_code = generate_unique_ticket_code(db)
    title = data.title or f"Escalated Chat: {conv.title}"

    ticket = Ticket(
        ticket_code=ticket_code,
        title=title,
        description=summary_text,
        customer_id=conv.customer_id,
        category=data.category or TicketCategory.GENERAL_INQUIRY,
        priority=data.priority or TicketPriority.HIGH,
        status=TicketStatus.OPEN,
        linked_conversation_id=conv.id,
        ai_summary=f"Escalated from active conversation #{conv.id} ({conv.title}).",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # Add initial activity
    act = TicketActivity(
        ticket_id=ticket.id,
        author_id=current_user.id,
        activity_type="created",
        new_value=ticket.status.value,
        note=f"Ticket {ticket.ticket_code} created directly from conversation #{conv.id}.",
        is_internal=False,
    )
    db.add(act)

    # Add system notification message to the conversation
    sys_msg = Message(
        conversation_id=conv.id,
        sender_type=MessageSenderType.SYSTEM,
        content=f"Your conversation has been escalated to support ticket {ticket.ticket_code}. An agent has been notified.",
        metadata_json={"ticket_id": ticket.id, "ticket_code": ticket.ticket_code},
    )
    db.add(sys_msg)

    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    return ticket
