from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import register_exception_handlers, register_middleware
from app.infrastructure.database.session import SessionLocal
from app.infrastructure.jobs import run_retention_cleanup_once
from app.presentation.router import api_router

logger = logging.getLogger(__name__)


async def _probe_ffmpeg_health(settings: Settings) -> dict[str, Any]:
    configured_binary = (settings.ffmpeg_binary or 'ffmpeg').strip() or 'ffmpeg'
    resolved_binary = shutil.which(configured_binary)
    if resolved_binary is None:
        logger.warning(
            'audio.ffmpeg.health',
            extra={
                'available': False,
                'ffmpeg_binary': configured_binary,
                'reason': 'binary_not_found',
            },
        )
        return {
            'available': False,
            'configured_binary': configured_binary,
            'resolved_binary': None,
            'version': None,
            'reason': 'binary_not_found',
        }

    try:
        completed_process = await asyncio.to_thread(
            subprocess.run,
            [resolved_binary, '-version'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except FileNotFoundError:
        logger.warning(
            'audio.ffmpeg.health',
            extra={
                'available': False,
                'ffmpeg_binary': configured_binary,
                'resolved_binary': resolved_binary,
                'reason': 'binary_not_found',
            },
        )
        return {
            'available': False,
            'configured_binary': configured_binary,
            'resolved_binary': resolved_binary,
            'version': None,
            'reason': 'binary_not_found',
        }
    except subprocess.TimeoutExpired:
        logger.warning(
            'audio.ffmpeg.health',
            extra={
                'available': False,
                'ffmpeg_binary': configured_binary,
                'resolved_binary': resolved_binary,
                'reason': 'health_check_timeout',
            },
        )
        return {
            'available': False,
            'configured_binary': configured_binary,
            'resolved_binary': resolved_binary,
            'version': None,
            'reason': 'health_check_timeout',
        }

    version_line = None
    if completed_process.stdout:
        version_line = completed_process.stdout.splitlines()[0].strip() or None

    if completed_process.returncode != 0:
        logger.warning(
            'audio.ffmpeg.health',
            extra={
                'available': False,
                'ffmpeg_binary': configured_binary,
                'resolved_binary': resolved_binary,
                'reason': 'non_zero_exit',
                'return_code': completed_process.returncode,
            },
        )
        return {
            'available': False,
            'configured_binary': configured_binary,
            'resolved_binary': resolved_binary,
            'version': version_line,
            'reason': 'non_zero_exit',
        }

    logger.info(
        'audio.ffmpeg.health',
        extra={
            'available': True,
            'ffmpeg_binary': configured_binary,
            'resolved_binary': resolved_binary,
            'version': version_line,
        },
    )
    return {
        'available': True,
        'configured_binary': configured_binary,
        'resolved_binary': resolved_binary,
        'version': version_line,
        'reason': None,
    }


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


async def _run_retention_cleanup_loop(settings: Settings) -> None:
    interval_seconds = max(60, int(settings.retention_cleanup_interval_minutes) * 60)

    while True:
        try:
            async with SessionLocal() as session:
                cleanup_stats = await run_retention_cleanup_once(
                    session,
                    chat_message_retention_days=settings.chat_message_retention_days,
                )

            logger.info('retention.cleanup.completed', extra=cleanup_stats)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('retention.cleanup.failed')

        await asyncio.sleep(interval_seconds)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.langsmith_api_key:
            os.environ['LANGSMITH_API_KEY'] = settings.langsmith_api_key
        os.environ['LANGSMITH_TRACING'] = 'true' if settings.langsmith_tracing else 'false'
        os.environ['LANGSMITH_PROJECT'] = settings.langsmith_project

        ffmpeg_health = await _probe_ffmpeg_health(settings)
        app.state.ffmpeg_health = ffmpeg_health
        if settings.audio_transcoder_required and not ffmpeg_health['available']:
            raise RuntimeError(
                'FFmpeg is required but unavailable. Set FFMPEG_BINARY correctly and ensure ffmpeg is installed.'
            )

        checkpointer, checkpointer_context, checkpointer_backend = await _build_langgraph_checkpointer(settings)

        app.state.langgraph_checkpointer = checkpointer
        app.state.langgraph_checkpointer_context = checkpointer_context
        app.state.langgraph_checkpointer_backend = checkpointer_backend
        app.state.chat_orchestrator = None
        retention_cleanup_task: asyncio.Task[None] | None = None

        if settings.retention_cleanup_enabled:
            retention_cleanup_task = asyncio.create_task(_run_retention_cleanup_loop(settings))
            app.state.retention_cleanup_task = retention_cleanup_task
            logger.info(
                'retention.cleanup.scheduler.started',
                extra={
                    'interval_minutes': max(1, int(settings.retention_cleanup_interval_minutes)),
                    'chat_message_retention_days': max(1, int(settings.chat_message_retention_days)),
                },
            )

        try:
            yield
        finally:
            if retention_cleanup_task is not None:
                retention_cleanup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await retention_cleanup_task

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
    app.state.retention_cleanup_task = None
    app.state.ffmpeg_health = {
        'available': False,
        'configured_binary': settings.ffmpeg_binary,
        'resolved_binary': None,
        'version': None,
        'reason': 'startup_not_completed',
    }

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

