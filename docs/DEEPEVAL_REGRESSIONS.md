# Agent regression evaluations

The DeepEval suite protects the LangGraph boundaries that previously caused incorrect chat outcomes. Golden cases in `apps/api/tests/goldens/agent_regressions.json` cover completion only after successful tool evidence, verified transaction IDs in split follow-ups, ambiguity when several transactions were created, and exact paise reconciliation for quantity splits. The guardrail script checks a small set of finance and off-topic decisions. These checks use real application functions and deterministic DeepEval metrics; they do not call an LLM or a database.

Run the fast checks from `apps/api`:

```powershell
python -m pytest -q tests/test_deepeval_agent_regressions.py
python scripts/run_deepeval_guardrail_eval.py
```

They run on API pull requests and before the API deployment job stages an artifact. A failing check stops that deployment job. Add a golden when fixing a new agent regression, then run the focused test and existing related API tests.

An optional live case sends a salary request through the actual chat API and Azure model. It verifies that exactly one income transaction was stored and that the response reports its real ID as completed. The test fixture creates a private in-memory SQLite database; it does not write to the configured PostgreSQL database. It makes paid Azure OpenAI calls and is not part of the automatic CI gate.

```powershell
$env:RUN_DEEPEVAL_LIVE = "1"
python -m pytest -q tests/test_deepeval_agent_regressions.py -k live_salary
Remove-Item Env:RUN_DEEPEVAL_LIVE
```

The live run needs `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and an Azure deployment setting in the API environment. Deterministic cases guard arithmetic and state handling; the live case checks one model behavior. Neither set proves every possible conversation will work, so new reported failures should become focused regression cases.
