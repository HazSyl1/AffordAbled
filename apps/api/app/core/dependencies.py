from __future__ import annotations

import logging
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
from app.application.services.export_service import ExportService
from app.application.services.image_service import ImageService
from app.application.services.profile_summary_service import ProfileSummaryService
from app.application.services.speech_service import SpeechService
from app.application.services.split_service import SplitService
from app.application.services.thread_service import ThreadService
from app.application.services.transaction_import_service import TransactionImportService
from app.application.services.transaction_service import TransactionService
from app.core.config import Settings, get_settings
from app.domain.entities import User
from app.domain.exceptions import InvalidTokenError
from app.domain.ports import ChatOrchestrator, IntentClassifier, SemanticGuardrail
from app.infrastructure.ai.agents.supervisor_graph import AgenticChatOrchestrator, AgenticSupervisorGraph
from app.infrastructure.ai.intent_classifier import KeywordIntentClassifier, LlmIntentClassifier
from app.infrastructure.ai.nemo_semantic_guardrail import NemoSemanticGuardrail
from app.infrastructure.ai.tools import CategoryTools, TransactionQueryTools
from app.infrastructure.audio.ffmpeg_audio_transcoder import FFmpegAudioTranscoder
from app.infrastructure.auth.google_oauth import GoogleAuthClient
from app.infrastructure.auth.jwt_service import JwtTokenService
from app.infrastructure.auth.password_hasher import Argon2PasswordHasher
from app.infrastructure.azure.azure_document_intelligence import AzureDocumentIntelligenceClient
from app.infrastructure.azure.azure_speech_to_text import AzureSpeechToTextClient
from app.infrastructure.database.repositories.sqlalchemy_account_repository import SqlAlchemyAccountRepository
from app.infrastructure.database.repositories.sqlalchemy_agent_correction_repository import (
    SqlAlchemyAgentCorrectionRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_category_repository import SqlAlchemyCategoryRepository
from app.infrastructure.database.repositories.sqlalchemy_chat_message_repository import SqlAlchemyChatMessageRepository
from app.infrastructure.database.repositories.sqlalchemy_chat_thread_repository import SqlAlchemyChatThreadRepository
from app.infrastructure.database.repositories.sqlalchemy_export_artifact_repository import (
    SqlAlchemyExportArtifactRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_guardrail_log_repository import (
    SqlAlchemyGuardrailLogRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_memory_repository import SqlAlchemyMemoryRepository
from app.infrastructure.database.repositories.sqlalchemy_refresh_session_repository import (
    SqlAlchemyRefreshSessionRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_split_repository import SqlAlchemySplitRepository
from app.infrastructure.database.repositories.sqlalchemy_transaction_import_repository import (
    SqlAlchemyTransactionImportRepository,
)
from app.infrastructure.database.repositories.sqlalchemy_transaction_repository import SqlAlchemyTransactionRepository
from app.infrastructure.database.repositories.sqlalchemy_user_repository import SqlAlchemyUserRepository
from app.infrastructure.database.session import get_session

logger = logging.getLogger(__name__)


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


def get_guardrail_log_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyGuardrailLogRepository:
    return SqlAlchemyGuardrailLogRepository(db)


def get_agent_correction_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyAgentCorrectionRepository:
    return SqlAlchemyAgentCorrectionRepository(db)


def get_chat_thread_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyChatThreadRepository:
    return SqlAlchemyChatThreadRepository(db)


def get_chat_message_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyChatMessageRepository:
    return SqlAlchemyChatMessageRepository(db)


def get_export_artifact_repository(db: AsyncSession = Depends(get_db)) -> SqlAlchemyExportArtifactRepository:
    return SqlAlchemyExportArtifactRepository(db)


def get_password_hasher() -> Argon2PasswordHasher:
    return Argon2PasswordHasher()


def get_token_service(settings: Settings = Depends(get_settings_dependency)) -> JwtTokenService:
    return JwtTokenService(settings)


def get_google_oauth_client(settings: Settings = Depends(get_settings_dependency)) -> GoogleAuthClient:
    return GoogleAuthClient(settings)


def get_speech_to_text_client(settings: Settings = Depends(get_settings_dependency)) -> AzureSpeechToTextClient:
    return AzureSpeechToTextClient(settings)


def get_audio_transcoder(settings: Settings = Depends(get_settings_dependency)) -> FFmpegAudioTranscoder:
    return FFmpegAudioTranscoder(
        binary=settings.ffmpeg_binary,
        timeout_seconds=settings.audio_transcode_timeout_seconds,
    )


def get_document_intelligence_client(
    settings: Settings = Depends(get_settings_dependency),
) -> AzureDocumentIntelligenceClient:
    return AzureDocumentIntelligenceClient(settings)


def get_guardrail_llm(settings: Settings = Depends(get_settings_dependency)) -> Any | None:
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


def get_semantic_guardrail(
    settings: Settings = Depends(get_settings_dependency),
    guardrail_llm: Any | None = Depends(get_guardrail_llm),
) -> SemanticGuardrail:
    if settings.chat_guardrail_provider != "nemo":
        logger.warning(
            "CHAT_GUARDRAIL_PROVIDER=%s is unsupported. Using NeMo guardrails.",
            settings.chat_guardrail_provider,
        )

    return NemoSemanticGuardrail(
        config_path=settings.nemo_guardrails_config_path,
        llm=guardrail_llm,
        block_token=settings.nemo_guardrails_block_token,
        allow_token=settings.nemo_guardrails_allow_token,
        needs_classification_token=settings.nemo_guardrails_needs_classification_token,
    )


def get_intent_classifier(
    settings: Settings = Depends(get_settings_dependency),
    intent_llm: Any | None = Depends(get_guardrail_llm),
) -> IntentClassifier:
    keyword_classifier = KeywordIntentClassifier()
    if settings.chat_intent_provider == "keyword":
        return keyword_classifier

    if intent_llm is None:
        logger.warning("LLM intent classification requested but Azure OpenAI is unavailable; using keyword fallback.")
        return keyword_classifier

    return LlmIntentClassifier(intent_llm, fallback=keyword_classifier)


def get_langgraph_checkpointer(request: Request) -> Any:
    checkpointer = getattr(request.app.state, "langgraph_checkpointer", None)
    if checkpointer is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Chat runtime is not initialized")
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
    db: AsyncSession = Depends(get_db),
) -> TransactionService:
    return TransactionService(
        transaction_repository=transaction_repository,
        account_repository=account_repository,
        category_repository=category_repository,
        split_repository=SqlAlchemySplitRepository(db),
        memory_event_writer=SqlAlchemyMemoryRepository(db),
    )


def get_thread_service(
    chat_thread_repository: SqlAlchemyChatThreadRepository = Depends(get_chat_thread_repository),
    chat_message_repository: SqlAlchemyChatMessageRepository = Depends(get_chat_message_repository),
) -> ThreadService:
    return ThreadService(
        chat_thread_repository=chat_thread_repository,
        chat_message_repository=chat_message_repository,
    )


def get_export_service(
    export_artifact_repository: SqlAlchemyExportArtifactRepository = Depends(get_export_artifact_repository),
    transaction_repository: SqlAlchemyTransactionRepository = Depends(get_transaction_repository),
    account_repository: SqlAlchemyAccountRepository = Depends(get_account_repository),
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
    settings: Settings = Depends(get_settings_dependency),
) -> ExportService:
    return ExportService(
        export_artifact_repository=export_artifact_repository,
        transaction_repository=transaction_repository,
        account_repository=account_repository,
        category_repository=category_repository,
        signing_key=settings.jwt_secret_key,
    )


def get_transaction_import_service(
    db: AsyncSession = Depends(get_db),
    transaction_repository: SqlAlchemyTransactionRepository = Depends(get_transaction_repository),
    account_repository: SqlAlchemyAccountRepository = Depends(get_account_repository),
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
) -> TransactionImportService:
    return TransactionImportService(
        account_repository=account_repository,
        category_repository=category_repository,
        transaction_repository=transaction_repository,
        import_repository=SqlAlchemyTransactionImportRepository(db),
    )


def get_category_tools(
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
) -> CategoryTools:
    return CategoryTools(category_repository=category_repository)


def get_transaction_query_tools(
    transaction_repository: SqlAlchemyTransactionRepository = Depends(get_transaction_repository),
    account_repository: SqlAlchemyAccountRepository = Depends(get_account_repository),
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
) -> TransactionQueryTools:
    return TransactionQueryTools(
        transaction_repository=transaction_repository,
        account_repository=account_repository,
        category_repository=category_repository,
    )


def get_chat_orchestrator(
    db: AsyncSession = Depends(get_db),
    checkpointer: Any = Depends(get_langgraph_checkpointer),
    settings: Settings = Depends(get_settings_dependency),
    semantic_guardrail: SemanticGuardrail = Depends(get_semantic_guardrail),
    intent_classifier: IntentClassifier = Depends(get_intent_classifier),
    transaction_service: TransactionService = Depends(get_transaction_service),
    account_repository: SqlAlchemyAccountRepository = Depends(get_account_repository),
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
    category_tools: CategoryTools = Depends(get_category_tools),
    transaction_query_tools: TransactionQueryTools = Depends(get_transaction_query_tools),
    export_service: ExportService = Depends(get_export_service),
    extraction_llm: Any | None = Depends(get_transaction_extraction_llm),
) -> ChatOrchestrator:
    del intent_classifier, category_tools, settings
    if extraction_llm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Agentic chat requires a configured LLM deployment.',
        )
    return AgenticChatOrchestrator(
        AgenticSupervisorGraph(
            checkpointer=checkpointer,
            llm=extraction_llm,
            guardrail=semantic_guardrail,
            category_service=CategoryService(category_repository=category_repository),
            account_service=AccountService(account_repository=account_repository),
            transaction_service=transaction_service,
            split_service=SplitService(
                SqlAlchemySplitRepository(db), SqlAlchemyMemoryRepository(db),
            ),
            query_tools=transaction_query_tools,
            export_service=export_service,
            memory_repository=SqlAlchemyMemoryRepository(db),
            db_session=db,
        )
    )


def get_profile_summary_service(
    transaction_repository: SqlAlchemyTransactionRepository = Depends(get_transaction_repository),
    category_repository: SqlAlchemyCategoryRepository = Depends(get_category_repository),
) -> ProfileSummaryService:
    return ProfileSummaryService(
        transaction_repository=transaction_repository,
        category_repository=category_repository,
    )


def get_chat_service(
    orchestrator: ChatOrchestrator = Depends(get_chat_orchestrator),
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
    chat_thread_repository: SqlAlchemyChatThreadRepository = Depends(get_chat_thread_repository),
    chat_message_repository: SqlAlchemyChatMessageRepository = Depends(get_chat_message_repository),
    agent_correction_repository: SqlAlchemyAgentCorrectionRepository = Depends(get_agent_correction_repository),
    guardrail_log_repository: SqlAlchemyGuardrailLogRepository = Depends(get_guardrail_log_repository),
) -> ChatService:
    return ChatService(
        orchestrator=orchestrator,
        user_repository=user_repository,
        chat_thread_repository=chat_thread_repository,
        chat_message_repository=chat_message_repository,
        agent_correction_repository=agent_correction_repository,
        guardrail_log_repository=guardrail_log_repository,
    )


def get_speech_service(
    speech_to_text_client: AzureSpeechToTextClient = Depends(get_speech_to_text_client),
    audio_transcoder: FFmpegAudioTranscoder = Depends(get_audio_transcoder),
) -> SpeechService:
    return SpeechService(
        speech_to_text_client=speech_to_text_client,
        audio_transcoder=audio_transcoder,
    )


def get_image_service(
    document_intelligence_client: AzureDocumentIntelligenceClient = Depends(get_document_intelligence_client),
) -> ImageService:
    return ImageService(image_to_text_client=document_intelligence_client)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(access_token_scheme),
    token_service: JwtTokenService = Depends(get_token_service),
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token = credentials.credentials
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        user_id: uuid.UUID = token_service.decode_access_token(token)
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user
