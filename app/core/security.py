import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import config
from app.core.logger import get_logger
from app.utils.mongo import (
    ROLE_ADMIN,
    get_project,
    get_user_by_id,
    has_permission,
)

logger = get_logger(__name__)

_SECRET_KEY = config.JWT_SECRET_KEY
if not _SECRET_KEY:
    _SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning(
        "JWT_SECRET_KEY not set - using an ephemeral key for this process. "
        "All existing sessions will be invalidated on restart. Set JWT_SECRET_KEY "
        "in your environment for any deployment that needs stable sessions."
    )

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        logger.warning("Malformed password hash encountered during verification")
        return False


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def _create_token(user_id: str, token_type: str, token_version: int, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": token_type,
        "ver": token_version,
        "jti": secrets.token_hex(8),
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def create_access_token(user_id: str, token_version: int = 0) -> str:
    return _create_token(user_id, "access", token_version, timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(user_id: str, token_version: int = 0) -> str:
    return _create_token(user_id, "refresh", token_version, timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    return payload


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    '''Strips sensitive fields before a user document ever reaches an API response.'''
    return {"id": user["_id"], "email": user["email"], "role": user["role"]}


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Dict[str, Any]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials, expected_type="access")
    user = get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")

    if payload.get("ver", 0) != user.get("token_version", 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked, please log in again")

    return user


def require_admin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    if current_user.get("role") != ROLE_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user


def require_project_access(project_id: str):
    '''Dependency factory: admins always pass; regular users need an explicit,
    active grant for an existing, enabled project. This is the sole authorization
    boundary for project endpoints - it must never be bypassed based on frontend state.'''

    def _dependency(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        if current_user.get("role") == ROLE_ADMIN:
            return current_user

        project = get_project(project_id)
        if project is None or not project.get("enabled", False):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        if not has_permission(current_user["_id"], project_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have access to '{project.get('name', project_id)}'",
            )

        return current_user

    return _dependency
