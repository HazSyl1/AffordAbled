# LangGraph Requirements and Audit

## Product contract

1. Every chat request passes guardrails and authenticated user context before reasoning.
2. A tool-free Supervisor selects one specialist at a time: Category, Transaction, Account, Analytics, or Formatting.
3. A specialist is an LLM brain with only its domain's capability-scoped tools. It decides whether to call a tool, delegate, ask for input, or finish.
4. The Supervisor receives only typed specialist results and may re-route or return a final answer; it never invokes domain tools.
5. Tool handlers validate input and enforce ownership from server-supplied `user_id`; the model never supplies authority.
6. Specialists return only `SpecialistResult(status, summary, data, actions_taken, errors)` to the Supervisor.
7. On interrupt/resume, LangGraph persists the original task, specialist state, full bounded history, and the new user answer. The answer must extend—not replace—the original task.
8. Missing required details cause a focused interrupt. Only destructive deletion requires confirmation.
9. A mutation is successful only after its handler returns a successful observation. A brain must not finish a requested mutation without attempting all required operations or reporting a verified failure/partial result.
10. Multi-item requests require one scoped tool call per item unless an explicitly supported batch tool is selected.
11. Transaction may delegate extraction to its nested, tool-free Extraction sub-agent. Analytics is read-only and does not interrupt. Formatting has no tools.
12. Tool failures are observations; retries, specialist iteration/time limits, and Supervisor reroute limits bound execution.
13. Each agent has independent prompt/model configuration, structured logs, and tests for scope, resume, retries, limits, handoffs, and API behavior.

## Required category behavior

For `Create 2 categories: Food and Groceries`:

1. Category brain identifies two requested category names and a missing enum value.
2. It interrupts once: `Should Food and Groceries be expense or income categories?`
3. If the user replies `expense`, it resumes with the original task and answer.
4. It calls `create_category(Food, expense)` and observes success.
5. It calls `create_category(Groceries, expense)` and observes success.
6. It finishes only after both observations, or returns a partial/failed structured result with the exact failed item and error.
7. Formatting turns the verified result into the final response.

## Current audit

| Requirement | Status | Evidence / gap |
| --- | --- | --- |
| Guardrails, auth, tool-free Supervisor | Implemented | Supervisor has no tool registry; toolsets use handoff user ID. |
| Scoped Category/Transaction/Account/Analytics/Formatting tools | Implemented | Per-specialist registries in `agents/supervisor_graph.py`. |
| Typed handoff and result contracts | Implemented | `agents/contracts.py`. |
| Checkpoint interrupt/resume | Implemented, tested | `task_request`, history, `latest_user_reply`, and `specialist_messages` persist across the attached subgraph interrupt. |
| Native ToolNode specialist resume | Implemented, tested | Each specialist is an attached `StateGraph` with bound tools, `ToolNode`, `tools_condition`, and checkpointed `specialist_messages`. |
| Delete-only confirmation | Implemented | Runtime destructive-tool policy. |
| Bounded retries, timeouts, reroutes | Implemented | Per-tool retries/timeouts, per-specialist iteration cap, and `_MAX_REROUTES`. |
| Transaction extraction delegation | Implemented | Nested Extraction agent registered as the Transaction delegate. |
| Category multi-create after type clarification | Implemented, integration-tested | API test pauses once, resumes, and verifies two persisted category mutations. |
| Analytics no-interrupt policy | Implemented | The Analytics runtime has no `ask_user` tool. |
| Per-agent model configuration | Constructor supports per-agent mapping | Dependency currently supplies one shared configured model. |
| Structured tracing | Partial | Agent/tool/action/latency logging exists; safe input/output identifiers and final status need fuller tracing. |
| Live-model end-to-end verification | Pending manual check | The mocked API regression and full backend suite pass; Azure/model behavior must still be exercised manually. |

## Latest implementation note

The production graph no longer uses a generic specialist-action dispatcher. Each specialist follows native LangGraph
tool calling: `llm.bind_tools(...) -> agent -> ToolNode -> agent`, inside an attached checkpointed subgraph. A user
reply therefore resumes the same pending tool loop with its prior ToolMessages intact.
