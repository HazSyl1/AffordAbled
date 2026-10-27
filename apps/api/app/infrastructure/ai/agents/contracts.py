from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

SpecialistName = Literal["category", "transaction", "split", "account", "analytics", "export", "formatting"]
ResultStatus = Literal["success", "partial", "failed", "needs_input"]
TaskStatus = Literal["queued", "running", "waiting_for_user", "completed", "failed"]


class TaskContract(BaseModel):
    """Durable, machine-verifiable work item stored in LangGraph state."""

    id: str = Field(min_length=1, max_length=80)
    original_text: str = Field(min_length=1, max_length=4_000)
    summary: str = Field(min_length=1, max_length=4_000)
    intent: str = Field(min_length=1, max_length=120)
    specialist: SpecialistName | None = None
    required_tools: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    completion_mode: Literal["all", "any"] = "all"
    status: TaskStatus = "queued"
    result_summary: str | None = Field(default=None, max_length=20_000)


class VerifiedTransactionReference(BaseModel):
    """A transaction ID captured from a successful tool result, never model prose."""

    id: uuid.UUID
    source_request: str = Field(min_length=1, max_length=4_000)
    amount_paise: int = Field(gt=0)
    merchant: str | None = None
    task_id: str | None = None


class HandoffContext(BaseModel):
    """Trusted context supplied by the supervisor to one specialist."""

    user_id: uuid.UUID
    owner_name: str | None = Field(default=None, max_length=120)
    request: str = Field(min_length=1, max_length=4_000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    timezone: str = "UTC"
    current_datetime: str | None = Field(
        default=None,
        description="Trusted current ISO datetime in the user's timezone, supplied by application code.",
    )
    constraints: dict[str, Any] = Field(default_factory=dict)


class ToolAction(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class SpecialistDecision(BaseModel):
    """The only control output a specialist brain may produce."""

    action: Literal["call_tool", "ask_user", "delegate", "finish"]
    tool: ToolAction | None = None
    question: str | None = Field(default=None, max_length=600)
    memory_signal: Literal[
        "category_mapping", "account_mapping", "preference", "split_preference",
    ] | None = Field(
        default=None,
        description=(
            "Set only for a clarification that captures a reusable preference; this queues post-transaction review."
        ),
    )
    memory_subject_hint: str | None = Field(default=None, max_length=120)
    delegate_to: str | None = Field(default=None, max_length=80)
    summary: str = Field(default="", max_length=20_000)


class ToolObservation(BaseModel):
    task_id: str | None = None
    tool: str
    ok: bool
    arguments: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=600)


class SpecialistResult(BaseModel):
    """Machine-readable result returned by a specialist to the supervisor."""

    specialist: SpecialistName
    task_id: str | None = None
    status: ResultStatus
    summary: str = Field(max_length=20_000)
    data: dict[str, Any] = Field(default_factory=dict)
    actions_taken: list[dict[str, Any]] = Field(default_factory=list)
    tool_observations: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SupervisorDecision(BaseModel):
    action: Literal["route", "finish", "refuse"]
    specialist: SpecialistName | None = None
    handoff: dict[str, Any] = Field(default_factory=dict)
    response: str | None = Field(default=None, max_length=20_000)
    tasks: list[str] | None = Field(
        default=None, description="Ordered user-requested tasks, supplied on the first decision."
    )
