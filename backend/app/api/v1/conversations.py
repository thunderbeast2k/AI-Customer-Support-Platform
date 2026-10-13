"""
Customer Conversation API Endpoints.
Handles chat creation, message streams, RAG-grounded responses, and ticket escalation.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.models.conversation import Conversation, ConversationStatus
from app.schemas.conversation import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationListResponse,
    MessageCreate,
    MessageResponse,
    EscalateConversationRequest,
)
from app.schemas.ticket import TicketResponse
from app.api.deps import get_current_user
from app.services import chat_service
from app.services.ticket_service import get_ticket_or_404

router = APIRouter(prefix="/conversations", tags=["Customer Chat & Conversations"])


def _format_conversation_response(conv: Conversation) -> ConversationResponse:
    """Helper to convert Conversation ORM model to ConversationResponse."""
    msg_responses = [
        MessageResponse(
            id=m.id,
            conversation_id=m.conversation_id,
            sender_type=m.sender_type,
            sender_id=m.sender_id,
            content=m.content,
            citations=m.citations,
            metadata_json=m.metadata_json,
            created_at=m.created_at,
        )
        for m in conv.messages
    ]

    linked_ticket_code = None
    linked_ticket_id = None
    if conv.ticket:
        linked_ticket_code = conv.ticket.ticket_code
        linked_ticket_id = conv.ticket.id

    return ConversationResponse(
        id=conv.id,
        customer_id=conv.customer_id,
        customer_name=conv.customer.full_name if conv.customer else None,
        customer_email=conv.customer.email if conv.customer else None,
        title=conv.title,
        status=conv.status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=msg_responses,
        linked_ticket_code=linked_ticket_code,
        linked_ticket_id=linked_ticket_id,
    )


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start New Conversation",
    description="Initializes a new customer support chat session, optionally sending an initial message.",
)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationResponse:
    conv = chat_service.create_conversation(db=db, customer=current_user, data=payload)
    return _format_conversation_response(conv)


@router.get(
    "",
    response_model=ConversationListResponse,
    summary="List Conversations",
    description="Lists previous conversation sessions. Customers are strictly restricted to their own sessions.",
)
def list_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationListResponse:
    total, items = chat_service.list_conversations(
        db=db,
        current_user=current_user,
        skip=skip,
        limit=limit,
    )
    formatted = [_format_conversation_response(c) for c in items]
    return ConversationListResponse(total=total, skip=skip, limit=limit, items=formatted)


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Get Conversation Messages",
    description="Returns complete message history, citations, and metadata for a conversation.",
)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationResponse:
    conv = chat_service.get_conversation_or_404(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
    )
    return _format_conversation_response(conv)


@router.post(
    "/{conversation_id}/messages",
    response_model=List[MessageResponse],
    summary="Send Message & Receive AI Answer",
    description="Appends customer query to conversation, queries knowledge base with Sentence Transformers, and generates context-grounded AI answer with source citations.",
)
def post_message(
    conversation_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[MessageResponse]:
    user_msg, ai_msg = chat_service.post_message_and_respond(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
        content=payload.content,
    )

    result = [
        MessageResponse(
            id=user_msg.id,
            conversation_id=user_msg.conversation_id,
            sender_type=user_msg.sender_type,
            sender_id=user_msg.sender_id,
            content=user_msg.content,
            citations=user_msg.citations,
            metadata_json=user_msg.metadata_json,
            created_at=user_msg.created_at,
        )
    ]

    if ai_msg:
        result.append(
            MessageResponse(
                id=ai_msg.id,
                conversation_id=ai_msg.conversation_id,
                sender_type=ai_msg.sender_type,
                sender_id=ai_msg.sender_id,
                content=ai_msg.content,
                citations=ai_msg.citations,
                metadata_json=ai_msg.metadata_json,
                created_at=ai_msg.created_at,
            )
        )

    return result


@router.post(
    "/{conversation_id}/escalate-ticket",
    summary="Escalate Conversation into Support Ticket",
    description="Converts conversation transcript into a formal tracked support ticket.",
)
def escalate_to_ticket(
    conversation_id: int,
    payload: EscalateConversationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = chat_service.escalate_conversation_to_ticket(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
        data=payload,
    )
    return {
        "message": f"Successfully escalated conversation #{conversation_id} to ticket {ticket.ticket_code}",
        "ticket_id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "status": ticket.status.value,
        "category": ticket.category.value,
        "priority": ticket.priority.value,
    }


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Update Conversation Status or Title",
)
def update_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationResponse:
    conv = chat_service.get_conversation_or_404(
        db=db,
        conversation_id=conversation_id,
        current_user=current_user,
    )

    if payload.title:
        conv.title = payload.title.strip()
    if payload.status:
        conv.status = payload.status

    db.commit()
    db.refresh(conv)
    return _format_conversation_response(conv)
