from __future__ import annotations

from typing import Any

from app.application.services.category_service import CategoryService
from app.infrastructure.ai.agents.brains import StructuredSpecialistBrain
from app.infrastructure.ai.agents.category import CategoryToolset
from app.infrastructure.ai.agents.prompts import CATEGORY_PROMPT
from app.infrastructure.ai.agents.runtime import SpecialistRuntime


def build_category_specialist(*, llm: Any, category_service: CategoryService) -> SpecialistRuntime:
    return SpecialistRuntime(
        name="category",
        brain=StructuredSpecialistBrain(llm=llm, system_prompt=CATEGORY_PROMPT),
        tools=CategoryToolset(category_service).registry(),
        max_iterations=8,
        max_tool_retries=3,
        timeout_seconds=45,
    )
