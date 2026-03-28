from __future__ import annotations

from collections.abc import Mapping


class AuthorizationError(Exception):
    pass


def _principal_values(principal: Mapping | object, key: str) -> list[str]:
    if isinstance(principal, Mapping):
        values = principal.get(key, [])
    else:
        values = getattr(principal, key, [])
    return list(values or [])


def has_role(principal: Mapping | object, role_name: str) -> bool:
    return role_name in _principal_values(principal, "roles")


def has_permission(principal: Mapping | object, permission_name: str) -> bool:
    return permission_name in _principal_values(principal, "permissions")


def require_permission(principal: Mapping | object, permission_name: str) -> None:
    if not has_permission(principal, permission_name):
        raise AuthorizationError(f"Missing required permission: {permission_name}")


def is_admin(principal: Mapping | object) -> bool:
    return has_role(principal, "admin") or has_permission(principal, "user:manage")
