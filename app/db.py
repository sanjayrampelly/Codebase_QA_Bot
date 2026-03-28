from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from utils.config import get_env, load_environment

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_environment(PROJECT_ROOT)


def get_database_url() -> str:
    configured_url = get_env("DATABASE_URL")
    if configured_url:
        return configured_url
    default_db_path = PROJECT_ROOT / "codebase_qna.db"
    return f"sqlite:///{default_db_path.as_posix()}"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    database_url = get_database_url()
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    from app.models import Base

    Base.metadata.create_all(bind=get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
