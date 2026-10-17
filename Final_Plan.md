# AffordAbled — Final Execution Plan

_Last reconciled: 2026-10-17_

**Current continuation context:** this document was reconciled against the current `feature/report-exports` worktree on 2026-10-17. `HANDOFF_2026-10-15.md` and the October 13 handoffs are historical snapshots; their branch names and "next actions" are not current instructions.

This plan is the execution source of truth for the next product iteration. It distinguishes code that exists today from roadmap items that are only partially implemented or not implemented.

## Current checkpoint (2026-10-17)

- Current branch: `feature/report-exports`, created on top of the committed split work. Report export/import implementation and split participant memory plan edits are on this branch; preserve unrelated local files.
- The split product flow is implemented across API/domain, UI, and LangGraph: create/edit splits, equal/custom shares, outstanding balances, mark a participant repaid (which creates and links a categorized income transaction), navigate between a split and its transaction, and create a split from chat after recording the expense. Split questions such as "how much do I owe/need to receive?" use a user-scoped read tool; contextual elaboration can reuse the tool observation/history.
- The user has manually confirmed the split UI and repayment flow are working. API regression coverage exists in `apps/api/tests/test_splits.py`; the full suite and complete fresh-thread AI/browser journeys have not been re-run as a release gate after all recent changes.
- Conversation context and tool observations are now retained in the LangGraph state, with category-clarification resume fixes and regression tests. The user-facing popup duration is 12 seconds in dashboard and chat; the frontend production build passed on 2026-10-17.
- Profile page and latest-five transaction summary, chat-history behavior, and transaction-chat close/discard/promote/draft choices are implemented. Verify these in the app if changing their behavior; do not treat the older October 15 handoff as authoritative for them.
- Current priority: the user reports the export/import app checks are complete. Decide whether to start the separate receipt extraction branch. The multi-category chat resume regression is fixed and the full backend suite passes.

**Not yet a release claim:** the full backend suite reached 100 passed on 2026-10-17. No full live-model suite or complete desktop/mobile browser acceptance run has been recorded for the combined worktree.

## 1. Git baseline and working rules

- Repository: `AffordAbled`
- Baseline branch/commit details below describe the October 15 snapshot only; inspect Git before rebasing or branching.
- Current implementation branch: `feature/report-exports`; the export/import feature is committed, while subsequent UI and category resume fixes are uncommitted.
- The feature branches `feature/advanced-guardrail`, `feature/chat-result-followups`, `feature/langgraph-supervisor`, and `feature/langgraph-multi-step-supervisor` have been merged. Do not continue feature work directly on `main`.
- Before a new independent phase: verify status, fetch/update `main`, then branch from the latest `origin/main`. For this continuation, preserve the dirty feature branch; do not pull/checkout/reset or recreate it from main.
- Branch naming: `feature/<short-scope>`; use a separate branch for each independently reviewable phase.
- Commit in small, coherent slices using Conventional Commit summaries (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). Do not push or open a PR until the user requests it.
- Never stage `.env`, credentials, generated artifacts, or unrelated edits. Review `git diff --check`, staged diff, and status before committing.

### Recent merged commits

| Commit | Change |
|---|---|
| `f4d7b12` | Merge PR #11: reconcile Phase 2 documentation/status |
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
- Analytics includes database-derived supported period comparisons, top-category summaries, authenticated-user account-balance reads, spending-by-account breakdowns, explicit capped-result disclosure, and clearer empty results. This work remains subject to the focused ambiguity/query checks listed below and is not claimed as merged.
- Split domain, API, migrations, tools, specialist, UI, and repayment-to-transaction linkage are implemented on the current feature branch.
- Profile editing and a lazy latest-five transaction summary are implemented; the profile summary does not wait for the profile form data.
- Chat persistence includes stored conversation messages and tool observations in graph state; split and category clarification follow-ups have targeted regression coverage.
- Response validation against database-produced finance facts.
- LangGraph checkpointing, chat thread/message persistence, ownership checks, guardrail decision logging, and agent correction records.
- Voice transcription path and basic image-to-text ingestion.
- Export artifact ownership/expiry lookup endpoint (download URL re-issuance), not end-to-end report generation.
- Config-gated retention cleanup for chat messages, guardrail logs, and expired export records.
- Per-user default account support, partial unique index, migration/backfill, and UI selection.

### Partially implemented / still needs end-to-end work

