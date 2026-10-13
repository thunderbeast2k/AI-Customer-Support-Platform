"""
Pydantic Schemas for Ticket Management and Activity Audit Trails.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.models.ticket import TicketCategory, TicketPriority, TicketStatus


class TicketActivityResponse(BaseModel):
    id: int
    ticket_id: int
    author_id: Optional[int]
    author_name: Optional[str] = None
    author_role: Optional[str] = None
    activity_type: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    note: Optional[str] = None
    is_internal: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255, description="Brief summary of the issue")
    description: str = Field(..., min_length=10, description="Full explanation of the customer inquiry or problem")
    category: Optional[TicketCategory] = Field(default=TicketCategory.GENERAL_INQUIRY)
    priority: Optional[TicketPriority] = Field(default=TicketPriority.MEDIUM)
    linked_conversation_id: Optional[int] = None


class TicketUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = None
    category: Optional[TicketCategory] = None
    priority: Optional[TicketPriority] = None
    status: Optional[TicketStatus] = None


class TicketAssign(BaseModel):
    assigned_agent_id: Optional[int] = Field(..., description="Agent user ID, or null to unassign")


class TicketNoteCreate(BaseModel):
    note: str = Field(..., min_length=1, description="Message content or internal note")
    is_internal: bool = Field(default=False, description="True if private agent note, hidden from customer")


class TicketResponse(BaseModel):
    id: int
    ticket_code: str
    title: str
    description: str
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    assigned_agent_id: Optional[int] = None
    assigned_agent_name: Optional[str] = None
    linked_conversation_id: Optional[int] = None
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    category_confidence: Optional[float] = None
    ai_summary: Optional[str] = None
    ai_suggested_response: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    activities: List[TicketActivityResponse] = []

    class Config:
        from_attributes = True


class TicketListResponse(BaseModel):
    total: int
    skip: int
    limit: int
    items: List[TicketResponse]


class TicketSuggestionResponse(BaseModel):
    ticket_id: int
    ticket_code: str
    suggested_reply: str
    key_points: List[str]
    confidence_score: float
    model_name: str
