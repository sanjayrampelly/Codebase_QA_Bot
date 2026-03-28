from __future__ import annotations

import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.deps import get_current_principal, require_permission
from api.schemas import (
    AskQuestionRequest,
    AskQuestionResponse,
    AssignRolesRequest,
    AuditLogModel,
    AuditLogsResponse,
    AuthTokensResponse,
    CreateRoleRequest,
    CreateUserRequest,
    CurrentUserModel,
    CurrentUserResponse,
    GrantRepositoryAccessRequest,
    IndexRepositoryRequest,
    IndexRepositoryResponse,
    LoginRequest,
    LogoutRequest,
    RegisterRequest,
    RefreshRequest,
    RefreshResponse,
    RepositoriesResponse,
    RepositoryAccessModel,
    RepositoryAccessResponse,
    RepositoryModel,
    RoleModel,
    RolesResponse,
    UserModel,
    UsersResponse,
    UpdateUserRequest,
)
from app.audit import log_audit_event, query_audit_logs
from app.auth import (
    AuthenticatedPrincipal,
    InvalidCredentialsError,
    initialize_auth_system,
    login_user,
    logout_user,
    refresh_session,
)
from app.db import session_scope
from app.models import Permission, RepositoryRecord, Role, User
from app.repository_service import (
    RepositoryAccessError,
    ensure_repository_access,
    get_repository_by_url,
    grant_repository_access,
    list_repositories_for_user,
    list_repository_access,
    sync_repository_record,
)
from app.user_service import UserServiceError, assign_roles_to_user, create_user_account, list_roles, list_users
from utils.config import get_env, load_environment
from utils.github_utils import is_valid_github_url, normalize_repo_url
from utils.logger import get_logger

load_environment(PROJECT_ROOT)
logger = get_logger(__name__)

app = FastAPI(
    title="Codebase Q&A Bot API",
    version="0.1.0",
    summary="JWT-based authentication, repository access control, indexing, and Q&A API",
    description=(
        "FastAPI backend for the Codebase Q&A Bot. "
        "It exposes custom JWT auth, RBAC-aware administration, repository access management, "
        "indexing, and repository-scoped question answering."
    ),
)


def _env_flag(name: str, default: bool) -> bool:
    value = get_env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@app.on_event("startup")
def startup_event() -> None:
    initialize_auth_system()


@lru_cache(maxsize=1)
def get_embedder() -> Any:
    from app.embedder import CodeEmbedder

    return CodeEmbedder()


@lru_cache(maxsize=1)
def get_store() -> Any:
    from app.vectorstore import PineconeStore

    return PineconeStore(index_name=get_env("PINECONE_INDEX_NAME", "codebase-qna") or "codebase-qna")


def access_expiry_seconds() -> int:
    return int(get_env("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")) * 60


def serialize_current_user(principal: AuthenticatedPrincipal) -> CurrentUserModel:
    return CurrentUserModel(
        id=principal.user_id,
        username=principal.username,
        email=principal.email,
        roles=principal.roles,
        permissions=principal.permissions,
    )


def serialize_role(role: Role) -> RoleModel:
    return RoleModel(
        id=role.id,
        name=role.name,
        description=role.description,
        permissions=[
            {"name": permission.name, "description": permission.description}
            for permission in sorted(role.permissions, key=lambda item: item.name)
        ],
    )


def serialize_user(user: User) -> UserModel:
    return UserModel(
        id=user.id,
        username=user.username,
        email=user.email,
        isActive=user.is_active,
        roles=[serialize_role(role) for role in sorted(user.roles, key=lambda item: item.name)],
        createdAt=user.created_at,
        lastLoginAt=user.last_login_at,
    )


def serialize_repository(record: RepositoryRecord, summary: dict | None = None) -> RepositoryModel:
    summary = summary or {}
    return RepositoryModel(
        id=record.id,
        repoUrl=record.repo_url,
        namespace=record.namespace,
        displayName=record.display_name,
        chunkCount=record.chunk_count or 0,
        indexedByUserId=record.indexed_by_user_id,
        lastIndexedAt=record.last_indexed_at,
        isActive=record.is_active,
        accessLevel=summary.get("access_level"),
        canView=summary.get("can_view"),
        canAsk=summary.get("can_ask"),
        canIndex=summary.get("can_index"),
        canReindex=summary.get("can_reindex"),
    )


def load_repository_by_id(repository_id: int) -> RepositoryRecord:
    with session_scope() as session:
        repository = session.get(RepositoryRecord, repository_id)
        if repository is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found.")
        return repository