- **Workflow coverage:** standalone category creation and bounded multi-step supervisor are merged. Live-model/PostgreSQL analytics → category integration remains an optional verification.
- **Analytics:** summary/list paths, supported period comparisons, top-category breakdowns, active-account balances, spending-by-account breakdowns, capped-result disclosure, and clearer empty results are implemented on the uncommitted feature branch. Consistent ambiguity UX, broader live-model evaluation, user baselines/patterns, pagination beyond fixed caps, and large-result exports remain incomplete.
- **Browser identity isolation:** user-scoped local drafts, legacy unowned-draft removal, identity-keyed chat state, and auth cache resets are implemented but need a same-browser multi-user journey check. Backend repository/checkpoint ownership appeared scoped; browser local storage was the likely exposure source.
- **Batch transaction review:** 2–10 supported ledger rows produce all-or-nothing ordered proposals and sequential per-transaction forms in both chat surfaces. No write occurs until an individual form is saved. Cancel/close clears the remainder; queue persistence and live-model/browser verification remain outstanding.
- **Receipt AI:** basic image-to-text exists; the staged Document Intelligence/layout → light LLM normalization → conditional vision fallback pipeline is not complete.
- **Exports:** re-download lookup is present; creating PDF/XLSX, blob upload, artifact creation, and chat handoff are absent.
- **Proactive insights:** summary/list insights exist; anomaly, recurring spend, budget threshold intelligence is not complete.
- **Intent workflow coverage:** transaction, category, analytics, account, and split capabilities exist. Export and memory workflows are still not implemented; confirm any remaining registry gaps against the current graph before adding specialists.

### Not implemented (confirmed by current router/service/file inventory)

- Staged receipt extraction, episodic/semantic/procedural memory, split participant preference memory, and notification delivery are not implemented. Report export/import is implemented on `feature/report-exports`; its migrations and live application checks remain outstanding.
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

### Phase 3 — Complete Analytics specialist (implemented; acceptance checks remain)

**Branch:** analytics work is present in the current worktree; inspect status before separating or committing it.

**Current slice:** database-derived comparisons for this-month-to-date vs matching dates last month and this-week-to-date vs matching days last week; top-five category totals; current balances for all active accounts or a requested exact name; spending breakdowns by active account; explicit overflow disclosure for transaction/account result caps; clearer zero-result replies carrying requested dates/category and verified zero totals/counts; and a deterministic query-planning evaluation matrix. Balance values come from authenticated account records, never transaction recomputation. Comparison totals, counts, deltas, and percentages come from database-backed code, with category scope applied consistently to both windows. Unsupported comparisons and multiple simultaneous category filters clarify instead of silently degrading to a one-period answer. The earlier focused comparison/account run passed 30 tests and Ruff; tests were not rerun after the latest empty-result/evaluation-matrix edits per user instruction. Ruff passes on the current working tree.

**Remaining:** consistent clarification UX for ambiguous category/account/query interpretations and broader live-model/query evaluation. Keep all figures database-authoritative and expand checks for relative dates, multi-category requests, follow-ups, and adversarial/ambiguous requests.

### Current branch additions — Privacy and batch transaction review

Alongside Phase 3, the working tree contains browser draft/auth identity isolation, ordered batch transaction proposals, and sequential transaction sheets. Preserve the existing dashboard greeting edits. Detailed file map, limitations, and continuation steps are in `HANDOFF_2026-10-15.md`.

**Latest validation:** after the user reported flattened ledger input failing, a regression reproduced a newline-only detector counting six entries as one. Detection now uses date-bounded currency entries, independent of line breaks. Eleven focused chat/batch/legacy-confirmation tests passed (94 deselected), including the exact six-row input through an authenticated HTTP route with stubbed extraction/guardrail; orchestrator/test Ruff checks passed. Earlier frontend lint and TypeScript/Vite production build passed with the existing >500 kB chunk warning; no frontend code changed in this correction. This does not validate all Phase 3 edits or the full combined backend suite. Live-model batch routing, form reset/save behavior, and same-browser cross-user isolation remain to be checked. See the handoff correction for fresh-thread retry guidance.

**Acceptance:** deterministic tool tests for math/filtering/timezones/ownership; planner tests for structured plans; response fact-preservation tests; live-model evaluation is a separate opt-in/nightly job.

### Phase 4 — Splits (implementation complete; final acceptance checks remain)

**Branch:** `feature/splits-mvp`

Implemented: split schema/domain/service/repositories/routes, participant contacts, equal/custom shares, edit flow, outstanding totals, repayment and linked categorized income transaction, transaction navigation, and tracker UI. LangGraph can create a split after recording an expense, resolve participant names from existing contacts or add new people, and answer outstanding-split questions with user-scoped data. The transaction must exist before the AI creates its split. Marking a share repaid is final; partial repayment and undo are not supported.

Receipt item allocation using remembered participant preferences is planned in Phase 6. The current split model stores participant totals, so that feature will also need a reviewed item-to-person allocation before those totals are saved.

