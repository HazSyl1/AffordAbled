from __future__ import annotations

import re

from app.domain.ports import GuardrailAssessment, GuardrailDecision

_FINANCE_KEYWORDS = (
    'spend',
    'spent',
    'expense',
    'income',
    'transaction',
    'spending',
    'budget',
    'bill',
    'split',
    'account',
    'balance',
    'wallet',
    'rent',
    'salary',
    'paid',
    'pay',
    'refund',
    'transfer',
    'merchant',
    'category',
    'statement',
    'cashflow',
)

_HARD_OFF_TOPIC_PHRASES = (
    'write a poem',
    'tell me a joke',
    'explain machine learning',
    'python tutorial',
    'movie recommendation',
    'recipe',
    'weather forecast',
)

_CONTEXTUAL_CUES = (
    'what did i just tell you',
    'what did i say',
    'earlier',
    'previous',
    'remember',
    'recall',
)

_AMOUNT_PATTERN = re.compile(r'(₹|rs\.?|inr|\$|usd|rupees?)\s*\d+|\b\d+\s*(paise|rupees?)\b')


class KeywordSemanticGuardrail:
    async def assess(self, message: str) -> GuardrailAssessment:
        normalized_message = ' '.join(message.lower().split())

        if any(phrase in normalized_message for phrase in _HARD_OFF_TOPIC_PHRASES):
            return GuardrailAssessment(decision=GuardrailDecision.BLOCK, confidence=0.95, layer='semantic')

        if any(cue in normalized_message for cue in _CONTEXTUAL_CUES):
            return GuardrailAssessment(
                decision=GuardrailDecision.NEEDS_CLASSIFICATION,
                confidence=0.55,
                layer='semantic',
            )

        finance_hits = sum(1 for keyword in _FINANCE_KEYWORDS if keyword in normalized_message)
        if _AMOUNT_PATTERN.search(normalized_message):
            finance_hits += 2

        if finance_hits >= 2:
            return GuardrailAssessment(decision=GuardrailDecision.ALLOW, confidence=0.9, layer='semantic')
        if finance_hits == 0:
            return GuardrailAssessment(decision=GuardrailDecision.BLOCK, confidence=0.8, layer='semantic')
        return GuardrailAssessment(decision=GuardrailDecision.NEEDS_CLASSIFICATION, confidence=0.6, layer='semantic')
