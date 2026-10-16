from __future__ import annotations

import logging
import uuid
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings
from app.core.request_context import reset_request_id, set_request_id
from app.domain.exceptions import (
    AccountNotFoundError,
    CategoryNotFoundError,
    ChatThreadAlreadyExistsError,
    ChatThreadNotFoundError,
    DomainError,
    ExportLinkExpiredError,
    ExportNotFoundError,
    ImageAnalysisError,
    ImageServiceNotConfiguredError,
    ImportAlreadyExistsError,
    InvalidChatInputError,
    InvalidCredentialsError,
    InvalidExportError,
    InvalidImageInputError,
    InvalidImportError,
    InvalidSpeechInputError,
    InvalidTokenError,
    InvalidTransactionError,
    SpeechServiceNotConfiguredError,
    SpeechTranscriptionError,
    TransactionNotFoundError,
    UserAlreadyExistsError,
)

logger = logging.getLogger(__name__)

_EXCEPTION_STATUS_MAP: dict[type[DomainError], int] = {
    AccountNotFoundError: 404,
    CategoryNotFoundError: 404,
    ChatThreadAlreadyExistsError: 409,
    ChatThreadNotFoundError: 404,
    ExportLinkExpiredError: 410,
    ExportNotFoundError: 404,
    InvalidExportError: 400,
    ImportAlreadyExistsError: 409,
    InvalidImportError: 400,
    InvalidCredentialsError: 401,
    InvalidChatInputError: 400,
    InvalidImageInputError: 400,
    InvalidSpeechInputError: 400,
    InvalidTokenError: 401,
    InvalidTransactionError: 400,
    ImageServiceNotConfiguredError: 503,
    ImageAnalysisError: 502,
    SpeechServiceNotConfiguredError: 503,
    SpeechTranscriptionError: 502,
    TransactionNotFoundError: 404,
    UserAlreadyExistsError: 409,
}


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        request_context_token = set_request_id(request_id)
        request.state.request_id = request_id
        start_time = perf_counter()
        response = None

        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((perf_counter() - start_time) * 1000, 2)
            status_code = response.status_code if response is not None else 500
            logger.info(
                'request.completed',
                extra={
                    'request_method': request.method,
                    'request_path': request.url.path,
                    'status_code': status_code,
                    'duration_ms': duration_ms,
                },
            )

            if response is not None:
                response.headers['X-Request-ID'] = request_id

            reset_request_id(request_context_token)


def register_middleware(app: FastAPI, settings: Settings) -> None:
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        status_code = _EXCEPTION_STATUS_MAP.get(type(exc), 400)
        return JSONResponse(
            status_code=status_code,
            content={
                'detail': str(exc) or exc.__class__.__name__,
                'request_id': getattr(request.state, 'request_id', None),
            },
        )
