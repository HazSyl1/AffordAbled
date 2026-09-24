from __future__ import annotations

from app.domain.ports import DetectedIntent

_INTENT_KEYWORDS: dict[DetectedIntent, tuple[str, ...]] = {
    DetectedIntent.LOG_TRANSACTION: (
        'spent',
        'expense',
        'paid',
        'payment',
        'income',
        'salary',
        'refund',
        'transfer',
        'transaction',
    ),
    DetectedIntent.QUERY_SPENDING: (
        'spending',
        'budget',
        'trend',
        'monthly',
        'weekly',
        'summary',
        'analytics',
    ),
    DetectedIntent.SPLIT_REQUEST: (
        'split',
        'shared',
        'friends',
        'owe',
        'owed',
        'divide',
    ),
    DetectedIntent.GENERATE_REPORT: (
        'report',
        'export',
        'pdf',
        'excel',
        'csv',
        'statement',
    ),
    DetectedIntent.ACCOUNT_QUERY: (
        'account',
        'balance',
        'wallet',
        'card',
        'bank',
    ),
    DetectedIntent.MEMORY_RELATED: (
        'remember',
        'recall',
        'earlier',
        'previous',
        'history',
        'what did i just tell you',
        'what did i say',
    ),
}

_OFF_TOPIC_MARKERS = (
    'poem',
    'joke',
    'machine learning',
    'movie',
    'recipe',
    'weather',
)


class KeywordIntentClassifier:
    async def classify(self, message: str) -> DetectedIntent:
        normalized_message = ' '.join(message.lower().split())

        if any(marker in normalized_message for marker in _OFF_TOPIC_MARKERS):
            return DetectedIntent.OFF_TOPIC

        for intent in (
            DetectedIntent.LOG_TRANSACTION,
            DetectedIntent.QUERY_SPENDING,
            DetectedIntent.SPLIT_REQUEST,
            DetectedIntent.GENERATE_REPORT,
            DetectedIntent.ACCOUNT_QUERY,
            DetectedIntent.MEMORY_RELATED,
        ):
            if any(keyword in normalized_message for keyword in _INTENT_KEYWORDS[intent]):
                return intent

        return DetectedIntent.OFF_TOPIC
