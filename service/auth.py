"""JWT authentication module for AI-Estimator SaaS.

Provides:
- Password hashing / verification via passlib[bcrypt]
- JWT access-token (15 min) and refresh-token (7 days) creation / validation
- FastAPI ``Depends`` dependencies: ``get_current_user``, ``require_role``
- Pydantic schemas: UserCreate, UserLogin, UserResponse, TokenResponse
- Email validation and password-strength checking
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator

from service.config import settings
from service.db_pg import PgDatabase, UserRecord, get_db

# ──────────────────────────────────────────────────────────────────────
# Password hashing
# ──────────────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return bcrypt hash of *plain* password."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` when *plain* matches *hashed*."""
    return pwd_context.verify(plain, hashed)


# ──────────────────────────────────────────────────────────────────────
# JWT helpers
# ──────────────────────────────────────────────────────────────────────

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7

_bearer_scheme = HTTPBearer()


def create_access_token(
    *,
    user_id: uuid.UUID,
    role: str = "estimator",
    extra: dict | None = None,
) -> str:
    """Create a short-lived access JWT (default 15 min)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(
    *,
    user_id: uuid.UUID,
    role: str = "estimator",
) -> str:
    """Create a long-lived refresh JWT (default 7 days)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT.  Raises ``JWTError`` on any problem."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )


# ──────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    """Registration payload."""

    email: EmailStr
    password: str
    full_name: str = Field(default="", max_length=200)
    company_name: str = Field(default="", max_length=200)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    """Login payload."""

    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """User data returned to clients (never includes hashed_password)."""

    id: uuid.UUID
    email: str
    full_name: str
    company_name: str
    role: str
    plan: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_record(cls, rec: UserRecord) -> "UserResponse":
        return cls(
            id=rec.id,
            email=rec.email,
            full_name=rec.full_name,
            company_name=rec.company_name,
            role=rec.role,
            plan=rec.plan,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
        )


class UserUpdate(BaseModel):
    """Profile update payload."""

    full_name: str | None = Field(default=None, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)


class ChangePasswordRequest(BaseModel):
    """Password change payload."""

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class TokenResponse(BaseModel):
    """JWT token pair returned after login / register / refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Refresh token payload."""

    refresh_token: str


class ApiKeyCreateRequest(BaseModel):
    """API key creation payload."""

    name: str = Field(default="default", max_length=100)


class ApiKeyResponse(BaseModel):
    """API key response (includes the raw key only at creation time)."""

    id: uuid.UUID
    name: str
    key: str  # raw key – only shown once at creation
    created_at: datetime


class ApiKeyListItem(BaseModel):
    """API key list item (no raw key)."""

    id: uuid.UUID
    name: str
    last_used_at: datetime | None
    created_at: datetime


# ──────────────────────────────────────────────────────────────────────
# FastAPI dependencies
# ──────────────────────────────────────────────────────────────────────


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> UserRecord:
    """Validate Bearer token and return the corresponding ``UserRecord``.

    Raises 401 on missing / invalid / expired tokens.
    """
    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type – expected access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await db.get_user_by_id(uid)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(*roles: str):
    """Return a ``Depends``-compatible dependency that enforces role-based access.

    Usage::

        @router.get("/admin-only", dependencies=[Depends(require_role("admin"))])
        async def admin_route(user: UserRecord = Depends(get_current_user)):
            ...
    """

    async def _check_role(user: Annotated[UserRecord, Depends(get_current_user)]) -> UserRecord:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' not permitted – requires one of {list(roles)}",
            )
        return user

    return _check_role
