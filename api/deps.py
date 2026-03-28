from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import AuthenticatedPrincipal
from app.authorization import has_permission
from app.db import session_scope
from app.jwt_service import JWTError, JWTExpiredError, JWTService
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def to_principal(user: User) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user.id,
        username=user.username,
        email=user.email,
        roles=user.role_names(),
        permissions=user.permission_names(),
        is_active=user.is_active,
    )


def get_current_principal(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AuthenticatedPrincipal:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    service = JWTService()
    try:
        claims = service.decode_token(credentials.credentials, expected_type="access")
    except JWTExpiredError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token expired.") from exc
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token.") from exc

    with session_scope() as session:
        user = session.get(User, int(claims["sub"]))
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User is inactive or missing.",
            )
        return to_principal(user)


def require_permission(permission_name: str):
    def dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if not has_permission(principal.to_session_dict(), permission_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission_name}",
            )
        return principal

    return dependency
