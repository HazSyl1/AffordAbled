from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.application.dto import LoginInput, RegisterUserInput, TokenPair
from app.domain.entities import RefreshSession, User
from app.domain.exceptions import InvalidCredentialsError, InvalidTokenError, UserAlreadyExistsError
from app.domain.ports import GoogleOAuthClient, PasswordHasher, TokenService
from app.domain.repositories import RefreshSessionRepository, UserRepository


@dataclass
class AuthService:
    user_repository: UserRepository
    refresh_session_repository: RefreshSessionRepository
    password_hasher: PasswordHasher
    token_service: TokenService
    google_oauth_client: GoogleOAuthClient

    async def register(self, data: RegisterUserInput) -> TokenPair:
        existing = await self.user_repository.get_by_email(data.email)
        if existing is not None:
            raise UserAlreadyExistsError(data.email)
        user = User(
            id=uuid.uuid4(),
            email=data.email,
            name=data.name,
            date_of_birth=data.date_of_birth,
            hashed_password=self.password_hasher.hash(data.password),
            google_sub=None,
            created_at=datetime.now(UTC),
        )
        user = await self.user_repository.create(user)
        return await self._issue_tokens(user.id)

    async def login(self, data: LoginInput) -> TokenPair:
        user = await self.user_repository.get_by_email(data.email)
        if user is None or user.hashed_password is None:
            raise InvalidCredentialsError()
        if not self.password_hasher.verify(data.password, user.hashed_password):
            raise InvalidCredentialsError()
        return await self._issue_tokens(user.id)

    async def login_with_google(self, code: str, redirect_uri: str) -> TokenPair:
        profile = await self.google_oauth_client.exchange_code(code, redirect_uri)
        user = await self.user_repository.get_by_google_sub(profile.sub)
        if user is None:
            user = await self.user_repository.get_by_email(profile.email)
        if user is None:
            user = User(
                id=uuid.uuid4(),
                email=profile.email,
                name=profile.name or profile.email.split('@')[0],
                date_of_birth=None,
                hashed_password=None,
                google_sub=profile.sub,
                created_at=datetime.now(UTC),
            )
            user = await self.user_repository.create(user)
        return await self._issue_tokens(user.id)

    async def refresh(self, refresh_token: str) -> TokenPair:
        user_id, jti = self.token_service.decode_refresh_token(refresh_token)
        session = await self.refresh_session_repository.get_by_jti(jti)
        if session is None or session.revoked_at is not None or session.expires_at < datetime.now(UTC):
            raise InvalidTokenError()
        await self.refresh_session_repository.revoke(jti)
        return await self._issue_tokens(user_id)

    async def logout(self, refresh_token: str) -> None:
        try:
            _, jti = self.token_service.decode_refresh_token(refresh_token)
        except InvalidTokenError:
            return
        await self.refresh_session_repository.revoke(jti)

    async def _issue_tokens(self, user_id: uuid.UUID) -> TokenPair:
        access_token = self.token_service.create_access_token(user_id)
        refresh_token, jti, expires_at = self.token_service.create_refresh_token(user_id)
        await self.refresh_session_repository.create(
            RefreshSession(id=uuid.uuid4(), user_id=user_id, jti=jti, expires_at=expires_at, revoked_at=None)
        )
        return TokenPair(access_token=access_token, refresh_token=refresh_token)
