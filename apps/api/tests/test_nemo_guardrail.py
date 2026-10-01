from __future__ import annotations

from app.domain.ports import GuardrailDecision
from app.infrastructure.ai.nemo_semantic_guardrail import NemoSemanticGuardrail


class StubRails:
    def __init__(self, output: object) -> None:
        self.output = output

    def invoke(self, payload: dict[str, str]) -> object:
        _ = payload
        return self.output


class ErrorRails:
    def invoke(self, payload: dict[str, str]) -> object:
        _ = payload
        raise RuntimeError('guardrail failure')


async def test_nemo_guardrail_maps_allow_token() -> None:
    guardrail = NemoSemanticGuardrail(
        config_path='app/infrastructure/ai/nemo_guardrails',
        rails_client=StubRails({'output': '__ALLOW__'}),
    )

    assessment = await guardrail.assess('Log INR 500 transaction')

    assert assessment.decision == GuardrailDecision.ALLOW


async def test_nemo_guardrail_maps_block_token() -> None:
    guardrail = NemoSemanticGuardrail(
        config_path='app/infrastructure/ai/nemo_guardrails',
        rails_client=StubRails({'output': '__BLOCK__'}),
    )

    assessment = await guardrail.assess('Give me stock tips')

    assert assessment.decision == GuardrailDecision.BLOCK


async def test_nemo_guardrail_maps_needs_classification_token() -> None:
    guardrail = NemoSemanticGuardrail(
        config_path='app/infrastructure/ai/nemo_guardrails',
        rails_client=StubRails({'output': '__NEEDS_CLASSIFICATION__'}),
    )

    assessment = await guardrail.assess('Help me improve money habits')

    assert assessment.decision == GuardrailDecision.NEEDS_CLASSIFICATION


async def test_nemo_guardrail_uses_classification_fallback_for_unknown_output() -> None:
    guardrail = NemoSemanticGuardrail(
        config_path='app/infrastructure/ai/nemo_guardrails',
        rails_client=StubRails({'output': 'UNEXPECTED'}),
    )

    assessment = await guardrail.assess('Can you check my budget?')

    assert assessment.decision == GuardrailDecision.NEEDS_CLASSIFICATION


async def test_nemo_guardrail_uses_classification_fallback_when_rails_fails() -> None:
    guardrail = NemoSemanticGuardrail(
        config_path='app/infrastructure/ai/nemo_guardrails',
        rails_client=ErrorRails(),
    )

    assessment = await guardrail.assess('Can you check my budget?')

    assert assessment.decision == GuardrailDecision.NEEDS_CLASSIFICATION
