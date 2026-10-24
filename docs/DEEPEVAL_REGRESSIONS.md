# Agent regression evaluations

Run the evaluation gate from `apps/api` after changing chat, LangGraph, finance tools, memory, or split logic:

```powershell
python scripts/run_agent_evaluations.py
```

On Windows, the wrapper can be run from anywhere inside the repository. It automatically uses
`apps/api/.venv/Scripts/python.exe` when that virtual environment exists:

```powershell
.\apps\api\scripts\run_deepeval.ps1
```

The command runs deterministic DeepEval goldens, guardrail decisions, and focused API tests. It prints a pass/fail count for each area, any failing case and its traceback, then a final total and `Result: PASS` or `Result: FAIL`. It exits with code 1 if any area fails. Add `--verbose` to print every passing case. The same gate runs on API pull requests and before API deployment.

| Area in summary | What it checks |
| --- | --- |
| Agent goldens and exact financial outcomes | A task completes only with a successful tool observation; follow-up splits use a verified transaction ID; ambiguous IDs require selection; quantity, itemized, and settlement splits reconcile in paise; contributions and existing debts affect settlement transfers; category edits and split participants yield the right memory candidates; date windows use the user's timezone. |
| Guardrail decisions | Finance requests, unrelated requests, and unsafe requests follow expected guardrail decisions. |
| Chat orchestration, task evidence, and thread history | Supervisor routing, task queues, receipt consent, category clarification, verified salary and analytics answers, chat API writes, and thread persistence. |
| Expense splits and settlement arithmetic | Equal and itemized splits, receipt rows and taxes, multiple quantity allocations, coupons, fees, payer roles, debts, draft review, and plan edits. |
| Spending queries and date filters | User-scoped query results, largest transaction ordering, account/category filters, aggregates, and local date windows. |
| Memory capture and review | Chat clarification signals, extraction evidence, edits, outbox creation, and user-scoped suggestions. |
| Voice transcription handoff | Audio input validation and transcription service behavior. |

The exact-value goldens live in `apps/api/tests/goldens/agent_regressions.json`; their evaluator is `apps/api/tests/test_deepeval_agent_regressions.py`. They use real application functions with a deterministic DeepEval metric, so a model cannot make an incorrect number look correct by wording its answer differently. The other areas run existing pytest API and service tests. Tests that need persistence use an isolated SQLite database supplied by pytest fixtures. The default run does not call Azure or write to production PostgreSQL.

## Optional live Azure evaluation

```powershell
python scripts/run_agent_evaluations.py --live
```

The equivalent Windows command is:

```powershell
.\apps\api\scripts\run_deepeval.ps1 -Live
```

Add `-Verbose` to either wrapper command to list every test case. The Python equivalent is `--verbose`.
For a quicker paid-model iteration that skips the deterministic suite, run:

```powershell
.\apps\api\scripts\run_deepeval.ps1 -LiveOnly -Verbose
```

or, from `apps/api`:

```powershell
python scripts/run_agent_evaluations.py --live-only --verbose
```

This adds six end-to-end chat cases using the configured Azure model:

1. Record one salary transaction and return its real persisted ID.
2. Record and equally split one dinner in a single turn. This checks task completion, popup state, transaction ID linkage, duplicate prevention, exact ₹402 shares, total reconciliation, and a coherent final answer.
3. Interpret a quantity-based split with a contribution and two existing debts, pause for confirmation, resume the same graph, and save exact expense shares and net settlement transfers. This checks all arithmetic in paise, preserved source adjustments, one transaction across both turns, and the absence of the verification fallback.
4. Create an equal split on a follow-up turn without recreating its expense.
5. Log one receipt grand total without creating a split or one transaction per receipt line.
6. Answer a largest-expense query from saved data without writing another transaction.

Every case calls the public FastAPI chat endpoint and therefore exercises authentication, the supervisor,
specialists, tools, LangGraph checkpoint/resume behavior, repositories, and response mapping. Assertions inspect
the saved API state as well as the assistant response. Each test has its own isolated SQLite wallet; it does not
write to local or production PostgreSQL.

The live cases use two DeepEval metrics:

- `ExactJsonMetric` requires an exact structured result.
- `BooleanCriteriaMetric` scores a set of named workflow invariants. Its failure reason includes the criterion,
  expected value, and observed value, which makes a model regression easier to locate.

The Azure model performs extraction and routing, but a second LLM does not judge the result. Financial values,
IDs, counts, links, and task completion are checked deterministically against the database and API response. This
prevents fluent wording from hiding a wrong amount or duplicate write.

When a live criterion fails, the runner prints `Failure artifacts:` followed by a directory under
`apps/api/.deepeval-results/`. Each JSON artifact contains the failed criteria with expected and observed values,
the chat response bodies, and the transaction and split snapshots read after the workflow. Authentication headers,
Azure credentials, and environment variables are never written. The directory is ignored by Git. When running the
test directly with pytest, artifacts are written to `apps/api/.deepeval-results/direct-pytest/`.

The live run makes paid model calls and needs `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and either
`AZURE_OPENAI_EXTRACTION_DEPLOYMENT` or `AZURE_OPENAI_DEPLOYMENT`. It is deliberately outside CI because model
behavior and Azure availability can change independently of a code commit.

The focused gate covers the listed scenarios, not every possible conversation or frontend behavior. When a new failure is found, add its exact inputs and required database outcome to a golden or focused test. Run the frontend build separately from `apps/web` with `npm run build` after UI changes.
