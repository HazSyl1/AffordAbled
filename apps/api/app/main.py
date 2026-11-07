from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from contextlib import asynccontextmanager, suppress
from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings, get_settings
from app.core.dependencies import (
    build_chat_service_for_session,
    get_guardrail_llm,
    get_semantic_guardrail,
    get_transaction_extraction_llm,
)
from app.core.logging import configure_logging
from app.core.middleware import register_exception_handlers, register_middleware
from app.infrastructure.audio.ffmpeg_audio_transcoder import resolve_ffmpeg_binary
from app.infrastructure.database.session import SessionLocal
from app.infrastructure.email import AzureAcsEmailProvider
from app.infrastructure.jobs import (
    run_chat_turn_loop,
    run_memory_outbox_loop,
    run_recurring_transaction_loop,
    run_retention_cleanup_once,
    run_split_notification_loop,
)
from app.infrastructure.sms import AzureAcsSmsProvider
from app.presentation.router import api_router

logger = logging.getLogger(__name__)


async def _probe_ffmpeg_health(settings: Settings) -> dict[str, Any]:
    configured_binary = (settings.ffmpeg_binary or 'ffmpeg').strip() or 'ffmpeg'
    resolved_binary = resolve_ffmpeg_binary(configured_binary)
    if resolved_binary == configured_binary and not os.path.isabs(resolved_binary):
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

    normalized_url = database_url
    if database_url.startswith('postgresql+asyncpg://'):
        normalized_url = database_url.replace('postgresql+asyncpg://', 'postgresql://', 1)
    elif database_url.startswith('postgresql+psycopg://'):
        normalized_url = database_url.replace('postgresql+psycopg://', 'postgresql://', 1)

    # asyncpg accepts ``ssl=require`` while psycopg/libpq expects
    # ``sslmode=require``. The same DATABASE_URL is used by both clients.
    if '?' not in normalized_url:
        return normalized_url

    base, query = normalized_url.split('?', 1)
    parameters = parse_qsl(query, keep_blank_values=True)
    if any(key == 'sslmode' for key, _ in parameters):
        return normalized_url
    parameters = [('sslmode' if key == 'ssl' else key, value) for key, value in parameters]
    return f'{base}?{urlencode(parameters)}'


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
                    chat_turn_retention_days=settings.chat_turn_retention_days,
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
        memory_outbox_task: asyncio.Task[None] | None = None
        chat_turn_task: asyncio.Task[None] | None = None
        recurring_transaction_task: asyncio.Task[None] | None = None
        split_notification_task: asyncio.Task[None] | None = None
        email_notification_task: asyncio.Task[None] | None = None

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

        if settings.memory_outbox_enabled:
            analysis_llm = get_transaction_extraction_llm(settings)
            memory_outbox_task = asyncio.create_task(
                run_memory_outbox_loop(
                    poll_interval_seconds=settings.memory_outbox_poll_interval_seconds,
                    batch_size=settings.memory_outbox_batch_size,
                    analysis_llm=analysis_llm,
                )
            )
            app.state.memory_outbox_task = memory_outbox_task
            logger.info(
                'memory.outbox.scheduler.started',
                extra={
                    'poll_interval_seconds': max(1, int(settings.memory_outbox_poll_interval_seconds)),
                    'batch_size': max(1, int(settings.memory_outbox_batch_size)),
                    'chat_analysis_enabled': analysis_llm is not None,
                },
            )

        if settings.chat_turn_worker_enabled:
            extraction_llm = get_transaction_extraction_llm(settings)
            guardrail_llm = get_guardrail_llm(settings)
            semantic_guardrail = get_semantic_guardrail(settings, guardrail_llm)

            async def process_chat_turn(job):
                if extraction_llm is None:
                    raise RuntimeError('Agentic chat requires a configured LLM deployment.')
                async with SessionLocal() as session:
                    chat_service = build_chat_service_for_session(
                        db=session,
                        checkpointer=checkpointer,
                        settings=settings,
                        semantic_guardrail=semantic_guardrail,
                        extraction_llm=extraction_llm,
                    )
                    response = await chat_service.send_message(
                        user_id=job.user_id,
                        message=job.message,
                        thread_id=job.thread_id,
                        timezone=job.timezone,
                        turn_id=job.id,
                    )
                    return response.to_public_dict()

            chat_turn_task = asyncio.create_task(
                run_chat_turn_loop(
                    process_chat_turn,
                    poll_interval_seconds=settings.chat_turn_poll_interval_seconds,
                    stale_after_seconds=settings.chat_turn_stale_after_seconds,
                    max_attempts=settings.chat_turn_max_attempts,
                )
            )
            app.state.chat_turn_task = chat_turn_task
            logger.info(
                'chat.turn.scheduler.started',
                extra={'poll_interval_seconds': max(1, settings.chat_turn_poll_interval_seconds)},
            )

        if settings.recurring_transaction_worker_enabled:
            recurring_transaction_task = asyncio.create_task(run_recurring_transaction_loop(
                stale_after_seconds=settings.recurring_transaction_stale_after_seconds,
                max_attempts=settings.recurring_transaction_max_attempts,
                batch_size=settings.recurring_transaction_batch_size,
                max_sleep_seconds=settings.recurring_transaction_max_sleep_seconds,
            ))
            app.state.recurring_transaction_task = recurring_transaction_task
            logger.info('recurring_transaction.scheduler.started', extra={
                'batch_size': max(1, settings.recurring_transaction_batch_size),
                'max_sleep_seconds': max(1, settings.recurring_transaction_max_sleep_seconds),
            })

        if settings.sms_enabled and settings.sms_worker_enabled:
            sms_provider = AzureAcsSmsProvider(
                settings.acs_connection_string,
                settings.acs_sender_number,
                settings.sms_send_timeout_seconds,
            )
            split_notification_task = asyncio.create_task(run_split_notification_loop(
                sms_provider,
                poll_interval_seconds=settings.sms_worker_poll_seconds,
                batch_size=settings.sms_worker_batch_size,
                stale_after_seconds=settings.sms_processing_stale_seconds,
            ))
            app.state.split_notification_task = split_notification_task
            logger.info('split_notification.scheduler.started', extra={
                'batch_size': max(1, settings.sms_worker_batch_size),
                'poll_interval_seconds': max(1, settings.sms_worker_poll_seconds),
            })

        email_worker_configured = (
            settings.email_enabled
            and settings.email_worker_enabled
            and settings.acs_connection_string
            and settings.email_sender_address
        )
        if email_worker_configured:
            email_provider = AzureAcsEmailProvider(
                settings.acs_connection_string, settings.email_sender_address, settings.email_send_timeout_seconds,
            )
            email_notification_task = asyncio.create_task(run_split_notification_loop(
                email_provider,
                poll_interval_seconds=settings.email_worker_poll_seconds,
                batch_size=settings.email_worker_batch_size,
                stale_after_seconds=settings.email_processing_stale_seconds,
                channel='email',
            ))

        try:
            yield
        finally:
            if retention_cleanup_task is not None:
                retention_cleanup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await retention_cleanup_task
            if memory_outbox_task is not None:
                memory_outbox_task.cancel()
                with suppress(asyncio.CancelledError):
                    await memory_outbox_task
            if chat_turn_task is not None:
                chat_turn_task.cancel()
                with suppress(asyncio.CancelledError):
                    await chat_turn_task
            if recurring_transaction_task is not None:
                recurring_transaction_task.cancel()
                with suppress(asyncio.CancelledError):
                    await recurring_transaction_task
            if split_notification_task is not None:
                split_notification_task.cancel()
                with suppress(asyncio.CancelledError):
                    await split_notification_task
            if email_notification_task is not None:
                email_notification_task.cancel()
                with suppress(asyncio.CancelledError):
                    await email_notification_task

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
    app.state.chat_turn_task = None
    app.state.recurring_transaction_task = None
    app.state.split_notification_task = None
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

