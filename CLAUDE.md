# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Backend (`apps/api`, Python 3.13, venv at `apps/api/.venv`):

```bash
# Windows: use the venv's own interpreter directly if `source`/activation isn't available
.venv/Scripts/python.exe -m pytest -q                       # full suite
.venv/Scripts/python.exe -m pytest -q tests/test_chat.py -k 'multirow_transaction'   # focused by keyword
.venv/Scripts/python.exe -m ruff check .
alembic current                                              # verify actual head before assuming a revision id
uvicorn app.main:app --reload
```

Frontend (`apps/web`):

```bash
npm run dev
npm run lint
npm run build     # tsc + vite build; existing >500kB chunk warning is non-blocking
```

PowerShell note: chain commands with `;`, not `&&`.

## Architecture

### Backend: onion layering

`apps/api/app/` is strict onion architecture: `presentation → application → domain`, with `infrastructure` implementing interfaces declared in `domain`/`application` and wired in from outside. `domain` has no framework imports.

- `domain/` — entities, `ports.py` (protocols for `IntentClassifier`, `SemanticGuardrail`, `ChatTurnResult`, `PendingTransactionProposal`, etc.), `repositories.py` (abstract interfaces).
- `application/services/` — use cases (`TransactionService`, `ChatService`, etc.); business/ledger rules live here, not in routers or infrastructure.
- `infrastructure/` — SQLAlchemy models/repos (`database/`), Alembic migrations, auth (JWT/Google OAuth), Azure adapters, and `ai/` (LangGraph orchestrator, guardrails, intent classifier, finance tools).
- `presentation/routers/` + `presentation/schemas/` — FastAPI routers and Pydantic request/response models. Routers depend only on application services via `Depends()`, never on repositories or SQLAlchemy sessions directly.

Note: `.github/instructions/backend.instructions.md` describes this layer as `api/v1/routers`; the actual package name in this repo is `presentation/routers` — trust the real path, not that doc.

Money is always integer paise; timestamps are timezone-aware ISO 8601; public IDs are UUIDs. Every repository method touching user-owned data takes the authenticated `user_id` as a mandatory filter — a `user_id` from a request body, query param, or LLM tool argument is never trusted.

### LangGraph chat orchestration (`infrastructure/ai/langgraph_chat_orchestrator.py`)

`POST /api/v1/chat` is the **only** endpoint that invokes LangGraph. Voice/OCR endpoints only return transcript/OCR text for the user to review and resubmit through chat — they never write transactions directly.

The graph is a bounded supervisor loop, not a single-shot router:

```
analyze_turn (deterministic preflight: pending proposal / HITL in progress / guardrail / multi-row ledger paste)
  → supervisor (LLM picks: run_workflow / ask_user / finish / refuse, from a FIXED registry)
  → workflow_dispatch (code-level validation: registered id? not repeated? under handoff cap?)
  → one specialist node: transaction_flow | query_planner→query_orchestrator | category_management | format_previous_result
  → workflow_observer (turns the specialist's raw output into a bounded, typed WorkflowResult — status/summary only, never full transaction rows)
  → back to supervisor (only if status=success and workflow is analytics/format_previous) or supervisor_finish
```

Key invariants enforced in code, not by the LLM:
- Registered workflow IDs are exactly `{transaction, analytics, category_management, format_previous}` (`_REGISTERED_SUPERVISOR_WORKFLOWS`). An unregistered id, non-empty `arguments`, a repeated `(workflow_id, arguments)` key, or exceeding `_MAX_SUPERVISOR_HANDOFFS` (3) fails closed in `_workflow_dispatch_node`.
- A hard-block guardrail decision cannot be overridden by the supervisor at any point.
- Transaction writes always go through explicit HITL confirm; the supervisor/LLM can only *propose*, never commit. `_transaction_flow` is the only place that calls `TransactionService.create_transaction`.
- `_count_transaction_rows` / `_looks_like_multiple_transaction_rows` detect multi-row ledger pastes independent of literal newlines (date-bounded currency-entry counting) — this was previously newline-only and undercounted flattened single-line pastes; don't regress that.
- Finance facts (balances, totals, comparisons) come from deterministic DB-backed tools in `infrastructure/ai/tools/`; the LLM composes wording from already-computed facts via `FinanceQueryReply`/`_llm_query_reply_chain` and must not recalculate anything.
- Clarification pauses use LangGraph `interrupt()` and resume via `Command(resume=...)` on the next turn, keyed by checkpoint `thread_id = f'{user_id}:{thread_id}'`.

### Frontend: atomic design + RTK Query

`apps/web/src/` follows atoms → molecules → organisms → templates → pages, with one `features/<domain>/` folder per domain owning its slice (`*Slice.ts`, local UI state only) and RTK Query API (`*Api.ts`, all server state — no raw `fetch`). Chat drafts in `features/chat/chatDrafts.ts` are keyed by authenticated user id (`affordabled_chat_drafts_v1_user_<id>`); legacy unowned drafts are discarded, not reassigned, because their owner can't be safely established.

### Where to find current work-in-progress status

This repo's root `Final_Plan.md` and the newest `HANDOFF_*.md` are the live execution-status documents (current branch, what's merged vs. uncommitted, what's validated vs. not). They change frequently — check the newest-dated handoff file rather than assuming this file reflects current phase status.
