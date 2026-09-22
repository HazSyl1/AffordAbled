---
name: "AffordAbled Testing"
description: "Use when adding or modifying unit tests, API tests, integration tests, test fixtures, mocks, or test configuration for the React frontend or FastAPI backend."
---
# Testing Guidelines — Minimal by Design

Testing is intentionally lightweight. Do not add broad test suites, snapshot tests, or coverage targets unless explicitly requested.

- **Per API router:** one smoke test confirming its main happy path responds with the expected status and shape (e.g. `POST /accounts` creates and returns an account).
- **Per critical financial rule:** one focused test — paise arithmetic/rounding, transfer balance updates, transaction confirmation gating (AI proposal must not persist without confirm), and cross-user data isolation (user A cannot read/modify user B's resource).
- Use `pytest` + FastAPI's `TestClient`/`httpx.AsyncClient`. Keep fixtures isolated, deterministic, and free of real credentials or financial data.
- Do not write frontend automated tests unless explicitly asked for a specific component or flow.