from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    workspace_name: str = Field(
        default="Design Workspace", min_length=1, max_length=120
    )


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: UUID
    email: str
    role: str
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    slug: str
    owner_id: UUID

    model_config = ConfigDict(from_attributes=True)


class AuditLogOut(BaseModel):
    id: UUID
    action: str
    details: dict[str, object]
    workspace_id: UUID | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)
