"""
Unit and Integration Tests for Phase 7: Machine Learning Ticket Categorization & Auto-Triage.
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
from app.models.audit import ModelUsage
from app.core.security import get_password_hash, create_access_token
from app.services.ticket_classifier import classifier_engine, SEED_TRAINING_DATA

# In-memory SQLite DB for tests
SQLALCHEMY_DATABASE_URL = "sqlite://"

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
        email="admin_ml@support.ai",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Admin ML",
        role=UserRole.ADMIN,
        is_active=True,
    )
    agent = User(
        email="agent_ml@support.ai",
        hashed_password=get_password_hash("AgentPass123!"),
        full_name="Agent ML",
        role=UserRole.AGENT,
        is_active=True,
    )
    customer = User(
        email="cust_ml@support.ai",
        hashed_password=get_password_hash("CustPass123!"),
        full_name="Customer ML",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add_all([admin, agent, customer])
    db.commit()

    yield

    Base.metadata.drop_all(bind=engine)


def get_token_for(email: str, role: str) -> str:
    return create_access_token(data={"sub": email, "role": role})


def test_classifier_engine_direct_prediction():
    """Verifies that the classifier predicts billing, tech issues, and account access accurately."""
    # 1. Billing issue
    res_billing = classifier_engine.predict(
        title="Unexpected charge on invoice INV-9901",
        description="I was billed twice on my Visa card for the subscription renewal. Please reverse the charge.",
        confidence_threshold=0.50,
    )
    assert res_billing.predicted_category == TicketCategory.BILLING
    assert res_billing.confidence_score > 0.40
    assert len(res_billing.category_probabilities) == 7

    # 2. Technical issue with urgent priority
    res_tech = classifier_engine.predict(
        title="Production 500 error and database connection timeout",
        description="The backend database pool is exhausted and API returning 504 gateway timeout. Entire site is down.",
        confidence_threshold=0.50,
    )
    assert res_tech.predicted_category == TicketCategory.TECHNICAL_ISSUE
    assert res_tech.predicted_priority == TicketPriority.URGENT
    assert res_tech.is_confident is True

    # 3. Account access
    res_account = classifier_engine.predict(
        title="Lost 2FA phone cannot login",
        description="I lost my phone with Google Authenticator and am locked out of my account. Reset password not working.",
        confidence_threshold=0.50,
    )
    assert res_account.predicted_category == TicketCategory.ACCOUNT_ACCESS

    # 4. Refund request
    res_refund = classifier_engine.predict(
        title="Refund request under 30-day money back guarantee",
        description="I cancelled my annual plan and want my money refunded back to my credit card account.",
        confidence_threshold=0.50,
    )
    assert res_refund.predicted_category == TicketCategory.REFUND_REQUEST


def test_classifier_explainability():
    """Verifies salient token feature extraction."""
    exp = classifier_engine.explain("Database connection timeout 500 server error", top_n=3)
    assert "tokens_analyzed" in exp.model_dump()
    assert "technical_issue" in exp.category_explanations
    tech_signals = [item.feature for item in exp.category_explanations["technical_issue"]]
    assert any("timeout" in f or "database" in f or "server" in f or "error" in f for f in tech_signals)


def test_api_predict_endpoint():
    """Verifies POST /api/v1/ml/predict."""
    token = get_token_for("cust_ml@support.ai", "customer")
    payload = {
        "title": "Where is my shipment ORD-9921?",
        "description": "Tracking number 9400111202556784920 has not updated in five days. Package delivery status requested.",
        "confidence_threshold": 0.50,
    }
    response = client.post(
        "/api/v1/ml/predict",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["predicted_category"] == "order_status"
    assert data["confidence_score"] > 0.40
    assert "inference_latency_ms" in data
    assert len(data["category_probabilities"]) == 7
    assert len(data["priority_probabilities"]) == 4


def test_api_metrics_and_samples_endpoints():
    """Verifies GET /api/v1/ml/metrics and GET /api/v1/ml/samples."""
    res_metrics = client.get("/api/v1/ml/metrics")
    assert res_metrics.status_code == 200
    metrics_data = res_metrics.json()
    assert metrics_data["status"] == "healthy"
    assert metrics_data["vocabulary_size"] > 10
    assert metrics_data["sample_count"] >= len(SEED_TRAINING_DATA)
    assert "billing" in metrics_data["categories"]

    res_samples = client.get("/api/v1/ml/samples")
    assert res_samples.status_code == 200
    samples_data = res_samples.json()
    assert len(samples_data) >= 5
    assert samples_data[0]["expected_category"] == "billing"


def test_api_triage_ticket_workflow():
    """Verifies end-to-end auto-triage on a database ticket."""
    db = TestingSessionLocal()
    customer = db.query(User).filter(User.email == "cust_ml@support.ai").first()

    # Create ticket with generic category
    ticket = Ticket(
        ticket_code="TIK-2026-7788",
        title="Double billed on credit card for annual plan",
        description="My card was charged twice on invoice INV-2024-889. Please refund the duplicate payment.",
        customer_id=customer.id,
        category=TicketCategory.GENERAL_INQUIRY,
        priority=TicketPriority.LOW,
        status=TicketStatus.OPEN,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    ticket_id = ticket.id
    db.close()

    agent_token = get_token_for("agent_ml@support.ai", "agent")
    triage_payload = {
        "auto_apply": True,
        "confidence_threshold": 0.40,
    }

    res = client.post(
        f"/api/v1/ml/triage-ticket/{ticket_id}",
        json=triage_payload,
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ticket_id"] == ticket_id
    assert data["applied_category"] == "billing"
    assert data["confidence"] > 0.40
    assert data["needs_human_review"] is False

    # Check updated database record
    db = TestingSessionLocal()
    updated_ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    assert updated_ticket.category == TicketCategory.BILLING
    assert updated_ticket.category_confidence is not None
    assert updated_ticket.category_confidence > 0.40

    activities = db.query(TicketActivity).filter(TicketActivity.ticket_id == ticket_id).all()
    assert any(a.activity_type == "ml_triage" for a in activities)
    db.close()


def test_api_retrain_endpoint():
    """Verifies POST /api/v1/ml/retrain with admin authorization."""
    admin_token = get_token_for("admin_ml@support.ai", "admin")
    res = client.post(
        "/api/v1/ml/retrain",
        json={"include_db_tickets": True},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["samples_trained"] >= len(SEED_TRAINING_DATA)
    assert data["vocabulary_size"] > 0
    assert data["accuracy"] > 0.80
