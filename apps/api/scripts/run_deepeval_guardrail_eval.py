from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# DeepEval validates some Azure URL env vars at import time.
os.environ.setdefault('AZURE_OPENAI_ENDPOINT', 'https://example.openai.azure.com/')
os.environ.setdefault('AZURE_OPENAI_API_KEY', 'test-key')


def main() -> None:
    api_root = Path(__file__).resolve().parents[1]
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    from deepeval import assert_test
    from deepeval.metrics import BaseMetric
    from deepeval.test_case import LLMTestCase

    from app.domain.ports import DetectedIntent, GuardrailDecision
    from app.infrastructure.ai.intent_classifier import KeywordIntentClassifier
    from app.infrastructure.ai.semantic_guardrail import KeywordSemanticGuardrail

    class ExactOutputMetric(BaseMetric):
        def __init__(self, expected_output: str) -> None:
            self.expected_output = expected_output
            self.threshold = 1.0
            self.score = 0.0
            self.reason = ''

        def measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
            self.score = 1.0 if test_case.actual_output == self.expected_output else 0.0
            self.reason = f'expected={self.expected_output}, actual={test_case.actual_output}'
            self.success = self.score >= self.threshold
            return self.score

        async def a_measure(self, test_case: LLMTestCase, *args, **kwargs) -> float:
            return self.measure(test_case, *args, **kwargs)

        @property
        def __name__(self) -> str:
            return 'ExactOutputMetric'

    async def evaluate_prompt(prompt: str) -> str:
        guardrail = KeywordSemanticGuardrail()
        classifier = KeywordIntentClassifier()

        decision = await guardrail.assess(prompt)
        if decision == GuardrailDecision.BLOCK:
            return 'BLOCK'

        if decision == GuardrailDecision.NEEDS_CLASSIFICATION:
            intent = await classifier.classify(prompt)
            if intent == DetectedIntent.OFF_TOPIC:
                return 'BLOCK'

        return 'ALLOW'

    def run_case(prompt: str, expected_label: str) -> None:
        actual_label = asyncio.run(evaluate_prompt(prompt))
        test_case = LLMTestCase(
            input=prompt,
            actual_output=actual_label,
            expected_output=expected_label,
            name=f'guardrail::{prompt[:24]}',
        )
        metric = ExactOutputMetric(expected_output=expected_label)
        assert_test(test_case=test_case, metrics=[metric], run_async=False)

    print('Running DeepEval guardrail checks...')

    run_case('Write a poem about my expenses', 'BLOCK')
    run_case('Can you check my budget for this month?', 'ALLOW')
    run_case('I paid ₹500 on groceries today', 'ALLOW')

    print('DeepEval guardrail checks passed.')


if __name__ == '__main__':
    main()
