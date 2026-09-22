from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.account_service import AccountService
from app.application.services.auth_service import AuthService
from app.application.services.category_service import CategoryService
from app.application.services.transaction_service import TransactionService
from app.core.config import Settings, get_settings
from app.core.security import BEARER_PREFIX
from app.domain.entities import User
from app.domain.exceptions import InvalidTokenError
from app.infrastructure.auth.google_oauth import GoogleAuthClient
from app.infrastructure.auth.jwt_service import JwtTokenService
from app.infrastructure.auth.password_hasher import Argon2PasswordHasher
from app.infrastructure.database.repositories.sqlalchemy_account_repository import SqlAlchemyAccountRepository
from app.infrastructure.database.repositories.sqlalchemy_category_repository import SqlAlchemyCategoryRepository
from app.infrastructure.database.repositories.sqlalchemy_refresh_session_repository import (
    SqlAlchemyRefreshSessionRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_transaction_repository import SqlAlchemyTransactionRepository
from app.infrastructure.database.repositories.sqlalchemy_user_repository import SqlAlchemyUserRepository
from app.infrastructure.database.session import get_session


async def get_db(session: AsyncSession = Depends(get_session)) -> AsyncGenerator[AsyncSession]:
    yield session


def get_settings_dependency() -> Settings:
    return get_settings()


def get_user_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyUserRepository:
    return SqlAlchemyUserRepository(db)


def get_account_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyAccountRepository:
    return SqlAlchemyAccountRepository(db)


def get_category_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyCategoryRepository:
    return SqlAlchemyCategoryRepository(db)


def get_transaction_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyTransactionRepository:
    return SqlAlchemyTransactionRepository(db)


def get_refresh_session_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyRefreshSessionRepository:
    return SqlAlchemyRefreshSessionRepository(db)


def get_password_hasher() -> Argon2PasswordHasher:
    return Argon2PasswordHasher()


def get_token_service(settings: Settings = Depends(get_settings_dependency)) -> JwtTokenService:
    return JwtTokenService(settings)


def get_google_oauth_client(settings: Settings = Depends(get_settings_dependency)) -> GoogleAuthClient:
    return GoogleAuthClient(settings)


def get_auth_service(
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
    refresh_session_repository: SqlAlchemyRefreshSessionRepository = Depends(get_refresh_session_repository),
    password_hasher: Argon2PasswordHasher = Depends(get_password_hasher),
    token_service: JwtTokenService = Depends(get_token_service),
    google_oauth_client: GoogleAuthClient = Depends(get_google_oauth_client),
) -> AuthService:
    return AuthService(
        user_repository=user_repository,
        refresh_session_repository=refresh_session_repository,
        password_hasher=password_hasher,
        token_service=token_service,
        google_oauth_client=google_oauth_client,
    )


def get_account_service(
    account_repository: SqlAlchemyAccountRepository = Depends(get_account_repository),
) -> AccountService:
    return AccountService(account_repository=account_repository)


def get_category_service(
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
) -> CategoryService:
    return CategoryService(category_repository=category_repository)


def get_transaction_service(
    transaction_repository: SqlAlchemyTransactionRepository = Depends(get_transaction_repository),
    account_repository: SqlAlchemyAccountRepository = Depends(get_account_repository),
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
) -> TransactionService:
    return TransactionService(
        transaction_repository=transaction_repository,
        account_repository=account_repository,
        category_repository=category_repository,
    )


async def get_current_user(
    request: Request,
    token_service: JwtTokenService = Depends(get_token_service),
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
) -> User:
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith(BEARER_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')
    token = auth_header[len(BEARER_PREFIX) :]
    try:
        user_id: uuid.UUID = token_service.decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token') from exc
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token')
    return user
