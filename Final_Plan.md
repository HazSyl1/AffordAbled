# AffordAbled — Final Execution Plan

_Last reconciled: 2026-10-14_

This plan is the execution source of truth for the next product iteration. It distinguishes code that exists today from roadmap items that are only partially implemented or not implemented.

## 1. Git baseline and working rules

- Repository: `AffordAbled`
- Baseline branch: `main`
- Baseline commit: `850f995` — merge of PR #7, including `4639a83` (`feat: improve finance chat and account defaults`).
- Verified at planning time: implementation branch `feature/chat-result-followups` was created from `main` at `850f995`. This branch now contains uncommitted Phase 0 implementation changes; the plan edit that preceded implementation is also in the worktree.
- The feature branch `feature/advanced-guardrail` has been merged. Do not continue feature work on `main`.
- Before each task: fetch/update `main`, verify clean status and current HEAD, then branch from the latest `origin/main`.
- Branch naming: `feature/<short-scope>`; use a separate branch for each independently reviewable phase.
- Commit in small, coherent slices using Conventional Commit summaries (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). Do not push or open a PR until the user requests it.
- Never stage `.env`, credentials, generated artifacts, or unrelated edits. Review `git diff --check`, staged diff, and status before committing.

### Recent merged commits

| Commit | Change |
|---|---|
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
- Recent conversation context supplied to routing/query planning; previous finance-query plan can be reused for a spending-to-transaction drill-down.
- Response validation against database-produced finance facts.
- LangGraph checkpointing, chat thread/message persistence, ownership checks, guardrail decision logging, and agent correction records.
- Voice transcription path and basic image-to-text ingestion.
- Export artifact ownership/expiry lookup endpoint (download URL re-issuance), not end-to-end report generation.
- Config-gated retention cleanup for chat messages, guardrail logs, and expired export records.
- Per-user default account support, partial unique index, migration/backfill, and UI selection.

### Partially implemented / still needs end-to-end work

- **Conversation continuity:** thread history is checkpointed and a limited context window is passed to classifiers/planners, but previous tool rows are not yet represented as a reusable structured result. Follow-up requests that transform prior results (for example “sort these by date and show me in a table”) can still fall through to generic chat.
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

### Phase 0 — Conversation result continuity and formatting (in progress)

**Branch:** `feature/chat-result-followups`

**Goal:** make results reusable as structured state and handle follow-up requests without guessing from prose.

1. [x] Define typed LLM actions for new query, drill-down, and formatting a prior result.
2. [x] Persist verified transaction rows and the query plan in LangGraph checkpoint state after a successful analytics call.
3. [x] Pass the structured previous result to the query planner and route formatting follow-ups to a dedicated graph node.
4. [x] Deterministically sort stored rows and render a Markdown table without a second DB query; escape cell pipes and preserve values.
5. [x] Render Markdown table blocks as accessible, horizontally scrollable HTML tables in both chat surfaces.
6. [x] Add regression tests for format action routing, stored result, scope reuse, sort order, and fact preservation.
7. [ ] Add/confirm an end-to-end acceptance test for: summary → “where?” → “sort these by date and show me in a table”, including exact row count and unchanged facts.
8. [ ] Review checkpoint retention/storage policy for persisted transaction rows, test deployed PostgreSQL checkpointer behavior, and document data minimization expectations.

**Acceptance / E2E:** same thread: “How much did I spend this month?” → “where?” → “sort these by date and show me in a table”. Expect same-period expense rows, no refusal/category prompt, date order explicitly defined (default newest first, unless user specifies otherwise), all amounts unchanged, table columns for date/merchant/amount/category, and no fabricated location/address claims.

**Current test evidence:** deterministic graph-node sequence test now covers summary facts → expense drill-down plan → stored transaction facts → sorted table without a second query. The full authenticated HTTP conversation with the configured live model remains a manual/opt-in integration check.

**Commit slices (not committed yet):**
- `feat(api): preserve structured analytics results for chat follow-ups`
- `feat(api): route contextual result formatting and drill-down actions`
- `feat(web): render structured chat tables`
- `test(chat): cover summary drill-down and result formatting`

### Phase 1 — Bounded top-level supervisor and workflow registry

**Branch:** `feature/langgraph-supervisor`

Continue after Phase 0 acceptance tests pass. The current work already gives the analytics planner typed actions and a registered formatter node; this is not yet a universal top-level supervisor. Next introduce a bounded supervisor over only workflows that exist: transaction proposal, analytics, clarification, prior-result formatting, and safe response. Register new workflows only when implemented. Allow bounded multi-step handoffs with a small maximum iteration count and explicit state transitions. Preserve guardrails, user scoping, transaction confirmation, DB-derived facts, and per-workflow error recovery. Do not give the LLM arbitrary graph access or unrestricted write tools.

**Acceptance:** mocked decisions route correctly; unknown handoffs are rejected; supervisor loops are bounded; cross-user tool scope cannot be overridden; writes still require HITL; existing chat/transaction/thread tests remain green.

**Commit slices:** `feat(api): add bounded supervisor decision model`; `feat(api): register analytics and transaction specialist workflows`; `test(ai): cover supervisor routing, limits, and safety`.

### Phase 2 — Complete Analytics specialist

**Branch:** `feature/analytics-workflows`

Add only after reviewing product scope: period comparisons, category/account breakdowns, account balance queries, clear empty/ambiguous cases, and result-size handling. Every figure remains database-authoritative. Add a query evaluation set for natural language interpretations, including relative dates, multi-category queries, follow-ups, and adversarial/ambiguous requests.

**Acceptance:** deterministic tool tests for math/filtering/timezones/ownership; planner tests for structured plans; response fact-preservation tests; live-model evaluation is a separate opt-in/nightly job.

### Phase 3 — Splits (if product priority confirmed)

**Branch:** `feature/splits-mvp`

Build split schema/domain/service/repositories/routes, contacts, equal/custom calculation, settlement, balance reconciliation, confirmation UX, and tracker UI. Defer smart bill-line splitting until ordinary split creation/settlement is reliable.

**Acceptance:** exact paise arithmetic including remainder allocation; owner isolation; transaction/split atomicity; confirm/cancel; settlement state; browser journey.

### Phase 4 — Exports and receipt pipeline

Separate branches: `feature/report-exports` and `feature/receipt-extraction`.

- Exports: deterministic PDF/XLSX rendering, blob storage adapter, artifact record creation/expiry, owner-scoped fresh download URL, chat handoff, cleanup.
- Receipt pipeline: OCR/layout extraction first, normalization second, vision fallback only for low-confidence cases. Keep image endpoint’s two-step review contract unless explicitly changed.

External-service work must document provisioning, env vars/secrets, and a concrete verification checklist before implementation is considered complete.

### Phase 5 — Memory and intelligence

Branches: `feature/finance-memory`, then `feature/proactive-insights-eval`.

Implement memory types only with explicit user controls, retention/deletion, ownership tests, and data minimization. Add anomaly/recurring/budget insights only when baseline data and a Budget domain are defined. Evaluation telemetry must avoid secrets/PII and include a documented opt-out/retention policy.

### Phase 6 — Notifications, rate limits, reliability

Branch: `feature/notifications-rate-limits`.

Implement notification preferences/outbox, Celery worker and Beat, email/push provider adapters, idempotency keys/deduplication, retries/dead-letter handling, and Redis-backed rate limits. Keep notifications disabled until provider setup and delivery checks are complete.

### Phase 7 — Release hardening

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
