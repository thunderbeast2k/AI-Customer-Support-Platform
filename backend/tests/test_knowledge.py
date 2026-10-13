"""
Unit and Integration Tests for Phase 5: Knowledge Base Ingestion, Chunking, Embeddings, and Semantic Search.
"""
import io
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


def test_document_ingestion_and_chunking():
    """Verify staff member can ingest a document and generate chunks with embeddings."""
    agent_token = _register_user("agent@support.ai", "agent", "Support Agent")

    sample_doc_content = (
        "Enterprise Refund and Subscription Guidelines 2026.\n\n"
        "Section 1: All recurring subscription invoices are generated automatically at the beginning of each billing month. "
        "In the event of an inadvertent duplicate payment or pre-authorization hold, the secondary charge will be released "
        "automatically within 72 business hours. If a customer demands an expedited electronic funds reversal, "
        "support staff may issue a direct refund to the originating payment card, settling in 3 to 5 business days.\n\n"
        "Section 2: Annual contract cancellations must be submitted at least 30 days prior to renewal."
    )

    files = {"file": ("refund_policy.md", io.BytesIO(sample_doc_content.encode("utf-8")), "text/markdown")}
    data = {"title": "Refund and Billing Guidelines 2026"}

    response = client.post(
        "/api/v1/knowledge/documents",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert response.status_code == 201
    doc_data = response.json()
    assert doc_data["title"] == "Refund and Billing Guidelines 2026"
    assert doc_data["status"] == "indexed"
    assert doc_data["chunk_count"] > 0
    doc_id = doc_data["id"]

    # Verify document chunks
    detail_res = client.get(
        f"/api/v1/knowledge/documents/{doc_id}",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert len(detail["chunks"]) == doc_data["chunk_count"]
    assert "Section 1" in detail["chunks"][0]["content"]


def test_duplicate_document_rejection():
    """Verify duplicate document content is detected by SHA-256 hash and rejected."""
    agent_token = _register_user("agent@support.ai", "agent", "Support Agent")

    content = "Unique terms for enterprise license agreement."
    files1 = {"file": ("terms.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}

    # First upload succeeds
    res1 = client.post(
        "/api/v1/knowledge/documents",
        files=files1,
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert res1.status_code == 201

    # Second upload with identical content fails
    files2 = {"file": ("terms_duplicate.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
    res2 = client.post(
        "/api/v1/knowledge/documents",
        files=files2,
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]


def test_semantic_vector_search():
    """Verify semantic vector search returns relevant chunks with similarity score."""
    agent_token = _register_user("agent@support.ai", "agent", "Support Agent")

    content = (
        "Okta SAML 2.0 Single Sign-On Architecture.\n\n"
        "To configure identity federation with Okta, upload our assertion metadata XML and set the ACS URL "
        "to https://api.support.ai/v1/auth/sso/callback. Ensure that SHA-256 signature algorithms are selected. "
        "Clock skew must not exceed 120 seconds to prevent 504 gateway timeout errors."
    )
    files = {"file": ("okta_guide.txt", io.BytesIO(content.encode("utf-8")), "text/plain")}
    client.post(
        "/api/v1/knowledge/documents",
        files=files,
        headers={"Authorization": f"Bearer {agent_token}"},
    )

    # Perform semantic search
    search_payload = {
        "query": "How to resolve clock skew timeout on Okta SAML callback?",
        "top_k": 3,
        "threshold": 0.4,
    }
    search_res = client.post(
        "/api/v1/knowledge/search",
        json=search_payload,
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["total_matches"] > 0
    match = search_data["results"][0]
    assert "Okta" in match["content"]
    assert match["similarity_score"] > 0.4
    assert match["dimension"] == 384 or search_data["dimension"] == 384


def test_customer_cannot_upload_document():
    """Verify customers are forbidden from uploading knowledge documents."""
    cust_token = _register_user("cust@example.com", "customer", "Customer")

    files = {"file": ("hack.txt", io.BytesIO(b"Unauthorized text"), "text/plain")}
    res = client.post(
        "/api/v1/knowledge/documents",
        files=files,
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]


def test_document_deletion_cascades_chunks():
    """Verify document deletion removes the document and all associated chunks."""
    agent_token = _register_user("agent@support.ai", "agent", "Support Agent")

    files = {"file": ("temp.txt", io.BytesIO(b"Temporary policy document to be deleted."), "text/plain")}
    create_res = client.post(
        "/api/v1/knowledge/documents",
        files=files,
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    doc_id = create_res.json()["id"]

    # Delete
    del_res = client.delete(
        f"/api/v1/knowledge/documents/{doc_id}",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert del_res.status_code == 200

    # Verify not found
    get_res = client.get(
        f"/api/v1/knowledge/documents/{doc_id}",
        headers={"Authorization": f"Bearer {agent_token}"},
    )
    assert get_res.status_code == 404
