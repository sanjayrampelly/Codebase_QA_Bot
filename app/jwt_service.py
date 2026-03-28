from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from utils.config import get_env, load_environment

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_environment(PROJECT_ROOT)


class JWTError(Exception):
    pass


class JWTExpiredError(JWTError):
    pass


@dataclass
class TokenPayload:
    token: str
    claims: dict


class JWTService:
    def __init__(
        self,
        *,
        secret_key: str | None = None,
        algorithm: str | None = None,
        access_minutes: int | None = None,
        refresh_days: int | None = None,
    ) -> None:
        self.secret_key = secret_key or get_env("JWT_SECRET_KEY")
        self.algorithm = algorithm or get_env("JWT_ALGORITHM", "HS256")
        self.access_minutes = access_minutes or int(get_env("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
        self.refresh_days = refresh_days or int(get_env("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))
        if not self.secret_key:
            raise ValueError("JWT_SECRET_KEY is not set")

    def _base_claims(self, user, token_type: str, expires_at: datetime) -> dict:
        issued_at = datetime.utcnow()
        return {
            "sub": str(user.id),
            "username": user.username,
            "roles": user.role_names(),
            "permissions": user.permission_names(),
            "token_type": token_type,
            "jti": str(uuid4()),
            "iat": issued_at,
            "exp": expires_at,
        }

    def create_access_token(self, user) -> TokenPayload:
        expires_at = datetime.utcnow() + timedelta(minutes=self.access_minutes)
        claims = self._base_claims(user, "access", expires_at)
        return TokenPayload(token=jwt.encode(claims, self.secret_key, algorithm=self.algorithm), claims=claims)

    def create_refresh_token(self, user) -> TokenPayload:
        expires_at = datetime.utcnow() + timedelta(days=self.refresh_days)
        claims = self._base_claims(user, "refresh", expires_at)
        return TokenPayload(token=jwt.encode(claims, self.secret_key, algorithm=self.algorithm), claims=claims)

    def decode_token(
        self,
        token: str,
        *,
        expected_type: str | None = None,
        verify_exp: bool = True,
    ) -> dict:
        try:
            claims = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"verify_exp": verify_exp},
            )
        except ExpiredSignatureError as exc:
            raise JWTExpiredError("Token has expired.") from exc
        except InvalidTokenError as exc:
            raise JWTError("Token is invalid.") from exc

        token_type = claims.get("token_type")
        if expected_type and token_type != expected_type:
            raise JWTError(f"Expected a {expected_type} token.")
        return claims
