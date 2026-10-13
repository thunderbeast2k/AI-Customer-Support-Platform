"""
Unit and Integration Tests for Phase 4: Customer Conversations, Message Streams, Citations, and Ticket Escalation.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db

SQLALCHEMY_DATABASE_URL = "sqlite://"

test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield


def _register_user(email: str, role: str, name: str) -> str:
    res = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": name, "role": role},
    )
    return res.json()["access_token"]


def test_start_conversation_and_post_message():
    """Verify customer can start a conversation, send a query, and receive an AI response with citations."""
    cust_token = _register_user("cust@example.com", "customer", "Jordan Lee")

    # 1. Start conversation
    create_res = client.post(
        "/api/v1/conversations",
        json={"title": "Billing inquiry"},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert create_res.status_code == 201
    conv_id = create_res.json()["id"]

    # 2. Post inquiry about refund
    msg_res = client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Can I get a refund for duplicate billing charges?"},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert msg_res.status_code == 200
    messages = msg_res.json()
    assert len(messages) == 2

    user_msg = messages[0]
    ai_msg = messages[1]

    assert user_msg["sender_type"] == "customer"
    assert "refund" in user_msg["content"].lower()

    assert ai_msg["sender_type"] == "ai"
    assert "refund" in ai_msg["content"].lower()
    assert len(ai_msg["citations"]) > 0
    assert "Billing & Refund Policies 2026.pdf" in ai_msg["citations"][0]["document_title"]
    assert ai_msg["metadata_json"]["model"] == "gemini-1.5-flash"


def test_customer_conversation_isolation():
    """Verify Customer A cannot view or post messages to Customer B's conversation."""
    cust1_token = _register_user("cust1@example.com", "customer", "Customer One")
    cust2_token = _register_user("cust2@example.com", "customer", "Customer Two")

    # Customer 1 starts conversation
    c_res = client.post(
        "/api/v1/conversations",
        json={"title": "Private conversation"},
        headers={"Authorization": f"Bearer {cust1_token}"},
    )
    conv_id = c_res.json()["id"]

    # Customer 2 attempts to read -> 403 Forbidden
    get_res = client.get(
        f"/api/v1/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {cust2_token}"},
    )
    assert get_res.status_code == 403
    assert "Access denied" in get_res.json()["detail"]

    # Customer 2 attempts to post message -> 403 Forbidden
    post_res = client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Unauthorized message"},
        headers={"Authorization": f"Bearer {cust2_token}"},
    )
    assert post_res.status_code == 403


def test_insufficient_evidence_fallback():
    """Verify an unknown or unsupported query yields a safe fallback without hallucination."""
    cust_token = _register_user("cust@example.com", "customer", "Customer")

    c_res = client.post(
        "/api/v1/conversations",
        json={"title": "Unknown topic"},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    conv_id = c_res.json()["id"]

    msg_res = client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "What is the secret recipe of your company cafeteria brownies?"},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert msg_res.status_code == 200
    ai_msg = msg_res.json()[1]
    assert "could not locate sufficiently high-confidence documentation" in ai_msg["content"]
    assert len(ai_msg["citations"]) == 0


def test_escalate_conversation_to_ticket():
    """Verify customer can escalate a conversation to a formal support ticket."""
    cust_token = _register_user("cust@example.com", "customer", "Customer")

    # Start conversation
    c_res = client.post(
        "/api/v1/conversations",
        json={"title": "SSO Callback Timeout Issue"},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    conv_id = c_res.json()["id"]

    # Send message
    client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "Okta SSO times out with 504 on callback. Need staff engineer."},
        headers={"Authorization": f"Bearer {cust_token}"},
    )

    # Escalate to ticket
    esc_res = client.post(
        f"/api/v1/conversations/{conv_id}/escalate-ticket",
        json={
            "title": "Urgent: Okta SSO 504 Gateway Timeout",
            "category": "technical_issue",
            "priority": "urgent",
            "reason": "Production enterprise users blocked from logging in.",
        },
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert esc_res.status_code == 200
    data = esc_res.json()
    assert "ticket_code" in data
    assert data["ticket_code"].startswith("TIK-")
    assert data["priority"] == "urgent"
    assert data["category"] == "technical_issue"

    # Verify conversation now reflects linked ticket and system notification message
    conv_res = client.get(
        f"/api/v1/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    conv_data = conv_res.json()
    assert conv_data["linked_ticket_code"] == data["ticket_code"]
    system_msgs = [m for m in conv_data["messages"] if m["sender_type"] == "system"]
    assert len(system_msgs) == 1
    assert data["ticket_code"] in system_msgs[0]["content"]
