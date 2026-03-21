from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

NULL_LIKE_VALUES = {"", "none", "null"}
HF_TOKEN_ENV_NAMES = (
    "HF_TOKEN",
    "HUGGINGFACE_API_KEY",
    "HUGGINGFACEHUB_API_TOKEN",
)


def _normalize_key(key: str) -> str:
    return key.lstrip("\ufeff").strip()


def _is_missing(value: str | None) -> bool:
    return value is None or value.strip().lower() in NULL_LIKE_VALUES


def load_environment(project_root: Path | None = None) -> None:
    env_path = (project_root or Path.cwd()) / ".env"
    if not env_path.exists():
        return

    load_dotenv(env_path, override=False)
    for key, value in dotenv_values(env_path).items():
        if key is None or value is None:
            continue
        normalized_key = _normalize_key(key)
        if os.getenv(normalized_key) is None:
            os.environ[normalized_key] = value

    hf_token = None
    for env_name in HF_TOKEN_ENV_NAMES:
        candidate = get_env(env_name)
        if not _is_missing(candidate):
            hf_token = candidate
            break
    if hf_token:
        os.environ.setdefault("HF_TOKEN", hf_token)
        os.environ.setdefault("HUGGINGFACEHUB_API_TOKEN", hf_token)


def get_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if _is_missing(value):
        value = os.getenv(f"\ufeff{name}")
    if _is_missing(value) and name in HF_TOKEN_ENV_NAMES:
        for env_name in HF_TOKEN_ENV_NAMES:
            candidate = os.getenv(env_name)
            if _is_missing(candidate):
                candidate = os.getenv(f"\ufeff{env_name}")
            if not _is_missing(candidate):
                value = candidate
                break
    if _is_missing(value):
        return default
    return value
