"""
Unit and Integration Tests for Phase 6: RAG Pipeline, Hybrid Retrieval, and LLM Adapters.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.user import User, UserRole
from app.models.knowledge import KnowledgeDocument, DocumentChunk
from app.models.audit import ModelUsage
from app.core.security import get_password_hash, create_access_token
from app.services.llm.base import LLMMessage
from app.services.llm.mock_provider import MockLLMProvider
from app.services.rag_orchestrator import orchestrate_rag_response
from app.services.hybrid_retriever import HybridRetriever

# Setup in-memory SQLite database for testing
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

    # Create admin, agent, customer
    admin = User(
        email="admin_rag@support.ai",
        hashed_password=get_password_hash("AdminPass123!"),
        full_name="Admin RAG",
        role=UserRole.ADMIN,
        is_active=True,
    )
    customer = User(
        email="cust_rag@support.ai",
        hashed_password=get_password_hash("CustPass123!"),
        full_name="Customer RAG",
        role=UserRole.CUSTOMER,
        is_active=True,
    )
    db.add_all([admin, customer])
    db.commit()

    # Seed knowledge document and chunks
    doc = KnowledgeDocument(
        title="Enterprise Billing Policies",
        filename="billing_policies.md",
        file_type="md",
        file_size_bytes=2400,
        content_hash="test-hash-1234",
        status="indexed",
        chunk_count=2,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    chunk1 = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        content="Section 1: Invoices are dispatched on the 1st of each calendar month. Duplicate transactions are refunded in 3 to 5 business days.",
        token_count=26,
    )
    chunk2 = DocumentChunk(
        document_id=doc.id,
        chunk_index=1,
        content="Section 2: Okta SAML Single Sign-On ACS callback URL must be set to https://api.support.ai/v1/auth/sso/callback.",
        token_count=22,
    )
    db.add_all([chunk1, chunk2])
    db.commit()

    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def get_auth_token(email: str = "admin_rag@support.ai", role: str = "admin") -> str:
    return create_access_token(data={"sub": email, "role": role})


def test_mock_llm_provider_behavior():
    """Verifies that MockLLMProvider answers deterministically and redacts hallucinations."""
    mock_prov = MockLLMProvider()
    assert mock_prov.provider_id == "mock"

    # Test with context containing billing information
    messages = [
        LLMMessage(role="system", content="You are a support bot. CONTEXT PASSAGES:\nRefunds settle in 3-5 business days."),
        LLMMessage(role="user", content="How long do refunds take?"),
    ]
    resp = mock_prov.generate_response(messages)
    assert "refund" in resp.content.lower()
    assert resp.total_tokens > 0
    assert resp.latency_ms >= 0


def test_mock_llm_provider_insufficient_evidence():
    """Verifies fallback message when evidence is insufficient."""
    mock_prov = MockLLMProvider()
    messages = [
        LLMMessage(role="system", content="CONTEXT PASSAGES:\n[INSUFFICIENT_EVIDENCE]"),
        LLMMessage(role="user", content="What is the internal wifi password?"),
    ]
    resp = mock_prov.generate_response(messages)
    assert "could not find verified facts" in resp.content.lower()


def test_rag_orchestrator_pipeline():
    """Verifies end-to-end RAG orchestrator with database retrieval."""
    db = TestingSessionLocal()
    result = orchestrate_rag_response(
        db=db,
        query="Tell me about duplicate charge refunds and billing date",
        top_k=2,
        threshold=0.20,
    )
    db.close()

    assert "answer" in result
    assert "citations" in result
    assert "tokens" in result
    assert result["provider"] == "mock"
    assert result["has_sufficient_evidence"] is True
    assert len(result["citations"]) > 0


def test_api_rag_query_endpoint():
    """Tests POST /api/v1/rag/query with valid authentication."""
    token = get_auth_token("cust_rag@support.ai", "customer")
    resp = client.post(
        "/api/v1/rag/query",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "query": "How are duplicate billing charges resolved?",
            "top_k": 3,
            "threshold": 0.20,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "answer" in data
    assert "citations" in data
    assert "model_name" in data
    assert data["provider"] == "mock"
    assert data["tokens"]["total"] > 0


def test_api_rag_providers_endpoint():
    """Tests GET /api/v1/rag/providers endpoint."""
    token = get_auth_token()
    resp = client.get(
        "/api/v1/rag/providers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    providers = resp.json()
    assert len(providers) >= 2
    prov_ids = [p["provider"] for p in providers]
    assert "mock" in prov_ids
    assert "gemini" in prov_ids


def test_api_rag_usage_audit():
    """Tests GET /api/v1/rag/usage to view recorded token metrics."""
    # First invoke a query to populate usage
    token = get_auth_token("admin_rag@support.ai", "admin")
    client.post(
        "/api/v1/rag/query",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "What is the Okta ACS callback URL?"},
    )

    resp = client.get(
        "/api/v1/rag/usage",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) > 0
    record = records[0]
    assert "total_tokens" in record
    assert "estimated_cost_usd" in record
    assert record["operation"] == "rag_response"
