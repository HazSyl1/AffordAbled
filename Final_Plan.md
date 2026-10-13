# AffordAbled Final Plan

_Last updated: 2026-10-13_

## Locked Architecture Decisions

1. `POST /api/v1/chat` is the only endpoint that invokes LangGraph.
2. Voice and image use two-step ingestion:
   - `POST /api/v1/chat/voice` returns transcript only.
   - `POST /api/v1/chat/image` returns OCR extraction only.
   - Frontend can edit extracted text, then send final text to `POST /api/v1/chat`.
3. Financial values must come from deterministic tools (no fabricated totals).
4. Transaction writes require HITL confirmation.

## Status Snapshot (Done)

- Deterministic query routing is implemented in LangGraph.
- Category tool mini-graph is implemented and wired to canonical categories.
- HITL clarification/cancel flow is implemented for transaction proposals.
- Voice STT integration path is implemented with transcoding fallback.
- Guardrail policy + decision logging plumbing is integrated end-to-end.
- Structured request logging + request-id context is integrated in middleware.
- Migration issue fixed for user storage flag rollout:
  - `apps/api/alembic/versions/a2_add_guardrail_logs_and_user_storage_flag.py` revision id was shortened to fit Alembic `VARCHAR(32)` limit.
  - `alembic upgrade head` now succeeds and applies `conversation_storage_enabled` + `guardrail_logs` schema.
- Flaky date-sensitive chat test was fixed to use dynamic relative time.
- Thread/message persistence and ownership-safe thread APIs are now implemented:
  - Added `chat_threads` + `chat_messages` persistence path.
  - Added `/api/v1/threads` create/list/get/delete endpoints with user ownership checks.
  - Chat turns now persist user + assistant messages to thread history.
- Agent correction persistence is implemented:
  - Added `agent_corrections` table and repository plumbing.
  - Chat proposal edits now store original proposal, corrected proposal, and user correction message.
  - Focused correction-flow tests pass.
- Export re-download endpoint is implemented:
  - Added `exports` table and repository/service plumbing.
  - Added authenticated endpoint `GET /api/v1/exports/{id}/download-url` with owner and expiry checks.
  - Focused export endpoint tests pass.
- Proactive insights are integrated into chat query responses:
  - Query tools now return structured `insights` payloads.
  - `/api/v1/chat` now exposes `insights`, and frontend chat UIs render them as assistant follow-up messages.
- Scheduled retention jobs are implemented:
  - Added periodic cleanup loop on app startup (config-gated) for expired guardrail logs, expired export links, and old chat messages.
  - Added retention cleanup utilities and focused retention job tests.
- Validation status:
  - Backend `ruff check .` passes.
  - Backend `pytest -q` passes (51 tests).
  - Frontend `npm run lint` passes.
  - Frontend `npm run build` passes after switching Vite execution to native config loading.

## Remaining Scope

1. Non-blocking frontend optimization: split oversized bundles reported during build warning.
2. Final merge-prep pass: run full validation, group logical commits, and prepare PR notes including migration impact.

## Execution Order (Next)

1. Run final validation:
   - Backend: `pytest -q` and `ruff check .` in `apps/api`.
   - Frontend: `npm run lint` and `npm run build` in `apps/web`.
2. Optional performance follow-up:
   - Introduce route-level or feature-level code splitting in web app entry points to reduce primary JS chunk size.
3. Release hygiene:
   - Prepare PR summary with migration chain (`a2` -> `b2` -> `b3` -> `b4`) and attach validation outputs.

## Definition of Done

- Chat contract remains locked (`/chat` orchestration, `/chat/voice` transcript only, `/chat/image` OCR only).
- Thread ownership checks and message persistence are active.
- Guardrail + correction telemetry are persisted and queryable.
- Export redownload endpoint is production-ready.
- Focused tests for touched files pass; final backend/frontend validation passes.
