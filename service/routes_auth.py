"""Auth routes for AI-Estimator SaaS.

All endpoints are mounted under the ``/auth`` prefix via an APIRouter.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError

from service.auth import (
    ApiKeyCreateRequest,
    ApiKeyListItem,
    ApiKeyResponse,
    ChangePasswordRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from service.db_pg import ApiKeyRecord, PgDatabase, UserRecord, get_db

router = APIRouter(prefix="/auth", tags=["auth"])

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

_API_KEY_PREFIX = "aie_"
_API_KEY_RAW_BYTES = 32  # 64 hex chars


def _generate_api_key() -> tuple[str, str]:
    """Return ``(raw_key, sha256_hex_hash)`` for a new API key.

    The raw key is shown to the user exactly once; the hash is stored.
    """
    raw = _API_KEY_PREFIX + secrets.token_hex(_API_KEY_RAW_BYTES)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


# ──────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    db: Annotated[PgDatabase, Depends(get_db)],
) -> TokenResponse:
    """Create a new account and return JWT tokens."""
    existing = await db.get_user_by_email(body.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    rec = UserRecord(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        company_name=body.company_name,
        role="estimator",
        plan="free",
    )
    user = await db.create_user(rec)

    access = create_access_token(user_id=user.id, role=user.role)
    refresh = create_refresh_token(user_id=user.id, role=user.role)
    return TokenResponse(access_token=access, refresh_token=refresh)


# ──────────────────────────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────────────────────────


@router.post("/login", response_model=TokenResponse)
async def login(
    body: UserLogin,
    db: Annotated[PgDatabase, Depends(get_db)],
) -> TokenResponse:
    """Authenticate with email + password and receive JWT tokens."""
    user = await db.get_user_by_email(body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access = create_access_token(user_id=user.id, role=user.role)
    refresh = create_refresh_token(user_id=user.id, role=user.role)
    return TokenResponse(access_token=access, refresh_token=refresh)


# ──────────────────────────────────────────────────────────────────────
# Token refresh
# ──────────────────────────────────────────────────────────────────────


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    db: Annotated[PgDatabase, Depends(get_db)],
) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh pair."""
    try:
        payload = decode_token(body.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type – expected refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        uid = uuid.UUID(user_id_str)
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

    access = create_access_token(user_id=user.id, role=user.role)
    refresh = create_refresh_token(user_id=user.id, role=user.role)
    return TokenResponse(access_token=access, refresh_token=refresh)


# ──────────────────────────────────────────────────────────────────────
# Profile
# ──────────────────────────────────────────────────────────────────────


@router.get("/me", response_model=UserResponse)
async def get_profile(
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> UserResponse:
    """Return the current user's profile."""
    return UserResponse.from_record(user)


@router.put("/me", response_model=UserResponse)
async def update_profile(
    body: UserUpdate,
    user: Annotated[UserRecord, Depends(get_current_user)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> UserResponse:
    """Update the current user's profile fields."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return UserResponse.from_record(user)

    updated = await db.update_user(user.id, **updates)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        )
    return UserResponse.from_record(updated)


# ──────────────────────────────────────────────────────────────────────
# Password change
# ──────────────────────────────────────────────────────────────────────


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> dict[str, str]:
    """Change the current user's password."""
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    new_hash = hash_password(body.new_password)
    await db.update_user(user.id, hashed_password=new_hash)
    return {"detail": "Password updated successfully"}


# ──────────────────────────────────────────────────────────────────────
# API Keys
# ──────────────────────────────────────────────────────────────────────


@router.post("/api-keys", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreateRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> ApiKeyResponse:
    """Generate a new API key for the current user.

    The raw key is returned **only at creation time**.
    """
    raw_key, key_hash = _generate_api_key()
    rec = ApiKeyRecord(
        user_id=user.id,
        key_hash=key_hash,
        name=body.name,
    )
    created = await db.create_api_key(rec)
    return ApiKeyResponse(
        id=created.id,
        name=created.name,
        key=raw_key,
        created_at=created.created_at,
    )


@router.get("/api-keys", response_model=list[ApiKeyListItem])
async def list_api_keys(
    user: Annotated[UserRecord, Depends(get_current_user)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> list[ApiKeyListItem]:
    """List the current user's API keys (without revealing the raw key)."""
    keys = await db.list_api_keys_for_user(user.id)
    return [
        ApiKeyListItem(
            id=k.id,
            name=k.name,
            last_used_at=k.last_used_at,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    user: Annotated[UserRecord, Depends(get_current_user)],
    db: Annotated[PgDatabase, Depends(get_db)],
) -> None:
    """Revoke (delete) an API key owned by the current user."""
    deleted = await db.delete_api_key(key_id, user_id=user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
