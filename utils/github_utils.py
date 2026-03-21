from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from git import Repo

from utils.logger import get_logger

logger = get_logger(__name__)

GITHUB_REGEX = re.compile(
    r"^(https://github.com/[^/]+/[^/]+)(\.git)?/?$", re.IGNORECASE
)


def is_valid_github_url(url: str) -> bool:
    return bool(GITHUB_REGEX.match(url.strip()))


def normalize_repo_url(url: str) -> str:
    match = GITHUB_REGEX.match(url.strip())
    if not match:
        return url.strip()
    return match.group(1)


def clone_repo(github_url: str, dest_dir: Optional[str] = None) -> str:
    github_url = github_url.strip()
    if Path(github_url).exists():
        logger.info("Using local path for repository: %s", github_url)
        return str(Path(github_url).resolve())

    if not is_valid_github_url(github_url):
        raise ValueError("Invalid GitHub URL. Please provide a public repo URL.")

    repo_url = normalize_repo_url(github_url)
    target_dir = dest_dir or tempfile.mkdtemp(prefix="codebase_qna_")
    logger.info("Cloning %s into %s", repo_url, target_dir)
    Repo.clone_from(repo_url, target_dir)
    return target_dir
