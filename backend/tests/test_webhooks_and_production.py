"""
Unit and Integration Tests for Phase 10: Multi-Channel Webhook Gateways & Production Hardening.
Verifies Slack, Zendesk, Email, and Generic HMAC Webhooks,
signature verification security, delivery auditing, and production headers/rate limiting.
"""
import json
import time
import hmac
import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.config import settings
from app.core.database import Base, get_db
from app.services.webhook_service import WebhookService

# In-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# ----------------------------------------------------
# 1. Slack Webhook Tests
# ----------------------------------------------------

def test_slack_url_verification():
    """Verifies that Slack url_verification challenge handshake succeeds."""
    payload = {
        "type": "url_verification",
        "token": "slack_verification_token",
        "challenge": "3eZbrw1aBm2rZgRNFDxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P",
    }
    response = client.post("/api/v1/webhooks/slack", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "url_verification accepted" in data["message"]


def test_slack_app_mention_event():
    """Tests inbound Slack app_mention with automatic categorization."""
    payload = {
        "type": "event_callback",
        "team_id": "T09988",
        "event": {
            "type": "app_mention",
            "user": "U12345",
            "channel": "C999",
            "text": "Help! Our payment gateway keeps failing with billing errors on renewals.",
        },
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig_base = f"v0:{ts}:{raw_bytes.decode('utf-8')}".encode("utf-8")
    sig = "v0=" + hmac.new(
        settings.WEBHOOK_SLACK_SIGNING_SECRET.encode("utf-8"),
        sig_base,
        hashlib.sha256,
    ).hexdigest()

    response = client.post(
        "/api/v1/webhooks/slack",
        content=raw_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Signature": sig,
            "X-Slack-Request-Timestamp": ts,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["channel"] == "slack"
    assert data["signature_verified"] is True
    assert data["ticket_category"] == "Billing"
    assert data["ticket_id"].startswith("TICK-")


def test_slack_signature_failure_rejected():
    """Tests that bad Slack signature correctly yields a rejection."""
    payload = {"type": "event_callback", "event": {"text": "Unauthorized event"}}
    raw_bytes = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))

    response = client.post(
        "/api/v1/webhooks/slack",
        content=raw_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Slack-Signature": "v0=invalid_signature_mock",
            "X-Slack-Request-Timestamp": ts,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert data["signature_verified"] is False


# ----------------------------------------------------
# 2. Zendesk Webhook Tests
# ----------------------------------------------------

def test_zendesk_ticket_sync():
    """Verifies Zendesk ticket synchronization."""
    payload = {
        "ticket_id": "ZD-44120",
        "title": "SAML Single Sign-On IdP Metadata Expired",
        "description": "Users are locked out due to expired certificate.",
        "requester_email": "admin@enterprise.org",
        "priority": "urgent",
        "status": "new",
    }
    response = client.post(
        "/api/v1/webhooks/zendesk",
        json=payload,
        headers={"Authorization": f"Bearer {settings.WEBHOOK_ZENDESK_TOKEN}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["channel"] == "zendesk"
    assert data["signature_verified"] is True
    assert "[ZD:ZD-44120]" in data["ticket_title"]
    assert data["ticket_priority"] == "urgent"


def test_zendesk_unauthorized_token():
    """Verifies that invalid token is rejected."""
    payload = {
        "ticket_id": "ZD-999",
        "title": "Some subject",
        "description": "Some description",
        "requester_email": "user@test.com",
    }
    response = client.post(
        "/api/v1/webhooks/zendesk",
        json=payload,
        headers={"Authorization": "Bearer completely_wrong_token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert data["signature_verified"] is False


# ----------------------------------------------------
# 3. Email Inbound Parse Tests
# ----------------------------------------------------

def test_email_inbound_parse():
    """Tests inbound email parser with SPF & DKIM authentication."""
    payload = {
        "from_email": "sarah.connor@cyberdyne.com",
        "from_name": "Sarah Connor",
        "to_email": "support@ourplatform.com",
        "subject": "System crash when running batch sync",
        "body_plain": "Whenever we run the nightly batch sync, the worker encounters an OOM error.",
        "spf_check": "pass",
        "dkim_check": "pass",
    }
    response = client.post("/api/v1/webhooks/email", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["channel"] == "email"
    assert data["signature_verified"] is True
    assert data["ticket_title"] == "System crash when running batch sync"


# ----------------------------------------------------
# 4. Generic HMAC Webhook Tests
# ----------------------------------------------------

def test_generic_hmac_webhook():
    """Tests generic HMAC-SHA256 signature authenticated webhook."""
    payload = {
        "event_type": "stripe.charge.disputed",
        "source_system": "billing_service",
        "payload": {"charge_id": "ch_99482", "amount": 25000},
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    sig = WebhookService.compute_generic_signature(raw_bytes)

    response = client.post(
        "/api/v1/webhooks/generic",
        content=raw_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["channel"] == "generic"
    assert data["signature_verified"] is True
    assert "[BILLING_SERVICE]" in data["ticket_title"]


def test_generic_hmac_invalid_signature():
    """Tests generic webhook rejection on forged signature."""
    payload = {"event_type": "fake.event", "source_system": "attacker"}
    raw_bytes = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/api/v1/webhooks/generic",
        content=raw_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=forged_hash_123456",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert data["signature_verified"] is False


# ----------------------------------------------------
# 5. Deliveries & Audit Log Tests
# ----------------------------------------------------

def test_get_webhook_deliveries():
    """Verifies that deliveries list returns history and channel breakdowns."""
    response = client.get("/api/v1/webhooks/deliveries")
    assert response.status_code == 200
    data = response.json()
    assert data["total_deliveries"] >= 4
    assert "channel_counts" in data
    assert "deliveries" in data
    assert len(data["deliveries"]) > 0


# ----------------------------------------------------
# 6. Webhook Sandbox Simulator Tests
# ----------------------------------------------------

def test_webhook_simulator_slack():
    """Tests simulated Slack dispatch in developer sandbox."""
    sim_request = {"channel": "slack", "simulate_signature_failure": False}
    response = client.post("/api/v1/webhooks/simulate", json=sim_request)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["channel"] == "slack"
    assert data["signature_verified"] is True


def test_webhook_simulator_signature_failure():
    """Tests simulated signature failure."""
    sim_request = {"channel": "slack", "simulate_signature_failure": True}
    response = client.post("/api/v1/webhooks/simulate", json=sim_request)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"
    assert data["signature_verified"] is False


# ----------------------------------------------------
# 7. Production Hardening & Rate Limiter Tests
# ----------------------------------------------------

def test_production_hardening_report():
    """Verifies production security headers and hardening report."""
    response = client.get("/api/v1/webhooks/production-hardening")
    assert response.status_code == 200
    data = response.json()
    assert data["security_headers_count"] >= 5
    assert data["rate_limiting_active"] is True
    assert "rate_limit_info" in data


def test_security_headers_injected():
    """Verifies that production headers are actually present on responses."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "X-Request-ID" in response.headers
    assert "X-Process-Time-Ms" in response.headers
    assert "X-RateLimit-Limit" in response.headers


def test_rate_limiter_tester_endpoint():
    """Tests rate limiter tester endpoint consumption."""
    response = client.post("/api/v1/webhooks/rate-limit-test?cost=1.0")
    assert response.status_code == 200
    data = response.json()
    assert data["limit_per_minute"] == 120
    assert data["status"] == "active"
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
