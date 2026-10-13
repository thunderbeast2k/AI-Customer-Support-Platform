"""
Pydantic Schemas for Customer Conversations, Messages, and Citations.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.models.conversation import ConversationStatus, MessageSenderType
from app.models.ticket import TicketCategory, TicketPriority


class CitationItem(BaseModel):
    document_title: str
    chunk_id: Optional[int] = None
    snippet: Optional[str] = None
    relevance_score: float = Field(..., ge=0.0, le=1.0)


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000, description="Customer inquiry or message text")


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_type: MessageSenderType
    sender_id: Optional[int] = None
    content: str
    citations: Optional[List[Dict[str, Any]]] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(default="New Conversation", max_length=255)
    initial_message: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    status: Optional[ConversationStatus] = None


class ConversationResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    title: str
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse] = []
    linked_ticket_code: Optional[str] = None
    linked_ticket_id: Optional[int] = None

    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[ConversationResponse]


class EscalateConversationRequest(BaseModel):
    title: Optional[str] = Field(None, description="Ticket title. Defaults to conversation topic")
    category: Optional[TicketCategory] = Field(default=TicketCategory.GENERAL_INQUIRY)
    priority: Optional[TicketPriority] = Field(default=TicketPriority.MEDIUM)
    reason: Optional[str] = Field(None, description="Why the customer requested escalation to human agent")
