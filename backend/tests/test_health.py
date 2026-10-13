"""
Unit and Integration Tests for Health and Readiness Endpoints.
Phase 1 Test Suite.
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_endpoint_returns_metadata():
    """Verify root endpoint returns project identity and navigation links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "project" in data
    assert data["project"] == "AI Customer Support Platform"
    assert data["phase"].startswith("Phase 1")
    assert "/docs" in data["documentation"]


def test_health_liveness_endpoint():
    """Verify /health returns 200 OK and status is healthy."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "timestamp" in data


def test_ready_endpoint_structure():
    """Verify /ready probe returns structured readiness and database info."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert "ready" in data
    assert "status" in data
    assert "database" in data
    assert "latency_ms" in data["database"]
    assert "vector_extension_available" in data["database"]


def test_v1_health_live_endpoint():
    """Verify /api/v1/health/live returns operational status."""
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_v1_health_ready_endpoint():
    """Verify /api/v1/health/ready returns service breakdown."""
    response = client.get("/api/v1/health/ready")
    # In dev/test without running Postgres, returns 200 with degraded state
    assert response.status_code in (200, 503)
    data = response.json()
    assert "ready" in data
    assert "services" in data
    assert "database" in data["services"]
    assert "ml_classifier" in data["services"]
    assert "embeddings" in data["services"]
    assert "llm_provider" in data["services"]


def test_v1_system_info_endpoint():
    """Verify /api/v1/health/system-info returns correct platform metadata."""
    response = client.get("/api/v1/health/system-info")
    assert response.status_code == 200
    data = response.json()
    assert data["project_name"] == "AI Customer Support Platform"
    assert data["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert data["embedding_dimension"] == 384
    assert data["llm_provider"] in ("mock", "gemini", "openai")
    assert isinstance(data["cors_allowed_origins"], list)


def test_request_id_and_latency_headers_present():
    """Verify middleware adds X-Request-ID and X-Process-Time-Ms headers."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert "X-Process-Time-Ms" in response.headers
    assert float(response.headers["X-Process-Time-Ms"]) >= 0.0
