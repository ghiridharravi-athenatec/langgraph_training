from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pymongo.errors import DuplicateKeyError

from app.core import config
from app.core.email import send_password_reset_email
from app.core.logger import get_logger
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.schemas.auth_schema import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserCreate,
)
from app.utils.mongo import (
    ROLE_USER,
    bump_token_version,
    check_password_reset_rate_limit,
    create_user,
    get_login_lockout,
    get_user_by_email,
    get_user_by_id,
    is_password_reset_jti_used,
    is_refresh_jti_used,
    list_permitted_project_ids,
    mark_password_reset_jti_used,
    mark_refresh_jti_used,
    record_login_failure,
    reset_login_attempts,
    set_user_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger(__name__)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=config.REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        samesite=config.COOKIE_SAMESITE,
        secure=config.COOKIE_SECURE,
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


_FORGOT_PASSWORD_RESPONSE = {"message": "If that email is registered, a password reset link has been sent."}


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest):
    '''Always returns the same generic message - whether the email is unregistered,
    rate-limited, or the send itself failed - so a caller can never distinguish
    "no such account" from "account exists" (user enumeration).'''
    if not check_password_reset_rate_limit(payload.email):
        logger.warning("Password reset rate limit hit for %s", payload.email)
        return _FORGOT_PASSWORD_RESPONSE

    user = get_user_by_email(payload.email)
    if user is None:
        logger.info("Password reset requested for unregistered email %s", payload.email)
        return _FORGOT_PASSWORD_RESPONSE

    token = create_password_reset_token(user["_id"])
    reset_link = f"{config.FRONTEND_ORIGIN}/reset-password?token={token}"
    send_password_reset_email(user["email"], reset_link)
    logger.info("Password reset link issued for %s", user["email"])
    return _FORGOT_PASSWORD_RESPONSE


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest):
    token_payload = decode_token(payload.token, expected_type="password_reset")
    if is_password_reset_jti_used(token_payload["jti"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This reset link has already been used.")

    user = get_user_by_id(token_payload["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")

    set_user_password(user["_id"], hash_password(payload.new_password))
    mark_password_reset_jti_used(token_payload["jti"])
    bump_token_version(user["_id"])  # revoke every existing session, including any stolen one
    logger.info("Password reset completed for %s", user["email"])
    return {"message": "Password has been reset. Please log in with your new password."}


@router.post("/change-password", response_model=TokenResponse)
def change_password(payload: ChangePasswordRequest, response: Response, current_user: dict = Depends(get_current_user)):
    if not verify_password(payload.current_password, current_user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    set_user_password(current_user["_id"], hash_password(payload.new_password))
    bump_token_version(current_user["_id"])
    logger.info("Password changed for %s", current_user["email"])

    # bump_token_version above just invalidated the access token this request came in
    # on - issue a fresh pair immediately so the caller's own session keeps working;
    # every *other* outstanding session for this user is still revoked.
    refreshed_user = get_user_by_id(current_user["_id"])
    return _issue_tokens(response, refreshed_user)


@router.get("/me", response_model=MeResponse)
def me(current_user: dict = Depends(get_current_user)):
    projects = list_permitted_project_ids(current_user["_id"])
    return MeResponse(id=current_user["_id"], email=current_user["email"], role=current_user["role"], projects=projects)
