import re
from typing import List

from pydantic import BaseModel, EmailStr, field_validator

_PASSWORD_MIN_LENGTH = 8


def _validate_password_strength(v: str) -> str:
    if len(v) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters long")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("Password must contain at least one letter and one number")
    return v


class UserCreate(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def password_must_be_strong(cls, v: str) -> str:
        return _validate_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_must_be_strong(cls, v: str) -> str:
        return _validate_password_strength(v)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_must_be_strong(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserOut(BaseModel):
    id: str
    email: str
    role: str


class MeResponse(UserOut):
    projects: List[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: MeResponse
