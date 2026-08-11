from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pymongo.errors import DuplicateKeyError

from app.core import config
from app.core.logger import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.schemas.auth_schema import LoginRequest, MeResponse, TokenResponse, UserCreate
from app.utils.mongo import (
    ROLE_USER,
    bump_token_version,
    create_user,
    get_login_lockout,
    get_user_by_email,
    get_user_by_id,
    is_refresh_jti_used,
    list_permitted_project_ids,
    mark_refresh_jti_used,
    record_login_failure,
    reset_login_attempts,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=config.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/api/v1/auth",
        max_age=config.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def _issue_tokens(response: Response, user: dict) -> TokenResponse:
    token_version = user.get("token_version", 0)
    access_token = create_access_token(user["_id"], token_version)
    refresh_token = create_refresh_token(user["_id"], token_version)
    _set_refresh_cookie(response, refresh_token)
    projects = list_permitted_project_ids(user["_id"])
    return TokenResponse(
        access_token=access_token,
        user=MeResponse(id=user["_id"], email=user["email"], role=user["role"], projects=projects),
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, response: Response):
    if get_user_by_email(payload.email) is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered")

    try:
        user = create_user(payload.email, hash_password(payload.password), role=ROLE_USER)
    except DuplicateKeyError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered")

    logger.info("New user signed up: %s", user["email"])
    return _issue_tokens(response, user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, response: Response):
    lockout = get_login_lockout(payload.email)
    if lockout is not None:
        retry_minutes = max(1, int((lockout - datetime.now(lockout.tzinfo)).total_seconds() // 60) + 1)
        logger.warning("Login attempt for locked-out account %s", payload.email)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in about {retry_minutes} minute(s).",
        )

    user = get_user_by_email(payload.email)
    if user is None or not verify_password(payload.password, user["password_hash"]):
        attempt = record_login_failure(payload.email)
        logger.warning("Failed login attempt for %s (count=%s)", payload.email, attempt["count"])
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    reset_login_attempts(payload.email)
    logger.info("User logged in: %s", user["email"])
    return _issue_tokens(response, user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response):
    refresh_token = request.cookies.get(config.REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token provided")

    payload = decode_token(refresh_token, expected_type="refresh")
    user = get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")

    if payload.get("ver", 0) != user.get("token_version", 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked, please log in again")

    if is_refresh_jti_used(payload["jti"]):
        # This exact refresh token was already redeemed once - someone (possibly an
        # attacker with a stolen token) is replaying it. Revoke every outstanding
        # session for this user rather than just rejecting this one request.
        bump_token_version(user["_id"])
        logger.warning("Refresh token reuse detected for user %s - all sessions revoked", user["email"])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected. All sessions have been revoked - please log in again.",
        )

    mark_refresh_jti_used(payload["jti"])
    return _issue_tokens(response, user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=config.REFRESH_COOKIE_NAME, path="/api/v1/auth")
    return {"message": "Logged out"}


@router.get("/me", response_model=MeResponse)
def me(current_user: dict = Depends(get_current_user)):
    projects = list_permitted_project_ids(current_user["_id"])
    return MeResponse(id=current_user["_id"], email=current_user["email"], role=current_user["role"], projects=projects)
