from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app import main as main_module


class _FailingAsyncContext:
    async def __aenter__(self):
        raise RuntimeError('postgres unavailable')

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type
        del exc
        del tb
        return False


def test_normalize_langgraph_postgres_conn_string() -> None:
    assert (
        main_module._normalize_langgraph_postgres_conn_string('postgresql+asyncpg://user:pass@localhost:5432/db')
        == 'postgresql://user:pass@localhost:5432/db'
    )
    assert (
        main_module._normalize_langgraph_postgres_conn_string('postgresql+psycopg://user:pass@localhost:5432/db')
        == 'postgresql://user:pass@localhost:5432/db'
    )
    assert main_module._normalize_langgraph_postgres_conn_string('sqlite+aiosqlite:///tmp/test.db') is None


@pytest.mark.asyncio
async def test_build_langgraph_checkpointer_auto_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main_module.AsyncPostgresSaver,
        'from_conn_string',
        staticmethod(lambda _: _FailingAsyncContext()),
    )

    settings = SimpleNamespace(
        langgraph_checkpointer_mode='auto',
        database_url='postgresql+asyncpg://postgres:postgres@localhost:5432/affordable',
        langgraph_checkpointer_startup_timeout_seconds=1,
    )

    checkpointer, checkpointer_context, backend = await main_module._build_langgraph_checkpointer(settings)

    assert isinstance(checkpointer, InMemorySaver)
    assert checkpointer_context is None
    assert backend == 'memory'


@pytest.mark.asyncio
async def test_build_langgraph_checkpointer_postgres_mode_raises_on_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module.AsyncPostgresSaver,
        'from_conn_string',
        staticmethod(lambda _: _FailingAsyncContext()),
    )

    settings = SimpleNamespace(
        langgraph_checkpointer_mode='postgres',
        database_url='postgresql+asyncpg://postgres:postgres@localhost:5432/affordable',
        langgraph_checkpointer_startup_timeout_seconds=1,
    )

    with pytest.raises(RuntimeError, match='Unable to initialize PostgreSQL LangGraph checkpointer'):
        await main_module._build_langgraph_checkpointer(settings)

