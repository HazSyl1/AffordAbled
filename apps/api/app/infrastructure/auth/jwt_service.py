from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import Settings
from app.domain.exceptions import InvalidTokenError

ALGORITHM = "HS256"


class JwtTokenService:
    def __init__(self, settings: Settings) -> None:
        self._secret_key = settings.jwt_secret_key
        self._access_expires = timedelta(minutes=settings.access_token_expire_minutes)
        self._refresh_expires = timedelta(days=settings.refresh_token_expire_days)

    def create_access_token(self, user_id: uuid.UUID) -> str:
        now = datetime.now(UTC)
        payload = {"sub": str(user_id), "type": "access", "iat": now, "exp": now + self._access_expires}
        return jwt.encode(payload, self._secret_key, algorithm=ALGORITHM)

    def create_refresh_token(self, user_id: uuid.UUID) -> tuple[str, str, datetime]:
        now = datetime.now(UTC)
        expires_at = now + self._refresh_expires
        jti = uuid.uuid4().hex
        payload = {"sub": str(user_id), "type": "refresh", "jti": jti, "iat": now, "exp": expires_at}
        token = jwt.encode(payload, self._secret_key, algorithm=ALGORITHM)
        return token, jti, expires_at

    def decode_access_token(self, token: str) -> uuid.UUID:
        payload = self._decode(token)
        if payload.get("type") != "access":
            raise InvalidTokenError()
        return uuid.UUID(payload["sub"])

    def decode_refresh_token(self, token: str) -> tuple[uuid.UUID, str]:
        payload = self._decode(token)
        if payload.get("type") != "refresh":
            raise InvalidTokenError()
        return uuid.UUID(payload["sub"]), payload["jti"]

    def _decode(self, token: str) -> dict:
        try:
            return jwt.decode(token, self._secret_key, algorithms=[ALGORITHM])
        except jwt.PyJWTError as exc:
            raise InvalidTokenError() from exc
