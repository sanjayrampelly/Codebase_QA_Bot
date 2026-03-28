from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.audit import log_audit_event
from app.authorization import is_admin
from app.db import session_scope
from app.models import RepositoryAccess, RepositoryRecord, Role, User, utcnow
from utils.github_utils import normalize_repo_url

ACCESS_LEVEL_FLAGS = {
    "viewer": {"can_view": True, "can_ask": True, "can_index": False, "can_reindex": False},
    "editor": {"can_view": True, "can_ask": True, "can_index": True, "can_reindex": True},
    "admin": {"can_view": True, "can_ask": True, "can_index": True, "can_reindex": True},
}

ACTION_TO_FLAG = {
    "view": "can_view",
    "ask": "can_ask",
    "index": "can_index",
    "reindex": "can_reindex",
}


class RepositoryAccessError(Exception):
    pass


@dataclass
class RepositorySummary:
    repo_url: str
    namespace: str
    chunk_count: int
    access_level: str
    can_view: bool
    can_ask: bool
    can_index: bool
    can_reindex: bool


def _upsert_repository_access(session, repository_id: int, user_id: int, access_level: str) -> RepositoryAccess:
    access_level = access_level.lower()
    if access_level not in ACCESS_LEVEL_FLAGS:
        raise ValueError(f"Unsupported access level: {access_level}")

    access_record = session.scalar(
        select(RepositoryAccess).where(
            RepositoryAccess.repository_id == repository_id,
            RepositoryAccess.user_id == user_id,
        )
    )
    if access_record is None:
        access_record = RepositoryAccess(repository_id=repository_id, user_id=user_id)
        session.add(access_record)

    access_record.access_level = access_level
    for key, value in ACCESS_LEVEL_FLAGS[access_level].items():
        setattr(access_record, key, value)
    session.flush()
    return access_record


def sync_repository_record(
    *,
    repo_url: str,
    namespace: str,
    chunk_count: int,
    indexed_by_user_id: int,
    action: str,
) -> RepositoryRecord:
    normalized_url = normalize_repo_url(repo_url)
    with session_scope() as session:
        repository = session.scalar(
            select(RepositoryRecord).where(RepositoryRecord.repo_url == normalized_url)
        )
        if repository is None:
            repository = RepositoryRecord(
                repo_url=normalized_url,
                namespace=namespace,
                display_name=normalized_url.rstrip("/").split("/")[-1],
            )
            session.add(repository)
            session.flush()

        repository.namespace = namespace
        repository.chunk_count = chunk_count
        repository.indexed_by_user_id = indexed_by_user_id
        repository.last_indexed_at = utcnow()
        repository.is_active = True
        session.flush()

        indexing_user = session.get(User, indexed_by_user_id)
        if indexing_user is None:
            raise RepositoryAccessError("Indexing user no longer exists.")

        owner_access_level = "admin" if "admin" in indexing_user.role_names() else "editor"
        _upsert_repository_access(session, repository.id, indexing_user.id, owner_access_level)

        admin_role = session.scalar(select(Role).where(Role.name == "admin"))
        if admin_role is not None:
            for admin_user in admin_role.users:
                _upsert_repository_access(session, repository.id, admin_user.id, "admin")

        log_audit_event(
            action,
            user_id=indexed_by_user_id,
            repo_url=normalized_url,
            namespace=namespace,
            details=f"chunk_count={chunk_count}",
            session=session,
        )
        return repository


def _user_record(session, user_id: int) -> User | None:
    return session.get(
        User,
        user_id,
        options=[selectinload(User.roles).selectinload(Role.permissions)],
    )


def list_repositories_for_user(user_id: int) -> list[RepositorySummary]:
    with session_scope() as session:
        user = _user_record(session, user_id)
        if user is None or not user.is_active:
            return []

        repositories: list[RepositorySummary] = []
        if "admin" in user.role_names():
            repo_records = session.scalars(
                select(RepositoryRecord).where(RepositoryRecord.is_active.is_(True)).order_by(RepositoryRecord.repo_url)
            ).all()
            for repo in repo_records:
                repositories.append(
                    RepositorySummary(
                        repo_url=repo.repo_url,
                        namespace=repo.namespace,
                        chunk_count=repo.chunk_count or 0,
                        access_level="admin",
                        can_view=True,
                        can_ask=True,
                        can_index=True,
                        can_reindex=True,
                    )
                )
            return repositories

        access_records = session.scalars(
            select(RepositoryAccess)
            .options(selectinload(RepositoryAccess.repository))
            .where(RepositoryAccess.user_id == user_id, RepositoryAccess.can_view.is_(True))
            .order_by(RepositoryAccess.repository_id)
        ).all()
        for access in access_records:
            repo = access.repository
            if repo is None or not repo.is_active:
                continue
            repositories.append(
                RepositorySummary(
                    repo_url=repo.repo_url,
                    namespace=repo.namespace,
                    chunk_count=repo.chunk_count or 0,
                    access_level=access.access_level,
                    can_view=access.can_view,
                    can_ask=access.can_ask,
                    can_index=access.can_index,
                    can_reindex=access.can_reindex,
                )
            )
        return repositories


