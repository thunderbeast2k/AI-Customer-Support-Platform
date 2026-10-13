"""
Unit and Integration Tests for Phase 3: Support Ticket Management, Privacy Scoping, and AI Suggestions.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.user import User, UserRole

# In-memory SQLite database
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


def test_ticket_creation_and_unique_code():
    """Verify customer can create a ticket with unique code generation."""
    cust_token = _register_user("cust1@example.com", "customer", "Customer One")

    payload = {
        "title": "Cannot access billing portal",
        "description": "Whenever I click billing, I get a blank screen with error 404.",
        "category": "billing",
        "priority": "high",
    }
    response = client.post(
        "/api/v1/tickets",
        json=payload,
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["ticket_code"].startswith("TIK-")
    assert data["title"] == payload["title"]
    assert data["status"] == "open"
    assert data["customer_email"] == "cust1@example.com"


def test_customer_data_isolation():
    """Verify Customer A cannot view Customer B's ticket."""
    cust1_token = _register_user("cust1@example.com", "customer", "Customer One")
    cust2_token = _register_user("cust2@example.com", "customer", "Customer Two")

    # Customer 1 creates ticket
    t_res = client.post(
        "/api/v1/tickets",
        json={"title": "Private issue", "description": "Confidential customer details"},
        headers={"Authorization": f"Bearer {cust1_token}"},
    )
    ticket_id = t_res.json()["id"]

    # Customer 1 can view
    get_res1 = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {cust1_token}"},
    )
    assert get_res1.status_code == 200

    # Customer 2 attempts to view -> 403 Forbidden
    get_res2 = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {cust2_token}"},
    )
    assert get_res2.status_code == 403
    assert "Access denied" in get_res2.json()["detail"]


def test_agent_can_view_all_tickets_and_assign():
    """Verify support agent can view all tickets and reassign agents."""
    cust_token = _register_user("cust@example.com", "customer", "Customer")
    agent_token = _register_user("agent@example.com", "agent", "Agent")

    # Create ticket
    t_res = client.post(
        "/api/v1/tickets",
        json={"title": "Agent assignment test", "description": "Needs review by senior agent"},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    ticket_id = t_res.json()["id"]

    # Agent gets ticket
    agent_get = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert agent_get.status_code == 200

    # Agent assigns ticket to themselves
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {agent_token}"})
    agent_id = me_res.json()["id"]

    assign_res = client.post(
        f"/api/v1/tickets/{ticket_id}/assign",
        json={"assigned_agent_id": agent_id},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert assign_res.status_code == 200
    assert assign_res.json()["assigned_agent_id"] == agent_id


def test_internal_agent_notes_hidden_from_customer():
    """Verify internal notes are strictly visible to staff and hidden from customer."""
    cust_token = _register_user("cust@example.com", "customer", "Customer")
    agent_token = _register_user("agent@example.com", "agent", "Agent")

    # Customer creates ticket
    t_res = client.post(
        "/api/v1/tickets",
        json={"title": "Internal note test", "description": "Customer inquiry description"},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    ticket_id = t_res.json()["id"]

    # Agent posts private internal note
    note_res = client.post(
        f"/api/v1/tickets/{ticket_id}/notes",
        json={"note": "CONFIDENTIAL: Customer flagged for chargeback risk.", "is_internal": True},
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert note_res.status_code == 201

    # Agent views ticket -> internal note is present
    agent_view = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    agent_notes = [a["note"] for a in agent_view.json()["activities"] if a["is_internal"]]
    assert len(agent_notes) == 1
    assert "CONFIDENTIAL" in agent_notes[0]

    # Customer views ticket -> internal note is completely omitted!
    cust_view = client.get(
        f"/api/v1/tickets/{ticket_id}",
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    cust_notes = [a["note"] for a in cust_view.json()["activities"] if a["is_internal"]]
    assert len(cust_notes) == 0
    assert not any("CONFIDENTIAL" in a.get("note", "") for a in cust_view.json()["activities"])


def test_customer_cannot_post_internal_note():
    """Verify customers receive 403 if they attempt to post an internal note."""
    cust_token = _register_user("cust@example.com", "customer", "Customer")

    t_res = client.post(
        "/api/v1/tickets",
        json={"title": "Note permission test", "description": "Customer description"},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    ticket_id = t_res.json()["id"]

    res = client.post(
        f"/api/v1/tickets/{ticket_id}/notes",
        json={"note": "Try to post private", "is_internal": True},
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert res.status_code == 403
    assert "Customers cannot create private internal notes" in res.json()["detail"]


def test_ai_suggested_reply():
    """Verify support agent can generate editable AI-suggested response."""
    cust_token = _register_user("cust@example.com", "customer", "Customer")
    agent_token = _register_user("agent@example.com", "agent", "Agent")

    t_res = client.post(
        "/api/v1/tickets",
        json={
            "title": "Refund inquiry on order #9821",
            "description": "I would like a refund because the service was not activated.",
            "category": "refund_request",
        },
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    ticket_id = t_res.json()["id"]

    res = client.post(
        f"/api/v1/tickets/{ticket_id}/suggest-reply",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "suggested_reply" in data
    assert "Dear Customer" in data["suggested_reply"] or "Customer" in data["suggested_reply"]
    assert "refund" in data["suggested_reply"].lower()
    assert len(data["key_points"]) > 0
    assert data["confidence_score"] > 0.8
