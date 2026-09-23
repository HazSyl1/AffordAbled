from __future__ import annotations

import re

from app.domain.ports import GuardrailDecision

_FINANCE_KEYWORDS = (
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
    async def assess(self, message: str) -> GuardrailDecision:
        normalized_message = ' '.join(message.lower().split())

        if any(phrase in normalized_message for phrase in _HARD_OFF_TOPIC_PHRASES):
            return GuardrailDecision.BLOCK

        if any(cue in normalized_message for cue in _CONTEXTUAL_CUES):
            return GuardrailDecision.NEEDS_CLASSIFICATION

        finance_hits = sum(1 for keyword in _FINANCE_KEYWORDS if keyword in normalized_message)
        if _AMOUNT_PATTERN.search(normalized_message):
            finance_hits += 2

        if finance_hits >= 2:
            return GuardrailDecision.ALLOW
        if finance_hits == 0:
            return GuardrailDecision.BLOCK
        return GuardrailDecision.NEEDS_CLASSIFICATION
