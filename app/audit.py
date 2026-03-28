from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models import AuditLog


def log_audit_event(
    action: str,
    *,
    user_id: int | None = None,
    repo_url: str | None = None,
    namespace: str | None = None,
    details: str | None = None,
    session=None,
) -> None:
    log_entry = AuditLog(
        user_id=user_id,
        action=action,
        repo_url=repo_url,
        namespace=namespace,
        details=details,
    )
    if session is not None:
        session.add(log_entry)
        return

    with session_scope() as managed_session:
        managed_session.add(log_entry)


def fetch_audit_logs(limit: int = 100) -> list[AuditLog]:
    with session_scope() as session:
        return session.scalars(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        ).all()


def query_audit_logs(
    *,
    limit: int = 100,
    user_id: int | None = None,
    action: str | None = None,
    repository_id: int | None = None,
) -> list[AuditLog]:
    from app.models import RepositoryRecord

    with session_scope() as session:
        statement = select(AuditLog)
        if user_id is not None:
            statement = statement.where(AuditLog.user_id == user_id)
        if action:
            statement = statement.where(AuditLog.action == action)
        if repository_id is not None:
            repository = session.get(RepositoryRecord, repository_id)
            if repository is None:
                return []
            statement = statement.where(AuditLog.repo_url == repository.repo_url)
        statement = statement.order_by(AuditLog.created_at.desc()).limit(limit)
        return session.scalars(statement).all()
