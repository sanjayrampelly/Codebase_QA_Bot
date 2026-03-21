from __future__ import annotations

from pathlib import Path
from typing import Iterable, Set

SUPPORTED_EXTENSIONS: Set[str] = {
    ".py",
    ".js",
    ".ts",
    ".java",
    ".cpp",
    ".go",
    ".rs",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
}

SKIP_SUFFIXES = {
    ".lock",
}


def is_supported_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def should_skip_dir(dir_name: str) -> bool:
    return dir_name in SKIP_DIRS


def iter_code_files(root: Path) -> Iterable[Path]:
    for current_root, dirnames, filenames in os_walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for file in filenames:
            path = Path(current_root) / file
            if is_supported_file(path):
                yield path


def os_walk(root: Path):
    import os

    return os.walk(root)
