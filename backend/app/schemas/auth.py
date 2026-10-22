"""Auth schemas. Extra fields are rejected so clients cannot smuggle provider/model keys."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class PasswordResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=512)
    new_password: str = Field(min_length=10, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime


class AuthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: UserRead


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


class PasswordResetRequested(MessageResponse):
    # Development only: no mail provider is configured, so the token is returned here.
    debug_token: str | None = None
