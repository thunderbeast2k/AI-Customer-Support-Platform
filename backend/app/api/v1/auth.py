"""
Authentication Endpoints: Registration, Login, Current User profile, and Role Verification.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.models.user import User, UserRole
from app.models.audit import AuditEvent
from app.schemas.user import UserCreate, UserLogin, UserResponse, Token
from app.api.deps import get_current_user, require_admin, require_agent_or_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication & User Management"])


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Register New User",
    description="Registers a new user account with hashed password and generates a signed JWT access token.",
)
def register_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
) -> Token:
    # Check if email is already registered
    existing_user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    # Hash password securely with bcrypt
    hashed_password = get_password_hash(payload.password)

    # Default to customer if not explicitly requested
    role = payload.role if payload.role else UserRole.CUSTOMER

    new_user = User(
        email=payload.email.lower().strip(),
        hashed_password=hashed_password,
        full_name=payload.full_name.strip(),
        role=role,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Create audit event
    audit = AuditEvent(
        user_id=new_user.id,
        event_type="user.register",
        target_type="user",
        target_id=str(new_user.id),
        details={"email": new_user.email, "role": new_user.role.value},
    )
    db.add(audit)
    db.commit()

    # Generate JWT
    access_token = create_access_token(subject=str(new_user.id), role=new_user.role.value)

    logger.info("User registered successfully: id=%d email=%s role=%s", new_user.id, new_user.email, new_user.role)

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(new_user),
    )


@router.post(
    "/login",
    response_model=Token,
    summary="User Login & Token Generation",
    description="Authenticates credentials and returns a signed JWT access token.",
)
def login_user(
    credentials: UserLogin,
    db: Session = Depends(get_db),
) -> Token:
    user = db.query(User).filter(User.email == credentials.email.lower().strip()).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been suspended or deactivated",
        )

    # Issue JWT token
    access_token = create_access_token(subject=str(user.id), role=user.role.value)

    # Record login audit event
    audit = AuditEvent(
        user_id=user.id,
        event_type="user.login",
        target_type="user",
        target_id=str(user.id),
        details={"email": user.email, "role": user.role.value},
    )
    db.add(audit)
    db.commit()

    logger.info("User logged in successfully: id=%d email=%s", user.id, user.email)

    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get Current User Profile",
    description="Returns the authenticated user's profile and active role.",
)
def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.get(
    "/admin-only",
    summary="RBAC Test: Admin Only Access",
    description="Protected route strictly requiring ADMIN role.",
)
def test_admin_access(
    admin_user: User = Depends(require_admin),
):
    return {
        "message": f"Welcome Admin {admin_user.full_name}!",
        "access_granted": True,
        "role": admin_user.role.value,
    }


@router.get(
    "/agent-only",
    summary="RBAC Test: Support Agent & Admin Access",
    description="Protected route requiring AGENT or ADMIN role.",
)
def test_agent_access(
    agent_user: User = Depends(require_agent_or_admin),
):
    return {
        "message": f"Welcome Staff Member {agent_user.full_name}!",
        "access_granted": True,
        "role": agent_user.role.value,
    }
