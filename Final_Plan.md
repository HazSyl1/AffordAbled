# AffordAbled — Final Execution Plan

_Last reconciled: 2026-10-14_

This plan is the execution source of truth for the next product iteration. It distinguishes code that exists today from roadmap items that are only partially implemented or not implemented.

## 1. Git baseline and working rules

- Repository: `AffordAbled`
- Baseline branch: `main`
- Baseline commit: `1948d9e` — merge of PR #10 (`feature/langgraph-multi-step-supervisor`) into `main`.
- Current branch: clean `main` at `1948d9e`; no feature work is currently in progress.
- The feature branches `feature/advanced-guardrail`, `feature/chat-result-followups`, `feature/langgraph-supervisor`, and `feature/langgraph-multi-step-supervisor` have been merged. Do not continue feature work directly on `main`.
- Before each task: fetch/update `main`, verify clean status and current HEAD, then branch from the latest `origin/main`.
- Branch naming: `feature/<short-scope>`; use a separate branch for each independently reviewable phase.
- Commit in small, coherent slices using Conventional Commit summaries (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). Do not push or open a PR until the user requests it.
- Never stage `.env`, credentials, generated artifacts, or unrelated edits. Review `git diff --check`, staged diff, and status before committing.

### Recent merged commits

| Commit | Change |
|---|---|
| `616821f` | Merge PR #8: structured analytics result follow-ups and table formatting |
| `e88fae8` | Merge PR #9: bounded single-dispatch supervisor and standalone category management |
| `1948d9e` | Merge PR #10: bounded multi-step supervisor loop |
| `6fb6f7c` | Preserve and format finance query results |
| `850f995` | Merge PR #7: advanced guardrails, persistence, account defaults, intent/query improvements |
| `4639a83` | LLM intent classifier, finance query improvements, contextual analytics follow-up work, default account support |
| `205b624` | Handoff and validation documentation |
| `44f0918` | Frontend build unblock and chat UI updates |
| `2ec91e3` | Persistence APIs and migration chain |
| `281400c` | LangGraph guardrail telemetry and persistence |

The exact PR merge ancestry is available in Git; the table records the verified recent mainline history, not a list of remaining commits.

## 2. Locked contracts and safety constraints

1. `POST /api/v1/chat` is the only endpoint that invokes LangGraph.
2. Voice and image are two-step ingestion: their endpoints return transcript/OCR text; the user can review it and then submit text through chat.
3. Financial values are computed from database-backed deterministic tools. The LLM may interpret intent and compose wording, but may not invent or recalculate balances/totals.
4. Transaction writes require explicit HITL confirmation through the transaction service.
5. Authenticated user identity and ownership scope come from server-side request/graph state, never LLM tool arguments.
6. Model output can select only registered actions/workflows. Unknown, ambiguous, or unsafe actions must clarify or fail closed.
7. Preserve timezone-aware finance-query behavior and the existing checkpointer/thread ownership isolation.

## 3. Verified implementation snapshot

### Implemented

