"""
ORM Models Package.
Exports all database entities for SQLAlchemy and Alembic autogeneration.
"""
from app.models.user import User, UserRole
from app.models.conversation import Conversation, ConversationStatus, Message, MessageSenderType
from app.models.ticket import Ticket, TicketActivity, TicketCategory, TicketPriority, TicketStatus
from app.models.knowledge import KnowledgeDocument, DocumentChunk, DocumentStatus
from app.models.audit import ModelUsage, AuditEvent

__all__ = [
    "User",
    "UserRole",
    "Conversation",
    "ConversationStatus",
    "Message",
    "MessageSenderType",
    "Ticket",
    "TicketActivity",
    "TicketCategory",
    "TicketPriority",
    "TicketStatus",
    "KnowledgeDocument",
    "DocumentChunk",
    "DocumentStatus",
    "ModelUsage",
    "AuditEvent",
]