**Acceptance already covered by code/tests:** exact paise arithmetic and remainder allocation, owner isolation, custom-share validation, edits preserving linked repayments, repayment transaction/category linkage, and protection of linked repayment transactions. `apps/api/tests/test_splits.py` contains the API coverage. The user manually confirmed the split UI and repayment flow work.

**Remaining acceptance:** test a fresh-thread chat request such as "spent 1000 on dinner with X and Y" end to end; confirm expense is recorded before split creation, contact matching/new participant creation is correct, the UI refreshes to show the split, and a follow-up such as "elaborate" reuses verified split details. Also verify failure behavior if the transaction succeeds but split creation fails. Run broader backend/browser gates during release hardening.

### Phase 5 — Exports and receipt pipeline

Separate branches: `feature/report-exports` and `feature/receipt-extraction`.

**Report export/import implementation on `feature/report-exports`:** CSV/XLSX/PDF transaction exports, local date filtering, signed owner-scoped download links, retention through the existing scheduler, and chat report handoff are implemented. Generated reports exclude internal IDs, hashes, and notes; older report downloads are retired by version check and migration. CSV/XLSX transaction import now has preview, row validation, account/category ownership checks, one-transaction batch confirmation, and exact-file duplicate protection, including same-user report re-import via a server-side fingerprint. Edited files are not checked for duplicate rows; the UI explains this limit. See `docs/TRANSACTION_FILES.md` for limits, deployment, and test steps. Report bytes currently use PostgreSQL; a blob adapter remains an optional scaling step. Receipt extraction remains a separate feature.

- Exports: deterministic PDF/XLSX rendering, blob storage adapter, artifact record creation/expiry, owner-scoped fresh download URL, chat handoff, cleanup.
- Receipt pipeline: OCR/layout extraction first, normalization second, vision fallback only for low-confidence cases. Produce structured line items, prices, quantity, tax/fees, and extraction confidence for later item-level splits. Keep image endpoint’s two-step review contract unless explicitly changed.

External-service work must document provisioning, env vars/secrets, and a concrete verification checklist before implementation is considered complete.

### Phase 6 — Memory and intelligence

Branches: `feature/finance-memory`, then `feature/split-participant-memory` after the structured receipt pipeline, then `feature/proactive-insights-eval`.

Implement memory types only with explicit user controls, retention/deletion, ownership tests, and data minimization. Add anomaly/recurring/budget insights only when baseline data and a Budget domain are defined. Evaluation telemetry must avoid secrets/PII and include a documented opt-out/retention policy.

#### Split participant preferences and smart receipt splits

- Store preferences for a stable, authenticated-user-owned split contact, rather than matching names alone. Start with user-approved dietary preferences such as vegetarian; allow the user to view, edit, or delete each preference. Record where it came from and when it was confirmed. Do not turn a single receipt or the model's guess into a permanent fact about a person.
- After receipt extraction, the user can say, for example, “Dinner with Isha and Piyush.” Resolve the contacts, retrieve the owner's approved preferences, classify receipt items only where the evidence is clear, and draft item-to-person assignments. If Isha is stored as vegetarian, exclude meat items from her suggested share. A vegetarian preference alone does not prove that she consumed every vegetarian item; ask for or show editable assignments when consumption is unclear.
- Extend the split proposal and review UI to show each receipt item, assigned people, each person's calculated share, shared tax/tip/fees, and the total. Calculate allocations deterministically in paise, including remainder handling. The LLM may suggest item labels and assignments, but may not invent prices or calculate final amounts. Require review before saving the transaction-linked split.
- Keep participant preferences and receipt allocations scoped to the authenticated user. Handle duplicate names, missing contacts, uncertain item labels, incomplete receipts, and conflicting preferences with a focused clarification or an editable equal-split fallback.

**Acceptance:** with an approved “Isha is vegetarian” preference and a receipt containing vegetarian and meat items, Isha's proposed allocation excludes meat; the displayed participant shares plus the owner's share exactly match the verified receipt total, including shared charges and rounding. A change or deletion of Isha's preference changes future proposals only, never historical splits. Cross-user tests prove another account cannot read or alter the preference or the resulting split.

The profile's transaction summary currently uses only the authenticated user's latest five transactions and loads independently of the profile form. When memory is implemented, consider an optional, user-controlled summary that can draw on longer-term patterns. Keep a deterministic latest-five fallback, define what is remembered and for how long, and let users inspect/delete memory before using it for profile copy.

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

- Whether tables are represented as Markdown text or a structured message block in the chat API/UI.
- Whether memory should be in the first release; confirm product consent, retention, deletion, and export behavior first.
- Which participant preferences the app should store beyond dietary restrictions, and how the user confirms or corrects proposed receipt item assignments.
- Production provider choices and provisioning for blob, OCR, notifications, email, push, and Redis rate limiting.
