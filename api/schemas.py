from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CurrentUserModel(BaseModel):
    id: int
    username: str
    email: str | None = None
    roles: list[str]
    permissions: list[str]


class CurrentUserResponse(BaseModel):
    user: CurrentUserModel


class LoginRequest(BaseModel):
    username_or_email: str = Field(alias="usernameOrEmail")
    password: str

    model_config = ConfigDict(populate_by_name=True)


class RegisterRequest(BaseModel):
    username: str
    email: str | None = None
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str = Field(alias="refreshToken")

    model_config = ConfigDict(populate_by_name=True)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(alias="refreshToken")

    model_config = ConfigDict(populate_by_name=True)


class AuthTokensResponse(BaseModel):
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    token_type: str = Field(default="Bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")
    user: CurrentUserModel

    model_config = ConfigDict(populate_by_name=True)


class RefreshResponse(BaseModel):
    access_token: str = Field(alias="accessToken")
    refresh_token: str | None = Field(default=None, alias="refreshToken")
    token_type: str = Field(default="Bearer", alias="tokenType")
    expires_in: int = Field(alias="expiresIn")

    model_config = ConfigDict(populate_by_name=True)


class PermissionModel(BaseModel):
    name: str
    description: str | None = None


class RoleModel(BaseModel):
    id: int
    name: str
    description: str | None = None
    permissions: list[PermissionModel] = []


class UserModel(BaseModel):
    id: int
    username: str
    email: str | None = None
    is_active: bool = Field(alias="isActive")
    roles: list[RoleModel]
    created_at: datetime = Field(alias="createdAt")
    last_login_at: datetime | None = Field(default=None, alias="lastLoginAt")

    model_config = ConfigDict(populate_by_name=True)


class UsersResponse(BaseModel):
    items: list[UserModel]


class RolesResponse(BaseModel):
    items: list[RoleModel]


class CreateUserRequest(BaseModel):
    username: str
    email: str | None = None
    password: str
    role_names: list[str] = Field(default_factory=list, alias="roleNames")

    model_config = ConfigDict(populate_by_name=True)


class UpdateUserRequest(BaseModel):
    username: str | None = None
    email: str | None = None
    is_active: bool | None = Field(default=None, alias="isActive")

    model_config = ConfigDict(populate_by_name=True)


class AssignRolesRequest(BaseModel):
    role_names: list[str] = Field(alias="roleNames")

    model_config = ConfigDict(populate_by_name=True)


class CreateRoleRequest(BaseModel):
    name: str
    description: str | None = None
    permission_names: list[str] = Field(default_factory=list, alias="permissionNames")

    model_config = ConfigDict(populate_by_name=True)


class RepositoryModel(BaseModel):
    id: int
    repo_url: str = Field(alias="repoUrl")
    namespace: str
    display_name: str | None = Field(default=None, alias="displayName")
    chunk_count: int | None = Field(default=None, alias="chunkCount")
    indexed_by_user_id: int | None = Field(default=None, alias="indexedByUserId")
    last_indexed_at: datetime | None = Field(default=None, alias="lastIndexedAt")
    is_active: bool = Field(alias="isActive")
    access_level: str | None = Field(default=None, alias="accessLevel")
    can_view: bool | None = Field(default=None, alias="canView")
    can_ask: bool | None = Field(default=None, alias="canAsk")
    can_index: bool | None = Field(default=None, alias="canIndex")
    can_reindex: bool | None = Field(default=None, alias="canReindex")

    model_config = ConfigDict(populate_by_name=True)


class RepositoriesResponse(BaseModel):
    items: list[RepositoryModel]


class IndexRepositoryRequest(BaseModel):
    repo_url: str = Field(alias="repoUrl")
    force_reindex: bool = Field(default=False, alias="forceReindex")

    model_config = ConfigDict(populate_by_name=True)


class IndexRepositoryResponse(BaseModel):
    repository_id: int = Field(alias="repositoryId")
    repo_url: str = Field(alias="repoUrl")
    namespace: str
    chunk_count: int | None = Field(default=None, alias="chunkCount")
    status: str
    message: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class RepositoryAccessModel(BaseModel):
    repository_id: int = Field(alias="repositoryId")
    user_id: int = Field(alias="userId")
    username: str | None = None
    access_level: str = Field(alias="accessLevel")
    can_view: bool = Field(alias="canView")
    can_ask: bool = Field(alias="canAsk")
    can_index: bool = Field(alias="canIndex")
    can_reindex: bool = Field(alias="canReindex")

    model_config = ConfigDict(populate_by_name=True)


class RepositoryAccessResponse(BaseModel):
    items: list[RepositoryAccessModel]


class GrantRepositoryAccessRequest(BaseModel):
    user_id: int = Field(alias="userId")
    access_level: str = Field(alias="accessLevel")

    model_config = ConfigDict(populate_by_name=True)


class AskQuestionRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, alias="topK")
    include_context: bool = Field(default=False, alias="includeContext")

    model_config = ConfigDict(populate_by_name=True)


class AskQuestionResponse(BaseModel):
    answer: str
    sources: list[str]
    context: str | None = None
    response_time_ms: int = Field(alias="responseTimeMs")

    model_config = ConfigDict(populate_by_name=True)


class AuditLogModel(BaseModel):
    id: int
    user_id: int | None = Field(default=None, alias="userId")
    action: str
    repo_url: str | None = Field(default=None, alias="repoUrl")
    namespace: str | None = None
    details: str | None = None
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True)


class AuditLogsResponse(BaseModel):
    items: list[AuditLogModel]


class ErrorResponse(BaseModel):
    message: str
    code: str | None = None
    details: dict | None = None
