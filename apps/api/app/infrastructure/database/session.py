from __future__ import annotations

from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_settings = get_settings()


def normalize_asyncpg_database_url(database_url: str) -> str:
    """Translate libpq's sslmode query parameter to asyncpg's ssl parameter."""
    if '+asyncpg' not in database_url or '?' not in database_url:
        return database_url

    parsed = urlsplit(database_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key == 'ssl' for key, _ in query):
        query = [(key, value) for key, value in query if key != 'sslmode']
    else:
        query = [('ssl' if key == 'sslmode' else key, value) for key, value in query]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


engine = create_async_engine(normalize_asyncpg_database_url(_settings.database_url), echo=False, future=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
