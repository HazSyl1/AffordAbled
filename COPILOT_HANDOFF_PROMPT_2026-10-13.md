# Copilot Handoff Prompt (2026-10-13)

Use this prompt in GitHub Copilot Chat (Agent mode) from the `AffordAbled` repo root.

```text
You are continuing work on AffordAbled on branch `feature/advanced-guardrail`.

Primary context:
- FastAPI backend in `apps/api`
- React/Vite frontend in `apps/web`
- Latest implementation status is in `HANDOFF_2026-10-13.md` and `Final_Plan.md`

What is already completed:
1) Fixed Alembic migration chain for `users.conversation_storage_enabled`
2) Added persisted chat threads/messages + ownership-safe thread APIs
3) Added persisted `agent_corrections`
4) Added exports re-download endpoint + expiry and ownership checks
5) Added proactive `insights` payloads to chat and surfaced in frontend
6) Added retention cleanup scheduler for expired logs/exports/messages
7) Frontend lint/build pass with Vite native config loader scripts

Before editing, read these files first:
- `HANDOFF_2026-10-13.md`
- `Final_Plan.md`
- `LangGraph implmenetation plan.md`
- `apps/api/app/presentation/router.py`
- `apps/api/app/presentation/routers/chat_router.py`
- `apps/api/app/presentation/routers/threads_router.py`
- `apps/api/app/presentation/routers/exports_router.py`
- `apps/api/app/application/services/chat_service.py`
- `apps/api/app/application/services/thread_service.py`
- `apps/api/app/application/services/export_service.py`
- `apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py`
- `apps/api/app/infrastructure/ai/tools/langgraph_finance_tools.py`
- `apps/api/app/infrastructure/jobs/retention_jobs.py`
- `apps/web/src/pages/ChatPage/ChatPage.tsx`
- `apps/web/src/features/dashboard/DashboardPage.tsx`
- `apps/web/src/features/chat/chatApi.ts`
- `apps/web/src/features/chat/chatDrafts.ts`
- `apps/web/package.json`

Validation commands to run after changes:
- Backend:
  - `cd apps/api`
  - `pytest -q`
  - `ruff check .`
- Frontend:
  - `cd ../web`
  - `npm run lint`
  - `npm run build`

Execution rules:
- Keep changes minimal and scoped.
- Preserve layered backend architecture (domain/application/infrastructure/presentation).
- Do not break migration chain (`a2_guardrail_logs_user_storage` -> `b2` -> `b3` -> `b4`).
- Add/update tests for touched backend behavior.
- Update `HANDOFF_2026-10-13.md` and `Final_Plan.md` after finishing.

Now do this in order:
1) Summarize current state from handoff docs in 8 bullets.
2) Propose next 3 highest-value tasks.
3) Execute task #1 fully with tests.
4) Report changed files and validation output.
```

