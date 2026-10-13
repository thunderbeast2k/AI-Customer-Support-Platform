"""
Unit and Integration Tests for Phase 9: Analytics Dashboard & CSAT Metrics.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db

# Use in-memory SQLite for testing
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


def test_get_dashboard_overview():
    """Verify GET /api/v1/analytics/dashboard returns executive KPIs, CSAT, sentiment, agents, and categories."""
    response = client.get("/api/v1/analytics/dashboard?time_range=7d")
    assert response.status_code == 200
    data = response.json()
    assert data["time_range"] == "7d"
    
    kpis = data["kpis"]
    assert kpis["total_tickets"] > 0
    assert kpis["fcr_pct"] > 70.0
    assert kpis["mttr_hours"] > 0.0
    assert 1.0 <= kpis["avg_csat"] <= 5.0
    assert kpis["sla_compliance_pct"] > 80.0

    csat = data["csat"]
    assert csat["total_surveys"] >= 5
    assert len(csat["distribution"]) == 5

    sentiment = data["sentiment"]
    assert sentiment["sentiment_recovery_rate_pct"] > 80.0
    assert len(sentiment["timeline"]) > 0

    assert len(data["agent_performance"]) >= 4
    assert len(data["category_metrics"]) >= 5


def test_dashboard_time_ranges():
    """Verify different time range filters return valid tailored volumes."""
    for tr in ["24h", "7d", "30d", "90d"]:
        res = client.get(f"/api/v1/analytics/dashboard?time_range={tr}")
        assert res.status_code == 200
        data = res.json()
        assert data["time_range"] == tr
        assert data["kpis"]["total_tickets"] > 0


def test_get_csat_metrics():
    """Verify GET /api/v1/analytics/csat returns star distribution and feedback."""
    response = client.get("/api/v1/analytics/csat")
    assert response.status_code == 200
    data = response.json()
    assert "average_score" in data
    assert "distribution" in data
    assert "recent_feedbacks" in data
    assert len(data["distribution"]) == 5
    # Verify stars descend from 5 to 1
    stars = [d["stars"] for d in data["distribution"]]
    assert stars == [5, 4, 3, 2, 1]


def test_submit_csat_survey_positive():
    """Verify POST /api/v1/analytics/csat correctly records 5-star review."""
    payload = {
        "ticket_code": "TIK-TEST-9999",
        "rating": 5,
        "comment": "Awesome help! Quick response and resolved my problem right away.",
        "customer_name": "Test User Alpha",
    }
    response = client.post("/api/v1/analytics/csat", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["recorded_rating"] == 5
    assert data["detected_sentiment"] == "positive"
    assert data["updated_avg_csat"] > 0


def test_submit_csat_survey_negative():
    """Verify POST /api/v1/analytics/csat correctly handles 1-star negative review."""
    payload = {
        "ticket_code": "TIK-TEST-1111",
        "rating": 1,
        "comment": "Terrible service, system is completely broken and waited 3 hours.",
        "customer_name": "Frustrated Customer",
    }
    response = client.post("/api/v1/analytics/csat", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["recorded_rating"] == 1
    assert data["detected_sentiment"] == "negative"


def test_get_sentiment_velocity():
    """Verify GET /api/v1/analytics/sentiment-velocity returns initial vs resolution flows."""
    response = client.get("/api/v1/analytics/sentiment-velocity?time_range=7d")
    assert response.status_code == 200
    data = response.json()
    assert data["initial_frustrated_pct"] > 0
    assert data["resolved_delighted_pct"] > 0
    assert data["sentiment_recovery_rate_pct"] > 75.0
    assert len(data["timeline"]) >= 4


def test_get_agent_workload_heatmap():
    """Verify GET /api/v1/analytics/heatmap returns 2D schedule grid."""
    response = client.get("/api/v1/analytics/heatmap")
    assert response.status_code == 200
    cells = response.json()
    assert len(cells) == 5 * 11  # 5 days x 11 hours (8 to 18)
    first_cell = cells[0]
    assert "day" in first_cell
    assert "hour" in first_cell
    assert "ticket_count" in first_cell
    assert first_cell["intensity"] in ["low", "medium", "high", "peak"]


def test_get_agent_performance():
    """Verify GET /api/v1/analytics/agents returns agent leaderboard metrics."""
    response = client.get("/api/v1/analytics/agents")
    assert response.status_code == 200
    agents = response.json()
    assert len(agents) >= 4
    agent = agents[0]
    assert agent["name"] == "Sarah Jenkins"
    assert agent["csat_score"] > 4.5
    assert agent["mttr_hours"] > 0
    assert agent["fcr_pct"] > 70


def test_get_category_metrics():
    """Verify GET /api/v1/analytics/categories returns category breakdown."""
    response = client.get("/api/v1/analytics/categories?total_tickets=200")
    assert response.status_code == 200
    categories = response.json()
    assert len(categories) >= 5
    cat_names = [c["category"] for c in categories]
    assert "billing" in cat_names
    assert "technical_issue" in cat_names
