from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


class APIClientError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass
class APIClient:
    base_url: str
    timeout_seconds: int = 60

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = requests.request(
                method,
                self._url(path),
                headers=headers,
                json=json,
                params=params,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise APIClientError(f"Could not reach backend at {self.base_url}.") from exc

        if response.status_code == 204:
            return None

        try:
            payload = response.json()
        except ValueError:
            payload = {"message": response.text or "Unknown backend error."}

        if response.ok:
            return payload

        message = payload.get("detail") or payload.get("message") or "Backend request failed."
        raise APIClientError(message, status_code=response.status_code, payload=payload)

    def health(self) -> Any:
        return self._request("GET", "/health")

    def login(self, username_or_email: str, password: str) -> dict:
        return self._request(
            "POST",
            "/auth/login",
            json={"usernameOrEmail": username_or_email, "password": password},
        )

    def register(self, username: str, email: str, password: str) -> dict:
        return self._request(
            "POST",
            "/auth/register",
            json={"username": username, "email": email, "password": password},
        )

    def refresh(self, refresh_token: str) -> dict:
        return self._request(
            "POST",
            "/auth/refresh",
            json={"refreshToken": refresh_token},
        )

    def logout(self, access_token: str, refresh_token: str) -> None:
        self._request(
            "POST",
            "/auth/logout",
            token=access_token,
            json={"refreshToken": refresh_token},
        )

    def me(self, access_token: str) -> dict:
        return self._request("GET", "/auth/me", token=access_token)

    def list_users(self, access_token: str) -> dict:
        return self._request("GET", "/users", token=access_token)

    def create_user(self, access_token: str, payload: dict) -> dict:
        return self._request("POST", "/users", token=access_token, json=payload)

    def update_user_roles(self, access_token: str, user_id: int, role_names: list[str]) -> dict:
        return self._request(
            "PUT",
            f"/users/{user_id}/roles",
            token=access_token,
            json={"roleNames": role_names},
        )

    def list_roles(self, access_token: str) -> dict:
        return self._request("GET", "/roles", token=access_token)

    def create_role(self, access_token: str, payload: dict) -> dict:
        return self._request("POST", "/roles", token=access_token, json=payload)

    def list_repositories(self, access_token: str) -> dict:
        return self._request("GET", "/repositories", token=access_token)

    def index_repository(self, access_token: str, repo_url: str, force_reindex: bool = False) -> dict:
        return self._request(
            "POST",
            "/repositories",
            token=access_token,
            json={"repoUrl": repo_url, "forceReindex": force_reindex},
        )

    def reindex_repository(self, access_token: str, repository_id: int) -> dict:
        return self._request(
            "POST",
            f"/repositories/{repository_id}/reindex",
            token=access_token,
        )

    def get_repository_access(self, access_token: str, repository_id: int) -> dict:
        return self._request(
            "GET",
            f"/repositories/{repository_id}/access",
            token=access_token,
        )

    def grant_repository_access(
        self,
        access_token: str,
        repository_id: int,
        user_id: int,
        access_level: str,
    ) -> dict:
        return self._request(
            "POST",
            f"/repositories/{repository_id}/access",
            token=access_token,
            json={"userId": user_id, "accessLevel": access_level},
        )

    def ask_question(
        self,
        access_token: str,
        repository_id: int,
        question: str,
        top_k: int,
        include_context: bool,
    ) -> dict:
        return self._request(
            "POST",
            f"/repositories/{repository_id}/questions",
            token=access_token,
            json={"question": question, "topK": top_k, "includeContext": include_context},
        )

    def get_audit_logs(
        self,
        access_token: str,
        *,
        user_id: int | None = None,
        action: str | None = None,
        repository_id: int | None = None,
    ) -> dict:
        params = {}
        if user_id is not None:
            params["user_id"] = user_id
        if action:
            params["action"] = action
        if repository_id is not None:
            params["repository_id"] = repository_id
        return self._request("GET", "/audit-logs", token=access_token, params=params or None)
