from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings, get_settings
from app.core.middleware import register_exception_handlers, register_middleware
from app.presentation.router import api_router

logger = logging.getLogger(__name__)


def _normalize_langgraph_postgres_conn_string(database_url: str) -> str | None:
    if not database_url.startswith('postgresql'):
        return None

    if database_url.startswith('postgresql+asyncpg://'):
        return database_url.replace('postgresql+asyncpg://', 'postgresql://', 1)

    if database_url.startswith('postgresql+psycopg://'):
        return database_url.replace('postgresql+psycopg://', 'postgresql://', 1)

    return database_url


async def _build_langgraph_checkpointer(settings: Settings) -> tuple[Any, Any | None, str]:
    mode = settings.langgraph_checkpointer_mode
    if mode == 'memory':
        logger.warning('LangGraph checkpointer mode is memory. Conversation checkpoints are not durable.')
        return InMemorySaver(), None, 'memory'

    postgres_conn_string = _normalize_langgraph_postgres_conn_string(settings.database_url)
    if postgres_conn_string is None:
        if mode == 'postgres':
            raise RuntimeError(
                'LANGGRAPH_CHECKPOINTER_MODE=postgres requires DATABASE_URL to use a PostgreSQL driver.'
            )
        logger.warning('DATABASE_URL is not PostgreSQL. Falling back to in-memory LangGraph checkpointer.')
        return InMemorySaver(), None, 'memory'

    checkpointer_context = AsyncPostgresSaver.from_conn_string(postgres_conn_string)
    startup_timeout_seconds = max(1, int(settings.langgraph_checkpointer_startup_timeout_seconds))

    try:
        checkpointer = await asyncio.wait_for(checkpointer_context.__aenter__(), timeout=startup_timeout_seconds)
        await asyncio.wait_for(checkpointer.setup(), timeout=startup_timeout_seconds)
        logger.info('LangGraph checkpointer initialized with PostgreSQL backend.')
        return checkpointer, checkpointer_context, 'postgres'
    except Exception as exc:
        try:
            await checkpointer_context.__aexit__(type(exc), exc, exc.__traceback__)
        except Exception:
            logger.debug('AsyncPostgresSaver cleanup after startup failure also failed.', exc_info=True)

        if mode == 'postgres':
            logger.exception('PostgreSQL checkpointer startup failed in postgres-only mode.')
            raise RuntimeError('Unable to initialize PostgreSQL LangGraph checkpointer') from exc

        logger.warning(
            'PostgreSQL checkpointer startup failed. Falling back to in-memory saver. '
            'Set LANGGRAPH_CHECKPOINTER_MODE=postgres to fail fast in strict environments.',
            exc_info=True,
        )
        return InMemorySaver(), None, 'memory'


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.langsmith_api_key:
            os.environ['LANGSMITH_API_KEY'] = settings.langsmith_api_key
        os.environ['LANGSMITH_TRACING'] = 'true' if settings.langsmith_tracing else 'false'
        os.environ['LANGSMITH_PROJECT'] = settings.langsmith_project

        checkpointer, checkpointer_context, checkpointer_backend = await _build_langgraph_checkpointer(settings)

        app.state.langgraph_checkpointer = checkpointer
        app.state.langgraph_checkpointer_context = checkpointer_context
        app.state.langgraph_checkpointer_backend = checkpointer_backend
        app.state.chat_orchestrator = None

        try:
            yield
        finally:
            if checkpointer_context is not None:
                await checkpointer_context.__aexit__(None, None, None)

    app = FastAPI(
        title='AffordAbled API',
        swagger_ui_parameters={'persistAuthorization': True},
        lifespan=lifespan,
    )

    app.state.langgraph_checkpointer = InMemorySaver()
    app.state.langgraph_checkpointer_context = None
    app.state.langgraph_checkpointer_backend = 'memory'
    app.state.chat_orchestrator = None

    register_middleware(app, settings)
    register_exception_handlers(app)

    app.include_router(api_router, prefix='/api/v1')

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    return app


app = create_app()

if __name__ == '__main__':
    import uvicorn

    uvicorn.run('app.main:app', host='0.0.0.0', port=8000, reload=True)

