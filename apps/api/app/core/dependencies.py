from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

try:  # optional in local/dev until dependency is installed
    from langchain_openai import AzureChatOpenAI
except ImportError:  # pragma: no cover - exercised in environments without langchain-openai
    AzureChatOpenAI = None

from app.application.services.account_service import AccountService
from app.application.services.auth_service import AuthService
from app.application.services.category_service import CategoryService
from app.application.services.chat_service import ChatService
from app.application.services.speech_service import SpeechService
from app.application.services.transaction_service import TransactionService
from app.core.config import Settings, get_settings
from app.domain.entities import User
from app.domain.exceptions import InvalidTokenError
from app.domain.ports import ChatOrchestrator
from app.infrastructure.ai.intent_classifier import KeywordIntentClassifier
from app.infrastructure.ai.langgraph_chat_orchestrator import LangGraphChatOrchestrator
from app.infrastructure.ai.semantic_guardrail import KeywordSemanticGuardrail
from app.infrastructure.auth.google_oauth import GoogleAuthClient
from app.infrastructure.auth.jwt_service import JwtTokenService
from app.infrastructure.auth.password_hasher import Argon2PasswordHasher
from app.infrastructure.azure.azure_speech_to_text import AzureSpeechToTextClient
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


access_token_scheme = HTTPBearer(auto_error=False)


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


def get_speech_to_text_client(settings: Settings = Depends(get_settings_dependency)) -> AzureSpeechToTextClient:
    return AzureSpeechToTextClient(settings)


def get_semantic_guardrail() -> KeywordSemanticGuardrail:
    return KeywordSemanticGuardrail()


def get_intent_classifier() -> KeywordIntentClassifier:
    return KeywordIntentClassifier()


def get_langgraph_checkpointer(request: Request) -> Any:
    checkpointer = getattr(request.app.state, 'langgraph_checkpointer', None)
    if checkpointer is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Chat runtime is not initialized')
    return checkpointer


def get_transaction_extraction_llm(settings: Settings = Depends(get_settings_dependency)) -> Any | None:
    if AzureChatOpenAI is None:
        return None

    deployment = settings.azure_openai_extraction_deployment or settings.azure_openai_deployment
    if not settings.azure_openai_endpoint or not settings.azure_openai_api_key or not deployment:
        return None

    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=deployment,
        api_version=settings.azure_openai_api_version,
        temperature=0,
        timeout=20,
        max_retries=2,
    )


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


def get_chat_orchestrator(
    checkpointer: Any = Depends(get_langgraph_checkpointer),
    settings: Settings = Depends(get_settings_dependency),
    semantic_guardrail: KeywordSemanticGuardrail = Depends(get_semantic_guardrail),
    intent_classifier: KeywordIntentClassifier = Depends(get_intent_classifier),
    transaction_service: TransactionService = Depends(get_transaction_service),
    account_repository: SqlAlchemyAccountRepository = Depends(get_account_repository),
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
    extraction_llm: Any | None = Depends(get_transaction_extraction_llm),
) -> ChatOrchestrator:
    return LangGraphChatOrchestrator(
        checkpointer=checkpointer,
        semantic_guardrail=semantic_guardrail,
        intent_classifier=intent_classifier,
        transaction_service=transaction_service,
        account_repository=account_repository,
        category_repository=category_repository,
        extraction_llm=extraction_llm,
        proposal_confidence_threshold=settings.chat_proposal_confidence_threshold,
        hitl_max_turns=settings.chat_hitl_max_turns,
    )


def get_chat_service(
    orchestrator: ChatOrchestrator = Depends(get_chat_orchestrator),
) -> ChatService:
    return ChatService(orchestrator=orchestrator)


def get_speech_service(
    speech_to_text_client: AzureSpeechToTextClient = Depends(get_speech_to_text_client),
) -> SpeechService:
    return SpeechService(speech_to_text_client=speech_to_text_client)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(access_token_scheme),
    token_service: JwtTokenService = Depends(get_token_service),
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    token = credentials.credentials
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')

    try:
        user_id: uuid.UUID = token_service.decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token') from exc

    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid or expired token')
    return user
