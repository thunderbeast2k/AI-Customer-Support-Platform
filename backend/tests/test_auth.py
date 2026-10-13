"""
Unit and Integration Tests for Phase 2: Authentication & Role-Based Access Control (RBAC).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.user import User, UserRole

# Use an in-memory SQLite database for isolated test execution
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Create tables in test database
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
    """Recreates tables cleanly before tests."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield


def test_user_registration_success():
    """Verify new user registration creates user and returns JWT token."""
    payload = {
        "email": "testuser@example.com",
        "password": "SecurePassword123!",
        "full_name": "Test User",
        "role": "customer",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "testuser@example.com"
    assert data["user"]["role"] == "customer"
    assert data["user"]["is_active"] is True


def test_registration_duplicate_email_fails():
    """Verify duplicate email registration is rejected with 400 Bad Request."""
    payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "full_name": "User One",
        "role": "customer",
    }
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]


def test_user_login_valid_credentials():
    """Verify user login returns access token with correct profile."""
    # Pre-register user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "loginuser@example.com",
            "password": "ValidPassword123!",
            "full_name": "Login User",
            "role": "customer",
        },
    )

    # Login
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "loginuser@example.com", "password": "ValidPassword123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "loginuser@example.com"


def test_user_login_invalid_password_rejected():
    """Verify login with incorrect password returns 401 Unauthorized."""
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "validuser@example.com",
            "password": "CorrectPassword123!",
            "full_name": "User",
            "role": "customer",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "validuser@example.com", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_get_me_protected_endpoint():
    """Verify /api/v1/auth/me returns profile when authenticated with Bearer token."""
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "me@example.com",
            "password": "Password123!",
            "full_name": "Me User",
            "role": "customer",
        },
    )
    token = reg.json()["access_token"]

    # Call /me without token -> 401
    unauth = client.get("/api/v1/auth/me")
    assert unauth.status_code == 401

    # Call /me with Bearer token -> 200
    auth_res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert auth_res.status_code == 200
    assert auth_res.json()["email"] == "me@example.com"
    assert auth_res.json()["full_name"] == "Me User"


def test_role_based_access_control():
    """Verify role-based access restrictions (Admin vs Agent vs Customer)."""
    # 1. Register Admin
    admin_reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "admin@test.com",
            "password": "Password123!",
            "full_name": "Admin Tester",
            "role": "admin",
        },
    )
    admin_token = admin_reg.json()["access_token"]

    # 2. Register Customer
    cust_reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "cust@test.com",
            "password": "Password123!",
            "full_name": "Customer Tester",
            "role": "customer",
        },
    )
    cust_token = cust_reg.json()["access_token"]

    # Admin accesses admin-only endpoint -> 200 OK
    admin_res = client.get(
        "/api/v1/auth/admin-only",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_res.status_code == 200
    assert admin_res.json()["access_granted"] is True

    # Customer tries to access admin-only endpoint -> 403 Forbidden
    cust_res = client.get(
        "/api/v1/auth/admin-only",
        headers={"Authorization": f"Bearer {cust_token}"},
    )
    assert cust_res.status_code == 403
    assert "Access denied" in cust_res.json()["detail"]
