# AffordAbled

**A personal finance app where the AI interprets, and the backend decides.**

AffordAbled combines a wallet interface with a conversational assistant built on LangGraph. Users can record transactions through manual forms, natural-language chat, receipt images, voice, or file import. Chat, receipt, voice, and manual transaction creation use the same transaction service; imports use a separate validated batch path. The language model interprets requests and selects tools, while backend code validates ownership, account balances, categories, and money amounts.

[Product and architecture guide](docs/PROJECT_OVERVIEW_AND_RESUME.md) · [LangGraph architecture](docs/LANGGRAPH_ARCHITECTURE_GUIDE.md)

## Why this exists

Personal finance data can start as a receipt, a bank export, a spoken note, or a chat message. Recording it repeatedly takes effort. Shared bills also require distinguishing who consumed each item, who paid the merchant, who owes whom, and whether a repayment should change the wallet.

AffordAbled brings those workflows together. **Financial arithmetic is performed by application code, not by a language model.**

## What's inside

### Core wallet

- Bank, cash, card, and wallet accounts with initial balances, active status, and a default account.
- User-owned expense and income categories, including starter categories at registration.
- Expense, income, refund, and transfer transactions with balance effects, editing, soft deletion, and restoration.
- CSV/XLSX import with preview, row validation, and confirmation before a batch is committed.
- CSV/XLSX/PDF report export, including report requests through chat.
- Dashboard, profile, transaction history, and responsive mobile views.

### Conversational assistant

- A **LangGraph supervisor** routes tasks to focused transaction, account, category, analytics, split, and export specialists.
- Multi-step requests can be handled in order. For example, “Create an Axis account with ₹6,000, then log ₹999 on food” involves account creation before the expense.
- Typed tool schemas restrict what a specialist can request. Server-side services validate and execute the operation.
- Bounded conversation history, saved tool observations, and verified transaction IDs support follow-ups such as “split that with A and B.”
- Semantic guardrails, bounded tool iteration, and configurable PostgreSQL-backed checkpoints support the workflow. An in-memory checkpoint option is available for development or fallback and is not durable.
- Receipt OCR uses Azure Document Intelligence. Voice uses Azure Speech-to-Text and FFmpeg conversion for supported compressed audio.

### Expense splitting and repayment

- Equal and custom splits track the owner's share separately from external participants.
- Itemized splits allocate priced rows to the people who shared them.
- Quantity-based splits combine fixed items per person with a remainder shared across the group.
- **Expense shares and settlement transfers are separate concepts:** a person's share describes consumption; a transfer describes who must pay whom after contributions and debts.
- Integer-paise calculations reconcile shares to the bill and net balances to zero.
- Standalone “someone owes me” records and repayment flows link owner payments to wallet transactions.

### User-controlled preference memory

- Transaction reviews, split actions, and flagged chat clarifications can create evidence events.
- Database outboxes allow a background worker to process evidence outside the interactive request.
- Event fingerprints prevent the same retry from counting as new evidence.
- A suggestion needs **three distinct evidence events** before it is shown.
- Users can confirm, edit, dismiss, or delete suggestions. Only confirmed memories are supplied to future relevant AI tasks.

## Architecture

```text
React + TypeScript + Vite
        |
FastAPI routers / Pydantic schemas
        |
Application services (finance rules)
        |
  +-----+-------------------+
  |                         |
Domain entities          Infrastructure
and ports                |- SQLAlchemy repositories -> PostgreSQL
                         |- LangGraph supervisor -> Azure OpenAI
                         |- Azure Document Intelligence (OCR)
                         |- Azure Speech-to-Text + FFmpeg
                         '- Background memory worker (database outbox)
```

**Core rule:** Financial writes pass through server-side ownership, validation, and reconciliation rules. Manual and chat transactions use `TransactionService`; CSV/XLSX imports use a separate validated batch workflow. The LLM cannot directly update wallet balances or write arbitrary records.

