from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings
from app.domain.exceptions import (
    AccountNotFoundError,
    CategoryNotFoundError,
    DomainError,
    InvalidCredentialsError,
    InvalidSpeechInputError,
    InvalidTokenError,
    InvalidTransactionError,
    SpeechServiceNotConfiguredError,
    SpeechTranscriptionError,
    TransactionNotFoundError,
    UserAlreadyExistsError,
)

_EXCEPTION_STATUS_MAP: dict[type[DomainError], int] = {
    AccountNotFoundError: 404,
    CategoryNotFoundError: 404,
    InvalidCredentialsError: 401,
    InvalidSpeechInputError: 400,
    InvalidTokenError: 401,
    InvalidTransactionError: 400,
    SpeechServiceNotConfiguredError: 503,
    SpeechTranscriptionError: 502,
    TransactionNotFoundError: 404,
    UserAlreadyExistsError: 409,
}


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get('X-Request-ID', str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers['X-Request-ID'] = request_id
        return response


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
        return JSONResponse(status_code=status_code, content={'detail': str(exc) or exc.__class__.__name__})
