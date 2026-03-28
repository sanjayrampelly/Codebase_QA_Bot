from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.audit import log_audit_event
from app.db import init_db, session_scope
from app.jwt_service import JWTError, JWTExpiredError, JWTService
from app.models import LoginAttempt, RefreshToken, User, utcnow
from app.user_service import (
    BootstrapStatus,
    build_bootstrap_status,
    ensure_initial_admin,
    get_user_by_identifier,
    seed_permissions_and_roles,
    verify_password,
)
from utils.config import get_env, load_environment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_environment(PROJECT_ROOT)

MAX_LOGIN_ATTEMPTS = int(get_env("AUTH_MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINUTES = int(get_env("AUTH_LOCKOUT_MINUTES", "15"))


class AuthenticationError(Exception):
    pass


class InvalidCredentialsError(AuthenticationError):
    pass


class SessionExpiredError(AuthenticationError):
    pass


@dataclass
class AuthenticatedPrincipal:
    user_id: int
    username: str
    email: str | None
    roles: list[str]
    permissions: list[str]
    is_active: bool

    def to_session_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuthSession:
    principal: AuthenticatedPrincipal
    access_token: str
    refresh_token: str | None = None


def _get_jwt_service() -> JWTService:
    return JWTService()


def _user_to_principal(user: User) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user.id,
        username=user.username,
        email=user.email,
        roles=user.role_names(),
        permissions=user.permission_names(),
        is_active=user.is_active,
    )


def _record_login_attempt(session, identifier: str, *, was_successful: bool, details: str | None = None) -> None:
    session.add(
        LoginAttempt(
            identifier=identifier.strip().lower(),
            was_successful=was_successful,
            details=details,
        )
    )


def _ensure_login_not_rate_limited(session, identifier: str) -> None:
    normalized_identifier = identifier.strip().lower()
    window_start = utcnow() - timedelta(minutes=LOCKOUT_MINUTES)
    recent_failures = session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            func.lower(LoginAttempt.identifier) == normalized_identifier,
            LoginAttempt.was_successful.is_(False),
            LoginAttempt.attempted_at >= window_start,
        )
    ) or 0
    if recent_failures >= MAX_LOGIN_ATTEMPTS:
        raise AuthenticationError(
            f"Too many failed login attempts. Please try again in {LOCKOUT_MINUTES} minutes."
        )


def initialize_auth_system() -> BootstrapStatus:
    init_db()
    with session_scope() as session:
        seed_permissions_and_roles(session)
        initial_admin_created = ensure_initial_admin(
            session,
            username=get_env("INITIAL_ADMIN_USERNAME"),
            password=get_env("INITIAL_ADMIN_PASSWORD"),
            email=get_env("INITIAL_ADMIN_EMAIL"),
        )
        return build_bootstrap_status(session, initial_admin_created=initial_admin_created)


def get_bootstrap_status() -> BootstrapStatus:
    with session_scope() as session:
        return build_bootstrap_status(session)


def login_user(identifier: str, password: str) -> AuthSession:
    if not identifier.strip() or not password:
        raise InvalidCredentialsError("Username/email and password are required.")

    jwt_service = _get_jwt_service()
    with session_scope() as session:
        _ensure_login_not_rate_limited(session, identifier)
        user = get_user_by_identifier(session, identifier)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            _record_login_attempt(
                session,
                identifier,
                was_successful=False,
                details="invalid_credentials",
            )
            log_audit_event("auth.login_failed", details=f"identifier={identifier.strip()}", session=session)
            raise InvalidCredentialsError("Invalid username/email or password.")

        _record_login_attempt(session, identifier, was_successful=True, details=f"user_id={user.id}")
        user.last_login_at = utcnow()
        access_payload = jwt_service.create_access_token(user)
        refresh_payload = jwt_service.create_refresh_token(user)

        session.add(
            RefreshToken(
                user_id=user.id,
                jti=refresh_payload.claims["jti"],
                expires_at=refresh_payload.claims["exp"],
                is_revoked=False,
            )
        )
        log_audit_event("auth.login_success", user_id=user.id, session=session)

        return AuthSession(
            principal=_user_to_principal(user),
            access_token=access_payload.token,
            refresh_token=refresh_payload.token,
        )


def _get_refresh_record(session, jti: str) -> RefreshToken | None:
    return session.scalar(select(RefreshToken).where(RefreshToken.jti == jti))


def refresh_session(refresh_token: str) -> AuthSession:
    if not refresh_token:
        raise SessionExpiredError("Session expired. Please log in again.")

    jwt_service = _get_jwt_service()
    with session_scope() as session:
        try:
            claims = jwt_service.decode_token(refresh_token, expected_type="refresh")
        except JWTExpiredError as exc:
            raise SessionExpiredError("Your session expired. Please log in again.") from exc
        except JWTError as exc:
            raise SessionExpiredError("Your session is invalid. Please log in again.") from exc

        refresh_record = _get_refresh_record(session, claims["jti"])
        if refresh_record is None or refresh_record.is_revoked:
            raise SessionExpiredError("Your session is no longer valid. Please log in again.")
        if refresh_record.expires_at < utcnow():
            raise SessionExpiredError("Your session expired. Please log in again.")

        user = session.get(User, int(claims["sub"]))
        if user is None or not user.is_active:
            raise SessionExpiredError("The user account is unavailable or inactive.")

        refresh_record.is_revoked = True
        refresh_record.revoked_at = utcnow()

        access_payload = jwt_service.create_access_token(user)
        new_refresh_payload = jwt_service.create_refresh_token(user)
        session.add(
            RefreshToken(
                user_id=user.id,
                jti=new_refresh_payload.claims["jti"],
                expires_at=new_refresh_payload.claims["exp"],
                is_revoked=False,
            )
        )
        log_audit_event("auth.refresh_rotated", user_id=user.id, session=session)
        return AuthSession(
            principal=_user_to_principal(user),
            access_token=access_payload.token,
            refresh_token=new_refresh_payload.token,
        )


def restore_session(access_token: str | None, refresh_token: str | None) -> AuthSession:
    jwt_service = _get_jwt_service()
    if access_token:
        try:
            claims = jwt_service.decode_token(access_token, expected_type="access")
        except JWTExpiredError:
            return refresh_session(refresh_token or "")
        except JWTError as exc:
            raise SessionExpiredError("Your session is invalid. Please log in again.") from exc

        with session_scope() as session:
            user = session.get(User, int(claims["sub"]))
            if user is None or not user.is_active:
                raise SessionExpiredError("The user account is unavailable or inactive.")
            return AuthSession(
                principal=_user_to_principal(user),
                access_token=access_token,
                refresh_token=refresh_token,
            )

    if refresh_token:
        return refresh_session(refresh_token)

    raise SessionExpiredError("Please log in to continue.")


def logout_user(refresh_token: str | None) -> None:
    if not refresh_token:
        return

    jwt_service = _get_jwt_service()
    with session_scope() as session:
        try:
            claims = jwt_service.decode_token(refresh_token, expected_type="refresh", verify_exp=False)
        except JWTError:
            return

        refresh_record = _get_refresh_record(session, claims["jti"])
        if refresh_record is None:
            return

        refresh_record.is_revoked = True
        refresh_record.revoked_at = utcnow()
        log_audit_event("auth.logout", user_id=refresh_record.user_id, session=session)