def perform_index(repo_url: str, *, principal: AuthenticatedPrincipal, force_reindex: bool) -> IndexRepositoryResponse:
    if not is_valid_github_url(repo_url):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid GitHub repository URL.")

    normalized_url = normalize_repo_url(repo_url)
    existing_repository = get_repository_by_url(normalized_url)

    if existing_repository and force_reindex:
        try:
            ensure_repository_access(user_id=principal.user_id, repo_url=normalized_url, action="reindex")
        except RepositoryAccessError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if existing_repository and not force_reindex:
        try:
            ensure_repository_access(user_id=principal.user_id, repo_url=normalized_url, action="view")
        except RepositoryAccessError:
            pass

    from app.ingestor import CodeIngestor

    ingestor = CodeIngestor()
    store = get_store()
    embedder = get_embedder()
    docs = ingestor.ingest(normalized_url)
    store.delete_namespace(normalized_url)
    store.upsert_documents(docs, embedder, namespace=normalized_url)
    repository = sync_repository_record(
        repo_url=normalized_url,
        namespace=normalized_url,
        chunk_count=len(docs),
        indexed_by_user_id=principal.user_id,
        action="repo.reindex" if force_reindex else "repo.index",
    )
    return IndexRepositoryResponse(
        repositoryId=repository.id,
        repoUrl=repository.repo_url,
        namespace=repository.namespace,
        chunkCount=repository.chunk_count or 0,
        status="completed",
        message="Repository indexed successfully.",
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/login", response_model=AuthTokensResponse, tags=["Auth"])
def auth_login(payload: LoginRequest) -> AuthTokensResponse:
    try:
        auth_session = login_user(payload.username_or_email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return AuthTokensResponse(
        accessToken=auth_session.access_token,
        refreshToken=auth_session.refresh_token,
        tokenType="Bearer",
        expiresIn=access_expiry_seconds(),
        user=serialize_current_user(auth_session.principal),
    )


@app.post("/auth/register", response_model=AuthTokensResponse, status_code=status.HTTP_201_CREATED, tags=["Auth"])
def auth_register(payload: RegisterRequest) -> AuthTokensResponse:
    if not _env_flag("AUTH_SELF_REGISTRATION_ENABLED", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-registration is disabled.",
        )

    default_role = get_env("AUTH_REGISTRATION_DEFAULT_ROLE", "viewer") or "viewer"
    try:
        with session_scope() as session:
            user = create_user_account(
                session,
                username=payload.username,
                email=payload.email,
                password=payload.password,
                role_names=[default_role],
            )
            log_audit_event(
                "auth.register_success",
                user_id=user.id,
                details=f"default_role={default_role}",
                session=session,
            )
    except UserServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    auth_session = login_user(payload.username, payload.password)
    return AuthTokensResponse(
        accessToken=auth_session.access_token,
        refreshToken=auth_session.refresh_token,
        tokenType="Bearer",
        expiresIn=access_expiry_seconds(),
        user=serialize_current_user(auth_session.principal),
    )


@app.post("/auth/refresh", response_model=RefreshResponse, tags=["Auth"])
def auth_refresh(payload: RefreshRequest) -> RefreshResponse:
    try:
        auth_session = refresh_session(payload.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return RefreshResponse(
        accessToken=auth_session.access_token,
        refreshToken=auth_session.refresh_token,
        tokenType="Bearer",
        expiresIn=access_expiry_seconds(),
    )


@app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, tags=["Auth"])
def auth_logout(
    payload: LogoutRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> Response:
    logout_user(payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/auth/me", response_model=CurrentUserResponse, tags=["Auth"])
def auth_me(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> CurrentUserResponse:
    return CurrentUserResponse(user=serialize_current_user(principal))


@app.get("/users", response_model=UsersResponse, tags=["Users"])
def get_users(
    principal: AuthenticatedPrincipal = Depends(require_permission("user:manage")),
) -> UsersResponse:
    with session_scope() as session:
        users = list_users(session)
    return UsersResponse(items=[serialize_user(user) for user in users])


@app.post("/users", response_model=UserModel, status_code=status.HTTP_201_CREATED, tags=["Users"])
def create_user(
    payload: CreateUserRequest,
    principal: AuthenticatedPrincipal = Depends(require_permission("user:manage")),
) -> UserModel:
    try:
        with session_scope() as session:
            user = create_user_account(
                session,
                username=payload.username,
                email=payload.email,
                password=payload.password,
                role_names=payload.role_names,
            )
            user = session.get(User, user.id, options=[selectinload(User.roles).selectinload(Role.permissions)])
            return serialize_user(user)
    except UserServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/users/{user_id}", response_model=UserModel, tags=["Users"])
def get_user(
    user_id: int,
    principal: AuthenticatedPrincipal = Depends(require_permission("user:manage")),
) -> UserModel:
    with session_scope() as session:
        user = session.get(User, user_id, options=[selectinload(User.roles).selectinload(Role.permissions)])
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        return serialize_user(user)


@app.patch("/users/{user_id}", response_model=UserModel, tags=["Users"])
def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    principal: AuthenticatedPrincipal = Depends(require_permission("user:manage")),
) -> UserModel:
    with session_scope() as session:
        user = session.get(User, user_id, options=[selectinload(User.roles).selectinload(Role.permissions)])
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        if payload.username is not None:
            user.username = payload.username.strip()
        if payload.email is not None:
            user.email = payload.email.strip().lower()
        if payload.is_active is not None:
            user.is_active = payload.is_active
        session.flush()
        return serialize_user(user)


@app.put("/users/{user_id}/roles", response_model=UserModel, tags=["Users"])
def replace_user_roles(
    user_id: int,
    payload: AssignRolesRequest,
    principal: AuthenticatedPrincipal = Depends(require_permission("role:manage")),
) -> UserModel:
    try:
        with session_scope() as session:
            user = assign_roles_to_user(session, user_id=user_id, role_names=payload.role_names)
            user = session.get(User, user.id, options=[selectinload(User.roles).selectinload(Role.permissions)])
            return serialize_user(user)
    except UserServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/roles", response_model=RolesResponse, tags=["Roles"])
def get_roles(
    principal: AuthenticatedPrincipal = Depends(require_permission("role:manage")),
) -> RolesResponse:
    with session_scope() as session:
        roles = list_roles(session)
    return RolesResponse(items=[serialize_role(role) for role in roles])


@app.post("/roles", response_model=RoleModel, status_code=status.HTTP_201_CREATED, tags=["Roles"])
def create_role(
    payload: CreateRoleRequest,
    principal: AuthenticatedPrincipal = Depends(require_permission("role:manage")),
) -> RoleModel:
    with session_scope() as session:
        existing_role = session.scalar(select(Role).where(Role.name == payload.name.strip()))
        if existing_role is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role already exists.")

        permissions = []
        if payload.permission_names:
            permissions = session.scalars(
                select(Permission).where(Permission.name.in_(payload.permission_names))
            ).all()
            if len(permissions) != len(set(payload.permission_names)):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more permissions were not found.")

        role = Role(
            name=payload.name.strip(),
            description=payload.description,
            permissions=list(permissions),
        )
        session.add(role)
        session.flush()
        role = session.get(Role, role.id, options=[selectinload(Role.permissions)])
        return serialize_role(role)


@app.get("/repositories", response_model=RepositoriesResponse, tags=["Repositories"])
def get_repositories(
    principal: AuthenticatedPrincipal = Depends(require_permission("repo:view")),
) -> RepositoriesResponse:
    summaries = list_repositories_for_user(principal.user_id)
    repository_ids = []
    by_url = {}
    for summary in summaries:
        record = get_repository_by_url(summary.repo_url)
        if record is not None:
            repository_ids.append(record.id)
            by_url[summary.repo_url] = summary
    with session_scope() as session:
        repositories = session.scalars(
            select(RepositoryRecord).where(RepositoryRecord.id.in_(repository_ids)).order_by(RepositoryRecord.repo_url)
        ).all() if repository_ids else []
    return RepositoriesResponse(
        items=[
            serialize_repository(repository, by_url.get(repository.repo_url).__dict__ if by_url.get(repository.repo_url) else None)
            for repository in repositories
        ]
    )


@app.post("/repositories", response_model=IndexRepositoryResponse, status_code=status.HTTP_202_ACCEPTED, tags=["Repositories"])
def index_repository(
    payload: IndexRepositoryRequest,
    principal: AuthenticatedPrincipal = Depends(require_permission("repo:index")),
) -> IndexRepositoryResponse:
    try:
        return perform_index(payload.repo_url, principal=principal, force_reindex=payload.force_reindex)
    except RepositoryAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/repositories/{repository_id}", response_model=RepositoryModel, tags=["Repositories"])
def get_repository(
    repository_id: int,
    principal: AuthenticatedPrincipal = Depends(require_permission("repo:view")),
) -> RepositoryModel:
    repository = load_repository_by_id(repository_id)
    try:
        summary = ensure_repository_access(user_id=principal.user_id, repo_url=repository.repo_url, action="view")
    except RepositoryAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return serialize_repository(repository, summary.__dict__)


@app.post("/repositories/{repository_id}/reindex", response_model=IndexRepositoryResponse, status_code=status.HTTP_202_ACCEPTED, tags=["Repositories"])
def reindex_repository(
    repository_id: int,
    principal: AuthenticatedPrincipal = Depends(require_permission("repo:reindex")),
) -> IndexRepositoryResponse:
    repository = load_repository_by_id(repository_id)
    try:
        return perform_index(repository.repo_url, principal=principal, force_reindex=True)
    except RepositoryAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@app.get("/repositories/{repository_id}/access", response_model=RepositoryAccessResponse, tags=["Repository Access"])
def get_repository_access_list(
    repository_id: int,
    principal: AuthenticatedPrincipal = Depends(require_permission("repo:view")),
) -> RepositoryAccessResponse:
    repository = load_repository_by_id(repository_id)
    if "admin" not in principal.roles:
        try:
            ensure_repository_access(user_id=principal.user_id, repo_url=repository.repo_url, action="view")
        except RepositoryAccessError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    rows = list_repository_access(repository.repo_url)
    return RepositoryAccessResponse(
        items=[
            RepositoryAccessModel(
                repositoryId=repository_id,
                userId=row["user_id"],
                username=row["username"],
                accessLevel=row["access_level"],
                canView=row["can_view"],
                canAsk=row["can_ask"],
                canIndex=row["can_index"],
                canReindex=row["can_reindex"],
            )
            for row in rows
        ]
    )


@app.post("/repositories/{repository_id}/access", response_model=RepositoryAccessModel, tags=["Repository Access"])
def update_repository_access(
    repository_id: int,
    payload: GrantRepositoryAccessRequest,
    principal: AuthenticatedPrincipal = Depends(require_permission("repo:index")),
) -> RepositoryAccessModel:
    repository = load_repository_by_id(repository_id)
    try:
        grant_repository_access(
            actor_user=principal.to_session_dict(),
            repository_url=repository.repo_url,
            target_user_id=payload.user_id,
            access_level=payload.access_level,
        )
    except RepositoryAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    rows = list_repository_access(repository.repo_url)
    target_row = next((row for row in rows if row["user_id"] == payload.user_id), None)
    if target_row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Access record was not persisted.")

    return RepositoryAccessModel(
        repositoryId=repository_id,
        userId=target_row["user_id"],
        username=target_row["username"],
        accessLevel=target_row["access_level"],
        canView=target_row["can_view"],
        canAsk=target_row["can_ask"],
        canIndex=target_row["can_index"],
        canReindex=target_row["can_reindex"],
    )


@app.post("/repositories/{repository_id}/questions", response_model=AskQuestionResponse, tags=["Q&A"])
def ask_question(
    repository_id: int,
    payload: AskQuestionRequest,
    principal: AuthenticatedPrincipal = Depends(require_permission("repo:ask")),
) -> AskQuestionResponse:
    repository = load_repository_by_id(repository_id)
    try:
        summary = ensure_repository_access(user_id=principal.user_id, repo_url=repository.repo_url, action="ask")
    except RepositoryAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    store = get_store()
    embedder = get_embedder()
    retriever = store.get_retriever(embedder, summary.namespace, k=payload.top_k)
    from app.llm import get_llm
    from app.rag_chain import CodeQAChain

    llm = get_llm()
    chain = CodeQAChain()
    start = time.time()
    result = chain.ask(payload.question, retriever, llm)
    elapsed = int((time.time() - start) * 1000)

    from app.audit import log_audit_event

    log_audit_event(
        "repo.ask",
        user_id=principal.user_id,
        repo_url=summary.repo_url,
        namespace=summary.namespace,
        details=payload.question[:200],
    )

    return AskQuestionResponse(
        answer=result["answer"],
        sources=result["sources"],
        context=result.get("context") if payload.include_context else None,
        responseTimeMs=elapsed,
    )


@app.get("/audit-logs", response_model=AuditLogsResponse, tags=["Audit"])
def get_audit_logs(
    user_id: int | None = None,
    action: str | None = None,
    repository_id: int | None = None,
    principal: AuthenticatedPrincipal = Depends(require_permission("audit:view")),
) -> AuditLogsResponse:
    logs = query_audit_logs(user_id=user_id, action=action, repository_id=repository_id, limit=200)
    return AuditLogsResponse(
        items=[
            AuditLogModel(
                id=log.id,
                userId=log.user_id,
                action=log.action,
                repoUrl=log.repo_url,
                namespace=log.namespace,
                details=log.details,
                createdAt=log.created_at,
            )
            for log in logs
        ]
    )
