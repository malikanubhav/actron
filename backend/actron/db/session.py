"""Database engines and sessions (sync for migrations and simple activities, async for the API)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from actron.config import get_settings


def _url(url: str | None = None) -> str:
    raw = url or get_settings().DATABASE_URL
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


@lru_cache(maxsize=4)
def engine(url: str | None = None) -> Engine:
    return create_engine(_url(url), pool_pre_ping=True, pool_size=10, max_overflow=20)


@lru_cache(maxsize=4)
def async_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(_url(url), pool_pre_ping=True, pool_size=10, max_overflow=20)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    maker = sessionmaker(engine(url), expire_on_commit=False)
    with maker() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


@asynccontextmanager
async def async_session(url: str | None = None) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(async_engine(url), expire_on_commit=False)
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def reset_engines() -> None:
    """Tests only: forget cached engines (after changing DATABASE_URL)."""
    engine.cache_clear()
    async_engine.cache_clear()
