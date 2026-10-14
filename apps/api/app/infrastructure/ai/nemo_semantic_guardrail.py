from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.domain.ports import GuardrailAssessment, GuardrailDecision

try:
    from nemoguardrails import RailsConfig
    from nemoguardrails.integrations.langchain.runnable_rails import RunnableRails
except ImportError:
    RailsConfig = None
    RunnableRails = None

logger = logging.getLogger(__name__)


class NemoSemanticGuardrail:
    def __init__(
        self,
        *,
        config_path: str,
        llm: Any | None = None,
        rails_client: Any | None = None,
        block_token: str = '__BLOCK__',
        allow_token: str = '__ALLOW__',
        needs_classification_token: str = '__NEEDS_CLASSIFICATION__',
    ) -> None:
        self._block_token = block_token.strip().upper()
        self._allow_token = allow_token.strip().upper()
        self._needs_classification_token = needs_classification_token.strip().upper()
        self._rails = rails_client or self._initialize_rails(config_path=config_path, llm=llm)

    async def assess(self, message: str) -> GuardrailAssessment:
        normalized_message = message.strip()
        if not normalized_message:
            return GuardrailAssessment(decision=GuardrailDecision.BLOCK, confidence=1.0, layer='semantic')

        if self._rails is None:
            logger.warning('NeMo guardrails unavailable; routing to intent classification fallback path.')
            return GuardrailAssessment(
                decision=GuardrailDecision.NEEDS_CLASSIFICATION,
                confidence=0.5,
                layer='semantic',
            )

        try:
            raw_response = await self._invoke_rails(normalized_message)
        except Exception:
            logger.exception('NeMo guardrail invocation failed. Routing to intent classification fallback path.')
            return GuardrailAssessment(
                decision=GuardrailDecision.NEEDS_CLASSIFICATION,
                confidence=0.5,
                layer='semantic',
            )

        output_token = self._extract_output_token(raw_response)
        if output_token == self._allow_token:
            return GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=0.9, layer='semantic')
        if output_token == self._needs_classification_token:
            return GuardrailAssessment(
                decision=GuardrailDecision.NEEDS_CLASSIFICATION,
                confidence=0.6,
                layer='semantic',
            )
        if output_token == self._block_token:
            return GuardrailAssessment(decision=GuardrailDecision.BLOCK, confidence=0.9, layer='semantic')

        logger.warning(
            'NeMo guardrails returned unknown token `%s`; routing to intent classification fallback path.',
            output_token,
        )
        return GuardrailAssessment(decision=GuardrailDecision.NEEDS_CLASSIFICATION, confidence=0.5, layer='semantic')

    def _initialize_rails(self, *, config_path: str, llm: Any | None) -> Any | None:
        if RunnableRails is None or RailsConfig is None:
            logger.warning('nemoguardrails package is not installed. Guardrail will fail closed.')
            return None

        resolved_path = self._resolve_config_path(config_path)
        if not resolved_path.exists():
            logger.warning('NeMo config path `%s` does not exist. Guardrail will fail closed.', resolved_path)
            return None

        try:
            rails_config = RailsConfig.from_path(str(resolved_path))
            if llm is not None:
                try:
                    return RunnableRails(config=rails_config, llm=llm, passthrough=False)
                except TypeError:
                    return RunnableRails(config=rails_config, passthrough=False)

            return RunnableRails(config=rails_config, passthrough=False)
        except Exception:
            logger.exception('Failed to initialize NeMo guardrails from `%s`.', resolved_path)
            return None

    async def _invoke_rails(self, message: str) -> Any:
        payload = {'input': message}
        if hasattr(self._rails, 'ainvoke'):
            return await self._rails.ainvoke(payload)

        return await asyncio.to_thread(self._rails.invoke, payload)

    def _extract_output_token(self, payload: Any) -> str:
        text = self._extract_output_text(payload)
        return text.splitlines()[0].strip().upper() if text else ''

    @staticmethod
    def _extract_output_text(payload: Any) -> str:
        if payload is None:
            return ''

        if isinstance(payload, str):
            return payload

        if isinstance(payload, dict):
            for key in ('output', 'content', 'response'):
                value = payload.get(key)
                if isinstance(value, str):
                    return value

            messages = payload.get('messages')
            if isinstance(messages, list) and messages:
                last_message = messages[-1]
                if isinstance(last_message, dict):
                    content = last_message.get('content')
                    if isinstance(content, str):
                        return content

            return ''

        content_value = getattr(payload, 'content', None)
        if isinstance(content_value, str):
            return content_value

        return str(payload)

    @staticmethod
    def _resolve_config_path(config_path: str) -> Path:
        path = Path(config_path)
        if path.is_absolute():
            return path

        cwd_candidate = Path.cwd() / path
        if cwd_candidate.exists():
            return cwd_candidate

        api_root = Path(__file__).resolve().parents[3]
        return api_root / path
