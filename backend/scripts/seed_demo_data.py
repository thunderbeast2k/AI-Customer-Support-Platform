#!/usr/bin/env python3
"""
Seed Script for Phase 2 Development and Demo Accounts.
Inserts demo accounts (Admin, Agent, Customer), sample tickets, conversations,
and knowledge base documents into PostgreSQL.

Usage:
    python scripts/seed_demo_data.py
"""
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal, Base, engine, init_db_extensions
from app.core.security import get_password_hash
from app.models.user import User, UserRole
from app.models.conversation import Conversation, ConversationStatus, Message, MessageSenderType
from app.models.ticket import Ticket, TicketActivity, TicketCategory, TicketPriority, TicketStatus
from app.models.knowledge import KnowledgeDocument, DocumentStatus
from app.models.audit import AuditEvent


def seed_database():
    print("\n" + "=" * 60)
    print(" AI Customer Support Platform - Phase 2 Database Seeding")
    print("=" * 60)

    # Ensure pgvector extension and tables exist
    init_db_extensions()
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # 1. Seed Demo Users
        print("\n1. Seeding Demo Users...")
        demo_users = [
            {
                "email": "admin@support.ai",
                "password": "AdminPass123!",
                "full_name": "Sarah Chen (Administrator)",
                "role": UserRole.ADMIN,
            },
            {
                "email": "agent@support.ai",
                "password": "AgentPass123!",
                "full_name": "Alex Rivera (Senior Agent)",
                "role": UserRole.AGENT,
            },
            {
                "email": "customer@support.ai",
                "password": "CustomerPass123!",
                "full_name": "Jordan Lee (Customer)",
                "role": UserRole.CUSTOMER,
            },
        ]

        user_objects = {}
        for u in demo_users:
            existing = db.query(User).filter(User.email == u["email"]).first()
            if not existing:
                user = User(
                    email=u["email"],
                    hashed_password=get_password_hash(u["password"]),
                    full_name=u["full_name"],
                    role=u["role"],
                    is_active=True,
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                user_objects[u["role"]] = user
                print(f"   [CREATED] {u['role'].value.upper()}: {u['email']} (Password: {u['password']})")
            else:
                user_objects[u["role"]] = existing
                print(f"   [EXISTS]  {u['role'].value.upper()}: {u['email']}")

        admin = user_objects.get(UserRole.ADMIN)
        agent = user_objects.get(UserRole.AGENT)
        customer = user_objects.get(UserRole.CUSTOMER)

        # 2. Seed Sample Conversations & Messages
        print("\n2. Seeding Sample Customer Conversation...")
        conv = db.query(Conversation).filter(Conversation.customer_id == customer.id).first()
        if not conv:
            conv = Conversation(
                customer_id=customer.id,
                title="Billing cycle and invoice inquiry",
                status=ConversationStatus.ACTIVE,
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)

            messages = [
                Message(
                    conversation_id=conv.id,
                    sender_type=MessageSenderType.CUSTOMER,
                    sender_id=customer.id,
                    content="Hello, I was charged twice for my subscription this month. Can you assist?",
                ),
                Message(
                    conversation_id=conv.id,
                    sender_type=MessageSenderType.AI,
                    content="I've located your recent billing transactions. According to our policy, duplicate charges are typically held in pre-authorization status and cleared within 3 business days. Would you like me to open a high-priority refund ticket for an agent?",
                    citations=[
                        {
                            "document": "Billing & Refund Policies 2026.pdf",
                            "chunk_id": 1,
                            "relevance_score": 0.92,
                        }
                    ],
                    metadata_json={"model": "gemini-1.5-flash", "latency_ms": 320},
                ),
            ]
            db.add_all(messages)
            db.commit()
            print(f"   [CREATED] Conversation ID: {conv.id} with 2 messages.")
        else:
            print(f"   [EXISTS]  Conversation ID: {conv.id}")

        # 3. Seed Sample Tickets
        print("\n3. Seeding Sample Support Tickets...")
        sample_tickets = [
            {
                "code": "TIK-2026-1001",
                "title": "Duplicate charge on Enterprise subscription renewal",
                "description": "Customer Jordan Lee reported duplicate invoice charges on transaction #INV-9821.",
                "customer_id": customer.id,
                "agent_id": agent.id,
                "category": TicketCategory.REFUND_REQUEST,
                "priority": TicketPriority.HIGH,
                "status": TicketStatus.IN_PROGRESS,
                "linked_conv": conv.id,
                "ai_summary": "Customer charged twice for monthly enterprise tier. Invoice INV-9821 needs refund review.",
            },
            {
                "code": "TIK-2026-1002",
                "title": "SAML SSO Okta authentication callback timeout",
                "description": "Enterprise login redirects to 504 gateway timeout after identity provider approval.",
                "customer_id": customer.id,
                "agent_id": agent.id,
                "category": TicketCategory.TECHNICAL_ISSUE,
                "priority": TicketPriority.URGENT,
                "status": TicketStatus.OPEN,
                "linked_conv": None,
                "ai_summary": "SAML SSO assertion timeout with Okta IDP.",
            },
            {
                "code": "TIK-2026-1003",
                "title": "Download receipt PDF for September tax filing",
                "description": "Customer requested copy of past receipt with VAT registration number.",
                "customer_id": customer.id,
                "agent_id": None,
                "category": TicketCategory.BILLING,
                "priority": TicketPriority.LOW,
                "status": TicketStatus.RESOLVED,
                "linked_conv": None,
                "ai_summary": "VAT tax receipt document request.",
            },
        ]

        for st in sample_tickets:
            existing_t = db.query(Ticket).filter(Ticket.ticket_code == st["code"]).first()
            if not existing_t:
                ticket = Ticket(
                    ticket_code=st["code"],
                    title=st["title"],
                    description=st["description"],
                    customer_id=st["customer_id"],
                    assigned_agent_id=st["agent_id"],
                    category=st["category"],
                    priority=st["priority"],
                    status=st["status"],
                    linked_conversation_id=st["linked_conv"],
                    ai_summary=st["ai_summary"],
                    category_confidence=0.94,
                )
                db.add(ticket)
                db.commit()
                db.refresh(ticket)

                # Add initial activity
                activity = TicketActivity(
                    ticket_id=ticket.id,
                    author_id=agent.id,
                    activity_type="created",
                    new_value=ticket.status.value,
                    note="Ticket initialized via platform ingest.",
                    is_internal=False,
                )
                db.add(activity)
                db.commit()
                print(f"   [CREATED] Ticket: {st['code']} - {st['title']} ({st['status'].value.upper()})")
            else:
                print(f"   [EXISTS]  Ticket: {st['code']}")

        # 4. Seed Sample Knowledge Base Documents
        print("\n4. Seeding Knowledge Document Metadata...")
        sample_docs = [
            {
                "title": "Billing & Refund Policies 2026",
                "filename": "Billing_Refund_Policies_2026.pdf",
                "file_type": "pdf",
                "size": 142800,
                "hash": "a8f9b4c2d3e14589710328490123abcd891234ef0123456789abcdef01234567",
                "chunks": 14,
            },
            {
                "title": "SAML and Okta SSO Configuration Guide",
                "filename": "Okta_SSO_Configuration.md",
                "file_type": "md",
                "size": 48200,
                "hash": "b7e2c1d0f5a43219876543210987bcde9876543210fedcba9876543210fedcba",
                "chunks": 8,
            },
        ]

        for sd in sample_docs:
            existing_d = db.query(KnowledgeDocument).filter(KnowledgeDocument.content_hash == sd["hash"]).first()
            if not existing_d:
                k_doc = KnowledgeDocument(
                    title=sd["title"],
                    filename=sd["filename"],
                    file_type=sd["file_type"],
                    file_size_bytes=sd["size"],
                    content_hash=sd["hash"],
                    status=DocumentStatus.INDEXED,
                    chunk_count=sd["chunks"],
                )
                db.add(k_doc)
                db.commit()
                print(f"   [CREATED] Knowledge Doc: {sd['title']} ({sd['chunks']} chunks)")
            else:
                print(f"   [EXISTS]  Knowledge Doc: {sd['title']}")

        # Record Audit Log
        audit = AuditEvent(
            user_id=admin.id,
            event_type="system.database_seed",
            target_type="database",
            target_id="customer_support_db",
            details={"phase": "Phase 2", "seeded_by": "seed_demo_data.py"},
        )
        db.add(audit)
        db.commit()

        print("\n" + "=" * 60)
        print(" Seed Completed Successfully!")
        print(" Demo Accounts Ready:")
        print("   - Admin:    admin@support.ai    / AdminPass123!")
        print("   - Agent:    agent@support.ai    / AgentPass123!")
        print("   - Customer: customer@support.ai / CustomerPass123!")
        print("=" * 60 + "\n")

    except Exception as exc:
        db.rollback()
        print(f"\n[FAIL] Seeding encountered an error: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
