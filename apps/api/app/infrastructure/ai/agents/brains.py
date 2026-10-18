from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import Field, create_model

from app.infrastructure.ai.agents.contracts import (
    HandoffContext,
    SpecialistDecision,
    SupervisorDecision,
    ToolObservation,
)


def scoped_specialist_decision_schema(tool_names: set[str]) -> type[SpecialistDecision]:
    """Build a decision contract whose tool name is limited to real capabilities.

    The registry remains the authorization boundary at execution time. This
    schema gives the LLM the same truthful capability list at decision time so
    it cannot select a made-up tool name and mistake the resulting rejection
    for a permission failure.
    """
    if not tool_names:
        return SpecialistDecision

    allowed_name = Literal.__getitem__(tuple(sorted(tool_names)))
    scoped_tool = create_model(
        "ScopedToolAction",
        name=(allowed_name, Field(description="One of this specialist's permitted tool names.")),
        arguments=(dict[str, Any], Field(default_factory=dict)),
    )
    return create_model("ScopedSpecialistDecision", __base__=SpecialistDecision, tool=(scoped_tool | None, None))


class StructuredSpecialistBrain:
    """LLM adapter whose output is constrained to the specialist action contract."""

    def __init__(self, *, llm: Any, system_prompt: str, tool_names: set[str] | None = None) -> None:
        prompt = ChatPromptTemplate.from_messages(
            [("system", system_prompt), ("human", "Handoff: {handoff}\nObservations: {observations}")]
        )
        # Tool/function calling permits the typed contract's dynamic tool
        # arguments. Azure's strict JSON-schema response format rejects a
        # free-form object even when Pydantic validates it after parsing.
        self._chain = prompt | llm.with_structured_output(
            scoped_specialist_decision_schema(tool_names or set()), method="function_calling"
        )

    async def decide(self, context: HandoffContext, observations: list[ToolObservation]) -> SpecialistDecision:
        return await self._chain.ainvoke(
            {
                "handoff": context.model_dump_json(),
                "observations": json.dumps([item.model_dump() for item in observations], ensure_ascii=False),
            }
        )


class StructuredSupervisorBrain:
    def __init__(self, *, llm: Any, system_prompt: str) -> None:
        prompt = ChatPromptTemplate.from_messages(
            [("system", system_prompt), ("human", "Context: {context}\nResults: {results}")]
        )
        # `handoff` is intentionally a dynamic, typed context payload. Use
        # function calling rather than strict response_format JSON schema.
        self._chain = prompt | llm.with_structured_output(SupervisorDecision, method="function_calling")

    async def decide(
        self,
        context: HandoffContext,
        results: list[dict[str, Any]],
    ) -> SupervisorDecision:
        return await self._chain.ainvoke(
            {"context": context.model_dump_json(), "results": json.dumps(results, ensure_ascii=False)}
        )
