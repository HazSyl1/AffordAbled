# AffordAbled

AffordAbled is a personal finance app for tracking accounts, categories, transactions, and shared expenses. Its chat assistant uses LangGraph workflows to record and query financial data, with explicit review before transaction writes. It also supports receipt and voice ingestion, transaction import/export, itemized splits, and user-controlled preference memory.

## Project layout

- `apps/api/` — FastAPI backend, layered application/domain/infrastructure/presentation code, LangGraph agents, and Alembic migrations.
- `apps/web/` — React, TypeScript, and Vite frontend.
- `infra/` — deployment and infrastructure assets.
- `docs/` — architecture, product reference, transaction file behavior, and release checklist.

## Local development

### API

1. Create a Python 3.13 virtual environment in `apps/api` and install dependencies with `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and configure PostgreSQL plus the providers needed for the features you want to exercise. Do not commit `.env` or real credentials.
3. Apply database migrations from `apps/api`: `alembic upgrade head`.
4. Start the API from `apps/api`: `uvicorn app.main:app --reload`.

The API defaults to `http://localhost:8000`; its OpenAPI UI is at `/docs`. PostgreSQL is required for normal application persistence. Chat model, OCR, speech, and storage integrations require their corresponding credentials and service configuration.

### Web

1. Install dependencies in `apps/web` with `npm install`.
2. Optionally set `VITE_API_BASE_URL` in a local `.env` file; the default is `http://localhost:8000`.
3. Start Vite with `npm run dev`.

## Checks

From `apps/api`:

```powershell
python -m pytest -q
ruff check .
```

From `apps/web`:

```powershell
npm run lint
npm run build
```

## Product and release documentation

- [Project and architecture reference](docs/AFFORDABLED_PROJECT_REFERENCE.md)
- [Transaction CSV/XLSX import and export](docs/TRANSACTION_FILES.md)
- [Version 1 release checklist](docs/V1_RELEASE_CHECKLIST.md)
- [Current implementation plan](Final_Plan.md)

The release checklist tracks remaining migration, deployment, and browser acceptance gates. A successful local build and test run alone does not indicate that a production release is ready.
