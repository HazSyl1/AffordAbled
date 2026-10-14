from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.core.dependencies import get_intent_classifier
from app.domain.ports import DetectedIntent
from app.infrastructure.ai.intent_classifier import (
    IntentClassificationOutput,
    KeywordIntentClassifier,
    LlmIntentClassifier,
)


class StubStructuredIntentModel:
    def __init__(self, result: IntentClassificationOutput | Exception) -> None:
        self.result = result
        self.schema: type[IntentClassificationOutput] | None = None
        self.prompt_text = ''

    def with_structured_output(self, schema: type[IntentClassificationOutput]) -> StubStructuredIntentModel:
        self.schema = schema
        return self

    async def ainvoke(self, prompt_value: Any) -> IntentClassificationOutput:
        self.prompt_text = prompt_value.to_string()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_llm_intent_classifier_reads_receipt_instruction_not_receipt_total_words() -> None:
    model = StubStructuredIntentModel(
        IntentClassificationOutput(intent=DetectedIntent.LOG_TRANSACTION, confidence=0.98)
    )
    classifier = LlmIntentClassifier(model)
    message = (
        'Help me log the transaction from this receipt. OCR: Sub Total INR 1,035; '
        'Total INR 1,139; Invoice Date 20-May-18.'
    )

    intent = await classifier.classify(message)

    assert intent == DetectedIntent.LOG_TRANSACTION
    assert model.schema is IntentClassificationOutput
    assert 'Help me log the transaction' in model.prompt_text
    assert 'Sub Total INR 1,035' in model.prompt_text


@pytest.mark.asyncio
async def test_llm_intent_classifier_uses_keyword_fallback_for_low_confidence() -> None:
    model = StubStructuredIntentModel(
        IntentClassificationOutput(intent=DetectedIntent.OFF_TOPIC, confidence=0.2)
    )
    classifier = LlmIntentClassifier(model)

    intent = await classifier.classify('How is my monthly budget looking?')

    assert intent == DetectedIntent.QUERY_SPENDING


@pytest.mark.asyncio
async def test_llm_intent_classifier_uses_keyword_fallback_when_model_fails() -> None:
    model = StubStructuredIntentModel(RuntimeError('model unavailable'))
    classifier = LlmIntentClassifier(model)

    intent = await classifier.classify('I spent INR 500 on lunch')

    assert intent == DetectedIntent.LOG_TRANSACTION


def test_intent_classifier_dependency_selects_llm_when_configured() -> None:
    model = StubStructuredIntentModel(
        IntentClassificationOutput(intent=DetectedIntent.LOG_TRANSACTION, confidence=0.9)
    )

    classifier = get_intent_classifier(settings=Settings(chat_intent_provider='llm'), intent_llm=model)

    assert isinstance(classifier, LlmIntentClassifier)


def test_intent_classifier_dependency_uses_keyword_when_explicitly_configured() -> None:
    model = StubStructuredIntentModel(
        IntentClassificationOutput(intent=DetectedIntent.LOG_TRANSACTION, confidence=0.9)
    )

    classifier = get_intent_classifier(settings=Settings(chat_intent_provider='keyword'), intent_llm=model)

    assert isinstance(classifier, KeywordIntentClassifier)
