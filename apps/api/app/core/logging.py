from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.config import dictConfig

from app.core.request_context import get_request_id

_STANDARD_LOG_RECORD_KEYS = {
    'args',
    'asctime',
    'created',
    'exc_info',
    'exc_text',
    'filename',
    'funcName',
    'levelname',
    'levelno',
    'lineno',
    'module',
    'msecs',
    'message',
    'msg',
    'name',
    'pathname',
    'process',
    'processName',
    'relativeCreated',
    'stack_info',
    'thread',
    'threadName',
    'taskName',
}


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            'timestamp': datetime.now(UTC).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        request_id = getattr(record, 'request_id', None)
        if request_id:
            payload['request_id'] = request_id

        extra = self._extract_extra(record)
        if extra:
            payload['extra'] = extra

        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _extract_extra(record: logging.LogRecord) -> dict[str, object]:
        extra: dict[str, object] = {}
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_RECORD_KEYS or key == 'request_id':
                continue
            if value is None:
                continue
            extra[key] = value
        return extra


def configure_logging(level: str = 'INFO') -> None:
    normalized_level = level.upper()
    dictConfig(
        {
            'version': 1,
            'disable_existing_loggers': False,
            'filters': {
                'request_context': {
                    '()': RequestContextFilter,
                }
            },
            'formatters': {
                'json': {
                    '()': JsonFormatter,
                }
            },
            'handlers': {
                'default': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'json',
                    'filters': ['request_context'],
                }
            },
            'root': {
                'level': normalized_level,
                'handlers': ['default'],
            },
            'loggers': {
                'uvicorn': {'handlers': ['default'], 'level': normalized_level, 'propagate': False},
                'uvicorn.error': {'handlers': ['default'], 'level': normalized_level, 'propagate': False},
                'uvicorn.access': {'handlers': ['default'], 'level': normalized_level, 'propagate': False},
            },
        }
    )

