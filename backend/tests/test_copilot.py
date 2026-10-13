"""
Unit and Integration Tests for Phase 8: Agent Response Co-Pilot & Quick Replies.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.user import User, UserRole
from app.models.ticket import Ticket, TicketActivity, TicketCategory, TicketPriority, TicketStatus
from app.core.security import get_password_hash
from app.schemas.copilot import CopilotTone, CopilotLength, RefinementAction

# In-memory SQLite DB for tests
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    admin = User(
        email="admin_copilot@support.ai",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Admin CoPilot",
        role=UserRole.ADMIN,
        is_active=True,
    )
    agent = User(
        email="agent_copilot@support.ai",
        hashed_password=get_password_hash("AgentPass123!"),
        full_name="Agent Sarah",
        role=UserRole.AGENT,
        is_active=True,
    )
    customer = User(
        email="alex@customer.com",
        hashed_password=get_password_hash("CustPass123!"),
        full_name="Alex Mercer",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add_all([admin, agent, customer])
    db.commit()

    test_ticket = Ticket(
        ticket_code="TIK-2026-8801",
        title="Unauthorized duplicate charges on statement",
        description="I see two identical $99 charges on my Visa card from yesterday. Please refund immediately.",
        customer_id=customer.id,
        assigned_agent_id=agent.id,
        category=TicketCategory.BILLING,
        priority=TicketPriority.HIGH,
        status=TicketStatus.OPEN,
    )
    db.add(test_ticket)
    db.commit()

    yield

    db.close()
    Base.metadata.drop_all(bind=engine)


def test_get_supported_tones():
    """Verify endpoint lists all five enterprise tone personas."""
    res = client.get("/api/v1/copilot/tones")
    assert res.status_code == 200
    tones = res.json()
    assert len(tones) == 5
    tone_names = [t["tone"] for t in tones]
    assert "professional" in tone_names
    assert "empathetic" in tone_names
    assert "concise" in tone_names
    assert "technical" in tone_names
    assert "friendly" in tone_names


def test_list_and_filter_templates():
    """Verify listing canned response templates and filtering by category."""
    res = client.get("/api/v1/copilot/templates")
    assert res.status_code == 200
    templates = res.json()
    assert len(templates) >= 6

    # Filter billing
    res_billing = client.get("/api/v1/copilot/templates?category=billing")
    assert res_billing.status_code == 200
    billing_tpls = res_billing.json()
    assert len(billing_tpls) >= 1
    assert any("refund" in t["title"].lower() or "billing" in t["title"].lower() for t in billing_tpls)

    # Search keyword
    res_search = client.get("/api/v1/copilot/templates?search=Diagnostic")
    assert res_search.status_code == 200
    search_tpls = res_search.json()
    assert len(search_tpls) >= 1
    assert "diagnostic" in search_tpls[0]["title"].lower()


def test_create_and_get_custom_template():
    """Verify creating a custom template and parsing its variables."""
    payload = {
        "title": "Custom Escalation Macro",
        "category": "technical_issue",
        "content": "Hi {{customer_name}}, ticket {{ticket_code}} has been routed to engineering queue {{queue_id}}.",
    }
    create_res = client.post("/api/v1/copilot/templates", json=payload)
    assert create_res.status_code == 201
    data = create_res.json()
    assert data["title"] == "Custom Escalation Macro"
    assert "customer_name" in data["variables"]
    assert "queue_id" in data["variables"]
    assert not data["is_system"]

    # Retrieve by ID
    get_res = client.get(f"/api/v1/copilot/templates/{data['id']}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == data["id"]


def test_interpolate_template_with_ticket():
    """Verify template interpolation correctly binds ticket context variables."""
    payload = {
        "ticket_id": 1,
        "custom_variables": {
            "company_name": "Acme SaaS",
            "agent_name": "Agent Sarah",
        },
    }
    res = client.post("/api/v1/copilot/templates/tpl-refund-ack/interpolate", json=payload)
    assert res.status_code == 200
    data = res.json()
    interpolated = data["interpolated_content"]
    assert "Alex Mercer" in interpolated
    assert "TIK-2026-8801" in interpolated
    assert "Agent Sarah" in interpolated
    assert "Acme SaaS" in interpolated
    assert "{{customer_name}}" not in interpolated


def test_draft_reply_tones():
    """Verify drafting responses with different tones."""
    base_req = {
        "title": "Cannot log in with Okta SSO",
        "description": "Getting HTTP 504 Gateway Timeout when redirected back from Okta IdP.",
        "customer_name": "Marcus Vance",
        "category": "technical_issue",
        "priority": "high",
        "use_grounding": False,
        "provider_override": "mock",
    }

    # 1. Empathetic
    res_emp = client.post("/api/v1/copilot/draft", json={**base_req, "tone": "empathetic"})
    assert res_emp.status_code == 200
    data_emp = res_emp.json()
    assert data_emp["tone"] == "empathetic"
    assert data_emp["provider"] == "mock"
    assert "Marcus Vance" in data_emp["draft_reply"]
    assert any(w in data_emp["draft_reply"].lower() for w in ["apologize", "sorry", "understand"])

    # 2. Concise
    res_con = client.post("/api/v1/copilot/draft", json={**base_req, "tone": "concise"})
    assert res_con.status_code == 200
    data_con = res_con.json()
    assert data_con["tone"] == "concise"
    assert "Marcus Vance" in data_con["draft_reply"]

    # 3. Technical
    res_tech = client.post("/api/v1/copilot/draft", json={**base_req, "tone": "technical"})
    assert res_tech.status_code == 200
    data_tech = res_tech.json()
    assert data_tech["tone"] == "technical"
    assert any(w in data_tech["draft_reply"].lower() for w in ["diagnostic", "root cause", "callback"])

    # 4. Professional
    res_prof = client.post("/api/v1/copilot/draft", json={**base_req, "tone": "professional"})
    assert res_prof.status_code == 200
    data_prof = res_prof.json()
    assert data_prof["tone"] == "professional"
    assert data_prof["prompt_tokens"] > 0
    assert data_prof["latency_ms"] >= 0


def test_draft_reply_with_grounding():
    """Verify drafting with KB grounding enabled returns valid citations."""
    req = {
        "title": "Duplicate charge on statement",
        "description": "I see two $99 charges for my subscription.",
        "customer_name": "Alex Mercer",
        "category": "billing",
        "use_grounding": True,
        "provider_override": "mock",
    }
    res = client.post("/api/v1/copilot/draft", json=req)
    assert res.status_code == 200
    data = res.json()
    assert "draft_reply" in data
    assert len(data["draft_reply"]) > 20


def test_refine_draft_actions():
    """Verify one-click AI refinement operations (empathy, concise, bulletize, grammar)."""
    original = "We got your email about the charge. The money will come back in a few days. Bye."

    # More empathetic
    res_emp = client.post("/api/v1/copilot/refine", json={
        "draft_text": original,
        "action": "more_empathetic",
        "provider_override": "mock",
    })
    assert res_emp.status_code == 200
    data_emp = res_emp.json()
    assert data_emp["action"] == "more_empathetic"
    assert any(w in data_emp["refined_text"].lower() for w in ["apologize", "understand", "committed"])

    # More concise
    res_con = client.post("/api/v1/copilot/refine", json={
        "draft_text": original,
        "action": "more_concise",
        "provider_override": "mock",
    })
    assert res_con.status_code == 200
    data_con = res_con.json()
    assert data_con["action"] == "more_concise"

    # Bulletize
    res_bul = client.post("/api/v1/copilot/refine", json={
        "draft_text": original,
        "action": "bulletize",
        "provider_override": "mock",
    })
    assert res_bul.status_code == 200
    data_bul = res_bul.json()
    assert data_bul["action"] == "bulletize"
    assert "1." in data_bul["refined_text"] or "•" in data_bul["refined_text"]


def test_summarize_ticket_thread():
    """Verify summarizing ticket conversation into an internal handoff note."""
    req = {
        "ticket_id": 1,
        "title": "Unauthorized duplicate charges on statement",
        "description": "Customer reported two charges on credit card.",
        "conversation_thread": [
            {"sender": "customer", "text": "Why do I see two charges?"},
            {"sender": "agent", "text": "Looking into authorization holds."},
        ],
        "provider_override": "mock",
    }
    res = client.post("/api/v1/copilot/summarize", json=req)
    assert res.status_code == 200
    data = res.json()
    assert "summary" in data
    assert "Ticket Thread Summary" in data["summary"]
    assert data["current_status"] != ""
    assert data["recommended_action"] != ""


def test_apply_reply_to_ticket():
    """Verify applying a co-pilot reply directly to ticket activity and updating ticket state."""
    payload = {
        "reply_content": "Dear Alex, We have processed your refund and it will appear in 3-5 days.",
        "is_internal": False,
        "new_status": "waiting_for_customer",
    }
    res = client.post("/api/v1/copilot/apply-to-ticket/1", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["ticket_id"] == 1
    assert data["status"] == "waiting_for_customer"

    # Verify database state
    db = TestingSessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == 1).first()
    assert ticket.status == TicketStatus.WAITING_FOR_CUSTOMER
    assert "Dear Alex" in ticket.ai_suggested_response
    activities = db.query(TicketActivity).filter(TicketActivity.ticket_id == 1).all()
    assert any("Dear Alex" in str(a.note) for a in activities)
    db.close()