See the [full product and architecture guide](docs/PROJECT_OVERVIEW_AND_RESUME.md) for a request flow, engineering decisions, code links, demo scenarios, and resume-ready descriptions.

## Tech stack

| Layer | Technologies |
|---|---|
| Frontend | React 19, TypeScript, Vite, Redux Toolkit / RTK Query, Tailwind CSS, React Hook Form, Zod |
| Backend | Python 3.13, FastAPI, Pydantic, async SQLAlchemy, Alembic |
| Database | PostgreSQL for application data; PostgreSQL or in-memory LangGraph checkpoints by configuration |
| AI | LangGraph, LangChain tool calling, Azure OpenAI, optional LangSmith tracing, NeMo guardrails |
| Media and files | Azure Document Intelligence, Azure Speech-to-Text, FFmpeg, CSV/XLSX/PDF tooling |
| Infrastructure | Docker Compose for local services, Azure App Service API workflow, Azure Static Web Apps configuration |

## Local development

### API

From `apps/api`, create a Python 3.13 virtual environment, install dependencies, configure `.env` from `.env.example`, and apply migrations.

**PowerShell**

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

**macOS/Linux**

```bash
cd apps/api
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Configure PostgreSQL in `.env` before running Alembic or the API. Configure Azure OpenAI, OCR, and speech credentials for the features you want to use. Keep `.env` and real credentials out of Git. The API defaults to `http://localhost:8000`; OpenAPI documentation is at `/docs`.

### Web

```bash
cd apps/web
npm install
npm run dev
```

Vite defaults to `http://localhost:5173`. Set `VITE_API_BASE_URL` in a local web `.env` if the API is hosted elsewhere; otherwise it defaults to `http://localhost:8000`.

### Run checks

From `apps/api`:

```text
python -m pytest -q
ruff check .
```

Run all fast agent evaluations with `python scripts/run_agent_evaluations.py` from `apps/api`. The [DeepEval agent regression suite](docs/DEEPEVAL_REGRESSIONS.md) runs in pull requests and before API deployment. Add `--live` to include the Azure model case.

From `apps/web`:

```text
npm run lint
npm run build
```

### Export the LangGraph workflow diagram

From `apps/api`:

```text
python scripts/export_chat_langgraph.py
```

The script writes `apps/api/artifacts/langgraph/agentic_chat_langgraph.mmd`. It uses local stub services and an in-memory checkpointer; exporting the diagram does not connect to Azure or PostgreSQL.

## How a chat turn works

```text
User: “Spent ₹999 on food from Axis”
  -> ChatService receives the authenticated message and thread ID
  -> LangGraph loads bounded context and routes the active task
  -> Transaction specialist calls a typed create_transaction tool
  -> TransactionService checks ownership, category type, and amount
  -> Backend updates the account balance and saves the transaction
  -> Tool returns the verified transaction ID and amount
  -> Graph builds a response and completion state
  -> A later “split that” can use the saved transaction ID
```

The model may misunderstand a request, and providers may fail. The server-side boundary limits the impact of that uncertainty; it does not guarantee every chat turn succeeds.

## Documentation

| Document | What it covers |
|---|---|
| [Product and architecture guide](docs/PROJECT_OVERVIEW_AND_RESUME.md) | Product features, system design, demo scenarios, and resume wording |
| [Project reference](docs/AFFORDABLED_PROJECT_REFERENCE.md) | Component-level reference |
| [LangGraph architecture](docs/LANGGRAPH_ARCHITECTURE_GUIDE.md) | Graph design, specialists, and tool runtime |
| [LangGraph reliability](docs/LANGGRAPH_INTEGRATION_RELIABILITY.md) | Failure modes and recovery design |
| [Transaction files](docs/TRANSACTION_FILES.md) | Import and export behavior |
| [Release checklist](docs/V1_RELEASE_CHECKLIST.md) | Migration, deployment, and acceptance gates |

The group settlement planner is [documented separately](docs/COMPLEX_SETTLEMENTS.md) as current workspace work. Its migration and release gates must be completed before claiming it is deployed.