def get_repository_by_url(repo_url: str) -> RepositoryRecord | None:
    normalized_url = normalize_repo_url(repo_url)
    with session_scope() as session:
        return session.scalar(select(RepositoryRecord).where(RepositoryRecord.repo_url == normalized_url))


def ensure_repository_access(*, user_id: int, repo_url: str, action: str) -> RepositorySummary:
    normalized_url = normalize_repo_url(repo_url)
    with session_scope() as session:
        user = _user_record(session, user_id)
        if user is None or not user.is_active:
            raise RepositoryAccessError("The user account is unavailable or inactive.")

        repository = session.scalar(
            select(RepositoryRecord).where(RepositoryRecord.repo_url == normalized_url, RepositoryRecord.is_active.is_(True))
        )
        if repository is None:
            raise RepositoryAccessError("Repository is not indexed yet.")

        if "admin" in user.role_names():
            return RepositorySummary(
                repo_url=repository.repo_url,
                namespace=repository.namespace,
                chunk_count=repository.chunk_count or 0,
                access_level="admin",
                can_view=True,
                can_ask=True,
                can_index=True,
                can_reindex=True,
            )

        access_record = session.scalar(
            select(RepositoryAccess).where(
                RepositoryAccess.repository_id == repository.id,
                RepositoryAccess.user_id == user_id,
            )
        )
        if access_record is None:
            raise RepositoryAccessError("You do not have access to this repository.")

        required_flag = ACTION_TO_FLAG[action]
        if not getattr(access_record, required_flag):
            raise RepositoryAccessError(f"You do not have permission to {action} this repository.")

        return RepositorySummary(
            repo_url=repository.repo_url,
            namespace=repository.namespace,
            chunk_count=repository.chunk_count or 0,
            access_level=access_record.access_level,
            can_view=access_record.can_view,
            can_ask=access_record.can_ask,
            can_index=access_record.can_index,
            can_reindex=access_record.can_reindex,
        )


def grant_repository_access(
    *,
    actor_user: dict,
    repository_url: str,
    target_user_id: int,
    access_level: str,
) -> None:
    if not is_admin(actor_user):
        raise RepositoryAccessError("Only admins can manage repository access.")

    normalized_url = normalize_repo_url(repository_url)
    with session_scope() as session:
        repository = session.scalar(select(RepositoryRecord).where(RepositoryRecord.repo_url == normalized_url))
        if repository is None:
            raise RepositoryAccessError("Repository does not exist in the access catalog.")

        target_user = session.get(User, target_user_id)
        if target_user is None:
            raise RepositoryAccessError("Target user does not exist.")

        _upsert_repository_access(session, repository.id, target_user_id, access_level)
        log_audit_event(
            "repo.access_granted",
            user_id=actor_user["user_id"],
            repo_url=normalized_url,
            namespace=repository.namespace,
            details=f"target_user_id={target_user_id}; access_level={access_level}",
            session=session,
        )


def list_repository_access(repository_url: str) -> list[dict]:
    normalized_url = normalize_repo_url(repository_url)
    with session_scope() as session:
        repository = session.scalar(select(RepositoryRecord).where(RepositoryRecord.repo_url == normalized_url))
        if repository is None:
            return []
        access_records = session.scalars(
            select(RepositoryAccess)
            .options(selectinload(RepositoryAccess.user))
            .where(RepositoryAccess.repository_id == repository.id)
            .order_by(RepositoryAccess.user_id)
        ).all()
        return [
            {
                "username": access.user.username if access.user else f"user-{access.user_id}",
                "user_id": access.user_id,
                "access_level": access.access_level,
                "can_view": access.can_view,
                "can_ask": access.can_ask,
                "can_index": access.can_index,
                "can_reindex": access.can_reindex,
            }
            for access in access_records
        ]
