from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import get_settings
from app.core.middleware import register_exception_handlers, register_middleware
from app.presentation.router import api_router


def _langgraph_conn_string(database_url: str) -> str | None:
    if not database_url.startswith('postgresql'):
        return None

    if database_url.startswith('postgresql+asyncpg://'):
        return database_url.replace('postgresql+asyncpg://', 'postgresql://', 1)

    if database_url.startswith('postgresql+psycopg://'):
        return database_url.replace('postgresql+psycopg://', 'postgresql://', 1)

    return database_url


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.langsmith_api_key:
            os.environ['LANGSMITH_API_KEY'] = settings.langsmith_api_key
        os.environ['LANGSMITH_TRACING'] = 'true' if settings.langsmith_tracing else 'false'
        os.environ['LANGSMITH_PROJECT'] = settings.langsmith_project

        checkpointer_context = None
        checkpointer = InMemorySaver()

        postgres_conn_string = _langgraph_conn_string(settings.database_url)
        if postgres_conn_string:
            checkpointer_context = AsyncPostgresSaver.from_conn_string(postgres_conn_string)
            checkpointer = await checkpointer_context.__aenter__()
            await checkpointer.setup()

        app.state.langgraph_checkpointer = checkpointer
        app.state.langgraph_checkpointer_context = checkpointer_context
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

