from __future__ import annotations

from dataclasses import dataclass

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from app.models import Permission, Role, User

DEFAULT_PERMISSIONS: dict[str, str] = {
    "user:manage": "Create and manage users.",
    "role:manage": "Manage role assignments and permission mappings.",
    "repo:view": "View repositories in the UI.",
    "repo:index": "Index repositories.",
    "repo:reindex": "Re-index repositories.",
    "repo:delete": "Delete repository access or records.",
    "repo:ask": "Ask questions against a repository.",
    "audit:view": "Inspect audit events.",
    "token:refresh": "Refresh access tokens using refresh tokens.",
}

DEFAULT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": set(DEFAULT_PERMISSIONS.keys()),
    "editor": {"repo:view", "repo:index", "repo:reindex", "repo:ask", "token:refresh"},
    "viewer": {"repo:view", "repo:ask", "token:refresh"},
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    "admin": "Full administration across users, roles, and repositories.",
    "editor": "Can index and query allowed repositories.",
    "viewer": "Can view and ask questions on allowed repositories.",
}


@dataclass
class BootstrapStatus:
    user_count: int
    admin_exists: bool
    initial_admin_created: bool = False

    @property
    def has_users(self) -> bool:
        return self.user_count > 0


class UserServiceError(Exception):
    pass


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def get_user_by_identifier(session: Session, identifier: str) -> User | None:
    normalized_identifier = identifier.strip().lower()
    if not normalized_identifier:
        return None
    return session.scalar(
        select(User).where(
            (func.lower(User.username) == normalized_identifier)
            | (func.lower(User.email) == normalized_identifier)
        )
    )


def count_users(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User)) or 0


def seed_permissions_and_roles(session: Session) -> None:
    permissions_by_name: dict[str, Permission] = {}
    for name, description in DEFAULT_PERMISSIONS.items():
        permission = session.scalar(select(Permission).where(Permission.name == name))
        if permission is None:
            permission = Permission(name=name, description=description)
            session.add(permission)
            session.flush()
        permissions_by_name[name] = permission

    for role_name, permission_names in DEFAULT_ROLE_PERMISSIONS.items():
        role = session.scalar(select(Role).where(Role.name == role_name))
        if role is None:
            role = Role(name=role_name, description=ROLE_DESCRIPTIONS.get(role_name))
            session.add(role)
            session.flush()
        role.description = ROLE_DESCRIPTIONS.get(role_name)
        role.permissions = [permissions_by_name[name] for name in sorted(permission_names)]


def ensure_initial_admin(
    session: Session,
    *,
    username: str | None,
    password: str | None,
    email: str | None = None,
) -> bool:
    if not username or not password:
        return False

    existing_admin = session.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if existing_admin is not None:
        return False

    admin_role = session.scalar(select(Role).where(Role.name == "admin"))
    if admin_role is None:
        raise ValueError("Admin role must exist before creating the initial admin user.")

    user = User(
        username=username.strip(),
        email=email.strip().lower() if email else None,
        password_hash=hash_password(password),
        is_active=True,
    )
    user.roles.append(admin_role)
    session.add(user)
    return True


def build_bootstrap_status(
    session: Session,
    *,
    initial_admin_created: bool = False,
) -> BootstrapStatus:
    admin_role = session.scalar(select(Role).where(Role.name == "admin"))
    admin_exists = bool(admin_role and admin_role.users)
    return BootstrapStatus(
        user_count=count_users(session),
        admin_exists=admin_exists,
        initial_admin_created=initial_admin_created,
    )


def list_users(session: Session) -> list[User]:
    return session.scalars(select(User).options(selectinload(User.roles)).order_by(User.username)).all()


def list_roles(session: Session) -> list[Role]:
    return session.scalars(
        select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
    ).all()


def create_user_account(
    session: Session,
    *,
    username: str,
    email: str | None,
    password: str,
    role_names: list[str],
) -> User:
    normalized_username = username.strip()
    normalized_email = email.strip().lower() if email else None
    if not normalized_username or not password:
        raise UserServiceError("Username and password are required.")

    existing_user = session.scalar(
        select(User).where(func.lower(User.username) == normalized_username.lower())
    )
    if existing_user is not None:
        raise UserServiceError("A user with that username already exists.")

    if normalized_email:
        existing_email = session.scalar(
            select(User).where(func.lower(User.email) == normalized_email.lower())
        )
        if existing_email is not None:
            raise UserServiceError("A user with that email already exists.")

    roles = session.scalars(select(Role).where(Role.name.in_(role_names))).all() if role_names else []
    if role_names and len(roles) != len(set(role_names)):
        raise UserServiceError("One or more selected roles do not exist.")

    user = User(
        username=normalized_username,
        email=normalized_email,
        password_hash=hash_password(password),
        is_active=True,
    )
    user.roles = list(roles)
    session.add(user)
    session.flush()
    return user


def assign_roles_to_user(session: Session, *, user_id: int, role_names: list[str]) -> User:
    user = session.get(User, user_id, options=[selectinload(User.roles)])
    if user is None:
        raise UserServiceError("User does not exist.")

    roles = session.scalars(select(Role).where(Role.name.in_(role_names))).all() if role_names else []
    if role_names and len(roles) != len(set(role_names)):
        raise UserServiceError("One or more selected roles do not exist.")

    user.roles = list(roles)
    session.flush()
    return user
