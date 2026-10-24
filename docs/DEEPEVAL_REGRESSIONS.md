# Agent regression evaluations

Run the evaluation gate from `apps/api` after changing chat, LangGraph, finance tools, memory, or split logic:

```powershell
python scripts/run_agent_evaluations.py
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

This adds four end-to-end chat cases using the configured Azure model: record one salary transaction and report its real ID; create an equal split on a follow-up turn without duplicating the expense; log one receipt grand total without making a split; and answer a largest-expense query without writing a transaction. Every case checks saved API state, not just the assistant's prose. Each test has its own isolated SQLite wallet. The live run makes paid model calls and needs `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and an Azure deployment setting. It is deliberately outside CI because model behavior and Azure availability can change independently of a code commit.

The focused gate covers the listed scenarios, not every possible conversation or frontend behavior. When a new failure is found, add its exact inputs and required database outcome to a golden or focused test. Run the frontend build separately from `apps/web` with `npm run build` after UI changes.
