from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_env: str = 'development'
    log_level: str = 'INFO'

    database_url: str = 'postgresql+asyncpg://postgres:postgres@localhost:5432/affordable'
    redis_url: str = 'redis://localhost:6379/0'
    celery_broker_url: str = 'redis://localhost:6379/0'

    jwt_secret_key: str = 'dev-only-change-me'
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    google_client_id: str = ''
    google_client_secret: str = ''
    google_redirect_uri: str = ''

    # Comma-separated list, e.g. "http://localhost:5173,http://localhost:3000"
    cors_allowed_origins: str = 'http://localhost:5173'

    azure_storage_account_name: str = ''
    azure_storage_container_name: str = ''
    azure_document_intelligence_endpoint: str = ''
    azure_document_intelligence_key: str = ''
    azure_speech_key: str = ''
    azure_speech_region: str = 'centralindia'
    ffmpeg_binary: str = 'ffmpeg'
    audio_transcode_timeout_seconds: int = 15
    audio_transcoder_required: bool = False

    azure_openai_endpoint: str = ''
    azure_openai_api_key: str = ''
    azure_openai_deployment: str = ''
    azure_openai_api_version: str = '2024-10-21'
    azure_openai_extraction_deployment: str = ''

    chat_proposal_confidence_threshold: int = 80
    chat_hitl_max_turns: int = 5
    chat_deterministic_transaction_first: bool = False
    chat_guardrail_provider: Literal['nemo'] = 'nemo'
    chat_intent_provider: Literal['keyword', 'llm'] = 'llm'
    nemo_guardrails_config_path: str = 'app/infrastructure/ai/nemo_guardrails'
    nemo_guardrails_block_token: str = '__BLOCK__'
    nemo_guardrails_allow_token: str = '__ALLOW__'
    nemo_guardrails_needs_classification_token: str = '__NEEDS_CLASSIFICATION__'
    langgraph_checkpointer_mode: Literal['auto', 'postgres', 'memory'] = 'auto'
    langgraph_checkpointer_startup_timeout_seconds: int = 8
    retention_cleanup_enabled: bool = False
    retention_cleanup_interval_minutes: int = 60
    chat_message_retention_days: int = 180
    memory_outbox_enabled: bool = True
    memory_outbox_poll_interval_seconds: int = 5
    memory_outbox_batch_size: int = 20
    chat_turn_worker_enabled: bool = True
    chat_turn_poll_interval_seconds: int = 2
    chat_turn_stale_after_seconds: int = 600
    chat_turn_max_attempts: int = 3
    chat_turn_retention_days: int = 7
    free_chat_turns_per_day: int = 50
    free_ai_transactions_per_day: int = 20
    subscribed_chat_turns_per_day: int = 250
    subscribed_ai_transactions_per_day: int = 100
    free_media_requests_per_day: int = 30
    subscribed_media_requests_per_day: int = 150
    recurring_transaction_worker_enabled: bool = True
    recurring_transaction_stale_after_seconds: int = 300
    recurring_transaction_max_attempts: int = 8
    recurring_transaction_batch_size: int = 50
    recurring_transaction_max_sleep_seconds: int = 300

    sms_enabled: bool = False
    sms_provider: Literal['azure_acs'] = 'azure_acs'
    acs_connection_string: str = ''
    acs_sender_number: str = ''
    notification_cooldown_hours: int = 6
    max_notifications_per_split: int = 3
    max_sms_per_user_per_day: int = 10
    sms_worker_enabled: bool = True
    sms_worker_batch_size: int = 20
    sms_worker_poll_seconds: int = 5
    sms_processing_stale_seconds: int = 120
    sms_send_timeout_seconds: int = 15
    # Public URLs used inside reminder emails. The pay page must be reachable by recipients' phones.
    public_api_base_url: str = ''
    public_web_url: str = ''
    email_enabled: bool = False
    email_provider: Literal['azure_acs'] = 'azure_acs'
    email_sender_address: str = ''
    email_worker_enabled: bool = True
    email_worker_batch_size: int = 20
    email_worker_poll_seconds: int = 5
    email_processing_stale_seconds: int = 120
    email_send_timeout_seconds: int = 30

    langsmith_api_key: str = ''
    langsmith_tracing: bool = False
    langsmith_project: str = 'affordabled-dev'

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(',') if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
