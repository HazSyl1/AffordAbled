# AffordAbled Project Guidelines

## Product Boundaries

- AffordAbled is a local-first AI wallet rebuilt as a React web client and FastAPI API.
- Store monetary values as integer paise. Use ISO 8601 timestamps and UUID identifiers.
- AI may draft or clarify transaction data, but it must never persist a transaction without explicit user confirmation.
- Keep provider credentials and Azure secrets on the server. Do not expose secrets through browser code, logs, examples, or committed `.env` files.
- A user must never be able to read, modify, or delete another user's data. Every owned resource is authorized against the authenticated user on the server, not just filtered in the client.

## Confirmed Tech Stack

- **Frontend:** React + TypeScript, Redux Toolkit + RTK Query, CSS Modules, atomic component structure. See [frontend.instructions.md](instructions/frontend.instructions.md).
- **Backend:** FastAPI with onion architecture (domain / application / infrastructure / api), SQLAlchemy 2.0 async + Alembic, FastAPI `Depends()` for dependency injection. See [backend.instructions.md](instructions/backend.instructions.md).
- **Auth:** Email/password with JWT access + refresh tokens, plus Google OAuth 2.0 login. Both issue the same internal JWT session.
- **Testing:** Minimal by design — one smoke test per API router and one test per critical financial rule. See [testing.instructions.md](instructions/testing.instructions.md).

## Repository Structure

- `apps/web/` is the React and TypeScript frontend.
- `apps/api/` is the FastAPI backend.
- `infra/` contains local infrastructure configuration and future Azure infrastructure as code.
- Keep frontend, API, and infrastructure changes within their ownership boundaries. Add shared contracts deliberately rather than duplicating types silently.

## Working Practices

- Make focused changes and preserve existing public API behavior unless the task requires a breaking change.
- Validate changed code with the narrowest relevant lint, test, type-check, or build command.
- Do not include real credentials, personal financial data, or production identifiers in fixtures or examples.
- Update this guidance when a project convention becomes stable; keep it concise and actionable.