- Core account, category, and transaction APIs and frontend surfaces.
- Transaction proposals, confidence-gated clarification, confirm/cancel flow, and manual fallback.
- LLM intent classification with keyword fallback; configurable deterministic transaction routing.
- Spending summaries and transaction queries with calendar periods, user timezone, category filtering, and multi-category fan-out/aggregation.
- Recent conversation context supplied to routing/query planning; previous finance-query plan/result can be reused for drill-down and table formatting.
- A bounded multi-step supervisor and standalone category-management workflow are merged to `main` (PRs #9 and #10).
- Supervisor dispatch uses a registered workflow allowlist, bounded typed observations, a maximum of three handoffs, repeat-call protection, a decision timeout, and checkpointed clarification/resume.
- Response validation against database-produced finance facts.
- LangGraph checkpointing, chat thread/message persistence, ownership checks, guardrail decision logging, and agent correction records.
- Voice transcription path and basic image-to-text ingestion.
- Export artifact ownership/expiry lookup endpoint (download URL re-issuance), not end-to-end report generation.
- Config-gated retention cleanup for chat messages, guardrail logs, and expired export records.
- Per-user default account support, partial unique index, migration/backfill, and UI selection.

### Partially implemented / still needs end-to-end work

- **Workflow coverage:** standalone category creation and bounded multi-step supervisor are merged. Live-model/PostgreSQL analytics → category integration remains an optional verification.
- **Analytics:** summary/list paths are present. Comparison-to-period, user baselines/patterns, account balance query tools, robust table formatting, and large-result exports are not implemented as a complete analytics graph.
- **Receipt AI:** basic image-to-text exists; the staged Document Intelligence/layout → light LLM normalization → conditional vision fallback pipeline is not complete.
- **Exports:** re-download lookup is present; creating PDF/XLSX, blob upload, artifact creation, and chat handoff are absent.
- **Proactive insights:** summary/list insights exist; anomaly, recurring spend, budget threshold intelligence is not complete.
- **Intent workflow coverage:** the intent taxonomy includes split/report/account/memory categories, but matching specialist workflows are not all registered and executable.

### Not implemented (confirmed by current router/service/file inventory)

- Split domain/API/AI workflow and complete split frontend: `SplitsPage` remains a placeholder.
- Episodic/semantic/procedural memory services, storage, graph, and memory UI.
- Full Celery worker/Beat notifications and delivery pipeline. A retention loop is not a notification system.
- Redis-backed per-user/per-endpoint rate limits.
- LangSmith evaluation dataset and scheduled improvement loop.
- End-to-end Playwright browser suite and automated live-model evaluation suite.
- Route-level frontend chunk splitting; build warning has been non-blocking.

## 4. Prioritized implementation sequence

### Phase 0 — Conversation result continuity and formatting (merged)

**Branch:** `feature/chat-result-followups` — merged in PR #8 at `616821f`.

**Goal:** make results reusable as structured state and handle follow-up requests without guessing from prose.

1. [x] Define typed LLM actions for new query, drill-down, and formatting a prior result.
2. [x] Persist verified transaction rows and the query plan in LangGraph checkpoint state after a successful analytics call.
3. [x] Pass the structured previous result to the query planner and route formatting follow-ups to a dedicated graph node.
4. [x] Deterministically sort stored rows and render a Markdown table without a second DB query; escape cell pipes and preserve values.
5. [x] Render Markdown table blocks as accessible, horizontally scrollable HTML tables in both chat surfaces.
6. [x] Add regression tests for format action routing, stored result, scope reuse, sort order, and fact preservation.
7. [x] Add a deterministic graph-sequence regression test for summary → “where?” → “sort these by date and show me in a table”, including unchanged facts and formatting without a new query.
8. [ ] Run the complete authenticated HTTP sequence using the configured model and PostgreSQL checkpointer; verify state survives API restart.
9. [ ] Review checkpoint retention/storage policy for persisted transaction rows and document data minimization expectations.

**Acceptance / E2E:** same thread: “How much did I spend this month?” → “where?” → “sort these by date and show me in a table”. Expect same-period expense rows, no refusal/category prompt, date order explicitly defined (default newest first, unless user specifies otherwise), all amounts unchanged, table columns for date/merchant/amount/category, and no fabricated location/address claims.

**Current test evidence:** deterministic graph-node sequence test now covers summary facts → expense drill-down plan → stored transaction facts → sorted table without a second query. The full authenticated HTTP conversation with the configured live model remains a manual/opt-in integration check.

**Merged implementation:** `6fb6f7c feat: preserve and format finance query results` (merge commit `616821f`).

### Phase 1 — New-request arbitration and category-management workflow (merged)

**Branch:** `feature/langgraph-supervisor`; merged to `main` by PR #9 at `e88fae8`.

**Outcome:** after an analytics conversation, “Create a category 'Office Expense'” is routed as a new category-management request, not as a repeat query or formatting follow-up. Standalone category creation is registered beside transaction category-resolution.

#### 1A. Make current-request intent outrank stale analytics context

- Have the supervisor distinguish a **new request** from a **referential follow-up** to the previous result.
- Use `last_finance_query_result` only when the current request contains a reference/formatting intent such as “where?”, “those transactions”, “sort these”, or “show them in a table”. Do not route every non-transaction message to analytics merely because an earlier result exists.
- Preserve priority for a clearly new transaction (current turn has transaction evidence) and for explicit create/edit/delete-style actions.
- Keep guardrail hard-block precedence. Add tests for a new category action after analytics, a formatting follow-up after analytics, a new transaction after analytics, and off-topic content after analytics.

#### 1B. Register category management as a supervisor capability

- Add `category_management` to the structured supervisor workflow registry and map it to a dedicated graph node/subgraph route. Do not implement category creation as a fake transaction or as a query.
- Reuse the existing authenticated-user-scoped category mini-graph/tool/service. Do not duplicate repository logic or accept a model-supplied `user_id`.
- Parse the requested operation, name, and category type (`expense` or `income`). If type is unclear, ask a follow-up instead of silently assigning one; a name like “Office Expense” may be evidence but must follow a documented confidence/validation rule.
- Explicit “create category …” is user authorization to create that category; validate the name/type, create for the current user, and return a success response. It must not create or alter a transaction.
- Make duplicate requests idempotent: return the existing matching category or clearly report it already exists, without a duplicate row.
- Do not expose arbitrary account, transaction, or SQL tools through this workflow.

**Verification:** category-management is registered in the graph and supervisor; explicit category requests take precedence over stale analytics context; type clarification resumes; duplicate same-type requests are idempotent. Authenticated HTTP coverage verifies category persistence, user isolation, duplicate safety, and no transaction side effect. The full backend suite and Ruff passed before merge. A live-model/PostgreSQL same-thread analytics → category flow remains an opt-in integration check.

#### Acceptance tests

1. Same thread: spending summary → transaction list → “Create a category Office Expense”. Expected: category workflow, not old transaction rows.
2. Confirm category exists through the category API for the same user, with the selected/inferred type.
3. Repeat creation: no duplicate category.
4. Missing/ambiguous category type: ask a focused clarification and create only after resolved.
5. Another user cannot see or use the created category.
6. Existing follow-up flow still works: summary → “where?” → “sort these by date and show me in a table”.
7. New transaction after analytics still enters proposal/HITL and is not swallowed by prior-result context.
8. A hard-block guardrail decision cannot be overridden by supervisor/category workflow selection.

**Commit slices:**
- `fix(ai): distinguish new requests from prior-result follow-ups`
- `feat(ai): add standalone category-management workflow`
- `test(ai): cover category routing, duplicate safety, and user isolation`
- `docs: update supervisor and category workflow guidance`

**Phase exit gate:** all acceptance tests and full backend/Ruff validation pass; verify category creation is scoped and idempotent; run the live HTTP flow if model/PostgreSQL config is available; update the graph artifact; then PR-review and merge.

### Phase 2 — Bounded multi-step supervisor (merged)

**Branch:** `feature/langgraph-multi-step-supervisor`; merged to `main` by PR #10 at `1948d9e`.

**Recommendation:** implement incrementally—not as a broad graph rewrite. Phase 1 is merged. Phase 2 replaces one-shot routing with a bounded loop behind registered workflow contracts.

#### Target turn loop

```text
current message + bounded conversation/result context
	 → safety/preflight gates
	 → supervisor chooses: run registered workflow / ask user / finish / refuse
	 → workflow returns a typed result, clarification request, or safe error
	 → validate result and side effects
	 → supervisor sees a compact result summary and chooses next step
	 → repeat only within the per-turn budget
	 → final answer from verified results
```

The supervisor should not receive arbitrary node names or raw function access. Give it a capability registry containing only stable workflow IDs, descriptions, and argument schemas. Python resolves each ID to the implementation. Initially register only capabilities that actually exist: transaction proposal, analytics query/drill-down, prior-result formatting, and category management after Phase 1. Unsupported capabilities remain unavailable rather than being hallucinated.

#### Implementation design

1. **Define structured contracts**
	- `SupervisorAction`: `run_workflow`, `ask_user`, `finish`, or `refuse`.
	- For `run_workflow`, require a registered `workflow_id` and schema-validated arguments.
	- `WorkflowResult`: workflow ID, status (`success`, `needs_input`, `failed`), bounded user-safe summary, structured data reference/payload, and whether a side effect was proposed or committed.
	- Avoid copying entire histories/tool outputs into the supervisor prompt; provide a bounded conversation window and compact, typed result summaries. Keep full transaction facts in trusted state.

2. **Make the graph loop explicit**
	- Add a supervisor node that emits one structured action per iteration.
	- Add a deterministic dispatcher that checks the workflow ID against the registry and validates arguments before invoking a specialist node/subgraph/tool.
	- Each specialist returns a `WorkflowResult`; it does not decide the next unrelated capability.
	- Add an observation/validation step that checks result shape, user scope, errors, and side-effect rules, then returns to the supervisor.
	- The supervisor may call another registered capability, ask the user, finish, or refuse. A user question pauses with LangGraph `interrupt()` and resumes from the checkpoint on the next message.

3. **Add hard bounds and loop protection**
	- Start with a low configurable maximum (for example, 3 workflow handoffs per user turn).
	- Track handoff count and previously executed `(workflow_id, normalized_arguments)` pairs in graph state; reject repeated no-progress calls.
	- Bound per-call timeout, tool-result size, and total model/tool budget. On exhaustion, return a concise partial-result/clarification response; never spin.
	- Any action not in the registry, invalid arguments, or invalid workflow result is rejected by code.

4. **Preserve irreversible-action safeguards**
	- Read tools remain authenticated-user-scoped, with user ID injected from server/graph configuration.
	- Transaction workflows may build/update a proposal but cannot commit until the existing explicit HITL confirmation succeeds.
	- The supervisor cannot override guardrail hard blocks, ownership checks, tool authorization, transaction validation, or database fact validation.
	- Multi-step read operations may continue automatically within limits; ambiguous requests and all writes pause for user input/confirmation.

5. **Avoid duplicate reasoning layers**
	- Keep the top-level supervisor responsible for capability selection and multi-step coordination.
	- Keep deterministic validation/execution inside specialist workflows.
	- Keep the analytics planner only for analytics-specific interpretation if tests show it adds value; otherwise migrate its query-plan fields into the analytics workflow contract and retire the redundant LLM call. Do not have two LLM nodes independently re-decide the same top-level intent.
	- Keep guardrail and deterministic pending-HITL/transaction preflight before the supervisor; these are safety gates, not competing general-purpose planners.

#### Suggested work slices and commits

- `feat(ai): define registered workflow and result contracts`
- `feat(ai): add bounded supervisor dispatch and observation loop`
- `feat(ai): resume supervisor after workflow clarification`
- `test(ai): cover multi-step routing limits and safety invariants`
- `docs: explain registered supervisor loop and capability status`

Keep this feature branch focused on the supervisor engine. Register standalone category management in Phase 1 first; do not pull split, memory, export, or notification implementations into this phase just to make the registry look complete.

#### Acceptance tests

1. `create category` after an analytics conversation routes to category management—not the previous analytics result—and creates only for the authenticated user.
2. A supported composition can execute two read workflows (for example analytics followed by table formatting) and the supervisor receives the first workflow’s structured result before choosing the second.
3. A workflow can return `needs_input`; the graph asks the user, checkpoints, resumes, and continues with the same plan/context.
4. Transaction workflow proposes a write; no database write occurs before explicit confirmation. After confirmation exactly one write occurs.
5. Off-topic/hard-blocked requests cannot be routed to tools, even if the LLM supervisor requests it.
6. Unknown workflow ID, invalid arguments, invalid result, repeated no-progress call, timeout, and max-handoff exhaustion produce safe bounded exits.
7. Cross-user tests prove tools cannot change user scope using model arguments or checkpoint IDs.
8. Existing analytics, category, transaction HITL, prior-result table formatting, thread persistence, and ownership tests remain green.

Use stubbed supervisor decisions in normal CI. Keep real-model workflow evaluations opt-in/nightly and evaluate routing accuracy, clarification rate, tool selection, grounded responses, latency, and token/tool budgets.

**Phase exit gate:** full backend suite and Ruff pass; frontend lint/build pass if any UI changes occur; graph artifact is regenerated and reviewed; manual/opt-in same-thread test passes where PostgreSQL/model credentials are available; checkpoint storage/retention implications are documented; PR is reviewed and merged before starting the next product feature.

**Commit slices:** `feat(ai): add bounded supervisor plan state`; `feat(ai): execute registered multi-step workflows`; `test(ai): cover supervisor limits and safety`.

**Merged implementation:** action/result Pydantic contracts, fixed workflow registry, deterministic dispatcher and observer, three-handoff cap, duplicate workflow guard, supervisor decision timeout, and same-thread ask-user interrupt/resume. Tests cover analytics → `format_previous`, bounded summaries that do not expose transaction rows to the supervisor, unknown/repeated/over-budget/hard-blocked dispatch, transaction proposal stop behavior, contract validation, timeout fallback, and HTTP interrupt/resume. The graph asset is regenerated. Focused validation (16 tests) and Ruff passed. The full backend run was interrupted and not rerun before merge at the user's direction; this is not treated as a remaining task.

### Next: Phase 3 — Complete Analytics specialist

**Branch:** create `feature/analytics-workflows` from the latest clean `origin/main` before implementation.

Implement the approved Phase 3 scope below; do not start on `main`. Confirm and prioritize period comparisons, category/account breakdowns, account balance queries, clear empty/ambiguous responses, and result-size handling. Keep all figures database-authoritative and add a query evaluation set for relative dates, multi-category queries, follow-ups, and ambiguous requests.

### Phase 3 — Complete Analytics specialist

**Branch:** `feature/analytics-workflows`

Add only after reviewing product scope: period comparisons, category/account breakdowns, account balance queries, clear empty/ambiguous cases, and result-size handling. Every figure remains database-authoritative. Add a query evaluation set for natural language interpretations, including relative dates, multi-category queries, follow-ups, and adversarial/ambiguous requests.

**Acceptance:** deterministic tool tests for math/filtering/timezones/ownership; planner tests for structured plans; response fact-preservation tests; live-model evaluation is a separate opt-in/nightly job.

### Phase 4 — Splits (if product priority confirmed)

**Branch:** `feature/splits-mvp`

Build split schema/domain/service/repositories/routes, contacts, equal/custom calculation, settlement, balance reconciliation, confirmation UX, and tracker UI. Defer smart bill-line splitting until ordinary split creation/settlement is reliable.

**Acceptance:** exact paise arithmetic including remainder allocation; owner isolation; transaction/split atomicity; confirm/cancel; settlement state; browser journey.

### Phase 5 — Exports and receipt pipeline

Separate branches: `feature/report-exports` and `feature/receipt-extraction`.

- Exports: deterministic PDF/XLSX rendering, blob storage adapter, artifact record creation/expiry, owner-scoped fresh download URL, chat handoff, cleanup.
- Receipt pipeline: OCR/layout extraction first, normalization second, vision fallback only for low-confidence cases. Keep image endpoint’s two-step review contract unless explicitly changed.

External-service work must document provisioning, env vars/secrets, and a concrete verification checklist before implementation is considered complete.

### Phase 6 — Memory and intelligence

Branches: `feature/finance-memory`, then `feature/proactive-insights-eval`.

Implement memory types only with explicit user controls, retention/deletion, ownership tests, and data minimization. Add anomaly/recurring/budget insights only when baseline data and a Budget domain are defined. Evaluation telemetry must avoid secrets/PII and include a documented opt-out/retention policy.

### Phase 7 — Notifications, rate limits, reliability

Branch: `feature/notifications-rate-limits`.

Implement notification preferences/outbox, Celery worker and Beat, email/push provider adapters, idempotency keys/deduplication, retries/dead-letter handling, and Redis-backed rate limits. Keep notifications disabled until provider setup and delivery checks are complete.

### Phase 8 — Release hardening

Branch: `chore/release-hardening` or final release branch selected by maintainer.

- Route/feature code splitting if bundle warning remains valuable to address.
- Verify migration chain against a fresh database and the current environment; check actual Alembic head instead of assuming a revision ID.
- Full backend tests + Ruff; frontend lint + typecheck/build; focused E2E; auth/ownership/security review.
- Update architecture/Final Plan/handoff docs, note all migrations and operational setup, group commits, and prepare PR notes.

## 5. Per-phase development and Git procedure

1. Start from clean, updated `main`; record baseline HEAD. Never discard pre-existing work.
2. Create the phase-specific branch named above.
3. Before editing, inspect current files, tests, API contracts, migrations, and repo instructions. Treat this plan as priorities, not permission to bypass current code constraints.
4. Implement one reviewable slice at a time; add tests with the behavior.
5. Run focused tests/lint after each slice, then the phase validation below.
6. Review `git diff --check`, `git status`, staged diff, and ensure no secrets/config-local files are staged.
7. Commit with the planned Conventional Commit; push/PR only when explicitly requested.
8. Merge only after acceptance checks. Start the next phase from updated `main`.

## 6. Validation gates

### Every backend phase

- Focused pytest tests for changed behavior.
- Full `pytest -q` in `apps/api`.
- `ruff check .` in `apps/api`.
- Pylance/type diagnostics for changed files.
- If schema changes: Alembic upgrade from clean DB and upgrade from supported prior head; downgrade reviewed where safe.

### Every frontend phase

- Focused UI/component tests if present.
- `npm run lint`, `npm run build` in `apps/web`.
- Browser verification at desktop and mobile widths for user-visible behavior.

### Release gate

- Verify branch is based on current main and working tree is clean after commit.
- Verify exact Alembic current/head in target and migration path; do not assume `b4` because current branch includes `f2` and ordering may be chained differently.
- Run API health and authenticated smoke checks after migration.
- Record validation output, migration impact, environment requirements, and any skipped/live-model tests.

## 7. Definition of done

- Chat endpoint contract remains intact; voice/image remain reviewable ingestion steps.
- Transaction writes remain confirmed and user-scoped.
- Finance answers and tables are grounded in deterministic results.
- Contextual result-follow-ups work in one persistent thread and have regression tests.
- Supervisor can only dispatch registered, bounded, safe specialist workflows.
- Completed features have API/UI/tests/docs aligned; roadmap status is refreshed after each merged phase.
- CI validation passes and required migrations/operational setup are documented.

## 8. Open decisions before later phases

- Whether Splits or report exports should be the first major product workflow after analytics/supervisor completion.
- Whether tables are represented as Markdown text or a structured message block in the chat API/UI.
- Whether memory should be in the first release; confirm product consent, retention, deletion, and export behavior first.
- Production provider choices and provisioning for blob, OCR, notifications, email, push, and Redis rate limiting.
