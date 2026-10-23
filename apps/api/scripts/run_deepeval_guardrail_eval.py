from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

GUARDRAIL_CASES = (
    ('off_topic_poem', 'Write a poem about dinosaurs', 'BLOCK'),
    ('budget_question', 'Can you check my budget for this month?', 'ALLOW'),
    ('record_groceries', 'I paid ₹500 on groceries today', 'ALLOW'),
)

# DeepEval validates some Azure URL env vars at import time.
os.environ.setdefault('AZURE_OPENAI_ENDPOINT', 'https://example.openai.azure.com/')
os.environ.setdefault('AZURE_OPENAI_API_KEY', 'test-key')


def main() -> int:
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
        if decision.decision == GuardrailDecision.BLOCK:
            return 'BLOCK'

        if decision.decision == GuardrailDecision.NEEDS_CLASSIFICATION:
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

    passed = 0
    for name, prompt, expected_label in GUARDRAIL_CASES:
        try:
            run_case(prompt, expected_label)
        except AssertionError as exc:
            print(f'FAIL {name}: {exc}')
        else:
            print(f'PASS {name}')
            passed += 1
    failed = len(GUARDRAIL_CASES) - passed
    print(f'GUARDRAIL_SUMMARY passed={passed} failed={failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
