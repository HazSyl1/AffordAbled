# Application latency evaluation

Measure a baseline before changing the response path. p50 is the median: half of
successful actions finish within this time. p99 describes the slow tail: 99% of
successful actions finish within this time. Always inspect errors alongside these
percentiles; failing quickly is not a performance improvement.

## What the benchmark measures

Run `scripts/evaluate_latency.py` from `apps/api` against a running application.
It uses the existing HTTPX dependency and never imports the application or opens
the database. The default scenarios read accounts, transactions, categories,
splits, person balances, chat threads and recurring transactions. Use a dedicated
test account with a realistic data volume: an empty account is not a useful
baseline for expensive list/balance queries.

Each report contains p50/p95/p99 for successful actions, sample count, error rate,
individual attempt timings, request IDs, warmup failures and run metadata. Failed
and timed-out attempts remain in the JSON, with an additional all-attempt p99.
The command exits nonzero if any attempt or warmup fails. No latency deployment
gate is enabled; establish repeatable baselines first.

Chat is opt-in because it creates persistent turns/threads and incurs LLM usage.
Each sample submits a fresh turn, polls the durable job to a terminal state and
requires a nonempty answer. A `202 queued` response alone is never a successful
chat sample. Repeat `--chat-message` to measure a sequential multi-turn conversation
on the same thread; its reported latency covers the entire conversation.

The separate chat submit timing measures acknowledgement. Completed jobs also
return their claim and completion timestamps, so the report now includes queue
wait and worker processing timings. Client completion time includes network
trips and polling delay. The default 1.5-second poll interval matches the
visible browser's chat polling interval.

The worker is woken immediately after a turn is queued within the same API
process; the configured two-second poll remains a recovery path for restarts or
multi-process hosting. Structured logs include `chat.turn.claimed` with
`queue_wait_ms`, `chat.turn.succeeded` with `processing_ms`, and LangGraph
guardrail, supervisor, specialist-LLM and tool timings. Use the turn ID to
correlate them with LangSmith.

When the chat is visible, the web client also opens an authenticated fetch-based
SSE stream at `/chat/turns/{turn_id}/events`. It receives state changes as soon
as the local worker publishes them and rechecks the database once per second for
process/restart recovery. If streaming fails or the app is hidden, it returns to
the durable status polling path. Native `EventSource` is not used because it
cannot send the Bearer authorization header.

## Local first

Start the API with the normal local configuration and use a dedicated test
account. The benchmark can log in for you, so keep credentials in environment
variables and never put them in command arguments, reports or Git. It supports a
short-lived access token when one is already available, or logs in with the test
account's email and password when no token is set. Credentials are used only for
the login request and are never written to the report.

```powershell
cd AffordAbled/apps/api
$env:PERF_EMAIL = 'latency-test@example.com'
$env:PERF_PASSWORD = '<test-account-password>'
python scripts/evaluate_latency.py --samples 100 --concurrency 1 --revision '<git-sha>'
```

For Azure, set the same variables in the local shell and add `--base-url
'https://<api-host>' --allow-remote`. Use a dedicated account and rotate its
password after a shared or temporary test session.

Reports are written to `.performance/<UTC timestamp>/report.json` and `report.md`
(ignored by Git). Defaults use three warmup requests per scenario, excluded from
the measured percentiles. Keep cold-start measurements separate: use `--warmup 0`
immediately after a deliberate restart, and label the run accordingly. The script
does not restart any services.

Start chat with a small, separately labelled run to control model usage:

```powershell
python scripts/evaluate_latency.py --scenarios chat --allow-chat --samples 10 --warmup 1 --concurrency 1
python scripts/evaluate_latency.py --scenarios chat --allow-chat --samples 10 --warmup 1 --chat-message 'What are my account balances?' --chat-message 'What did I spend this month?'
```

Use only read-only finance questions in a test account. The benchmark does not
confirm transactions, send email, settle balances or clean up its chat records.
The account's normal quotas apply, including warmups and every conversational
turn. A timeout does not cancel a job: it may still finish in the background.

After checking the first report, repeat with concurrency 3 and then 5. This is a
closed workload: each client waits for an action to finish before submitting its
next action. It measures latency at bounded simultaneous demand, not capacity
under a fixed arrival rate. Scenarios execute separately, so results identify
individual actions rather than a mixed traffic profile.

For a credible p99 investigation, collect at least 1000 successful samples per
action across repeatable runs. This is a practical minimum, not a confidence
guarantee. A 10-sample chat p99 is essentially its slowest sample and must be
treated as exploratory. Do not silently remove slow samples or average the p99
values from several runs; recompute percentiles from their raw matching samples.

## Azure follow-up and comparisons

After the local baseline, use an Azure test account and explicitly enable remote
requests. Keep concurrency 1 initially and increase only after inspecting errors
and resource usage. Remote runs require HTTPS.

```powershell
python scripts/evaluate_latency.py --base-url 'https://<api-host>' --allow-remote --environment azure --samples 100 --concurrency 1 --revision '<deployed-sha>'
```

Record matching dataset size, deployment SHA, model deployment, region, runner
location and service tier with the retained report. Keep warm/cold, read API,
single-turn chat and multi-turn chat reports separate. Match these conditions
when comparing before/after optimization. Run from the same machine/location.

Use the existing `request.completed` JSON logs (`duration_ms`, `request_id`) to
correlate slow HTTP requests. Use LangSmith to inspect the slow chat turn's model
and tool steps; the job ID is available in the status polling URL. Benchmark
reports never include tokens, request/response bodies or prompt text. Treat
request IDs as operational data and restrict access to reports.

Prioritize changes using evidence: slow lists/balances warrant database query
inspection; slow submission-to-answer with fast HTTP requests warrants queue and
LangGraph inspection. Compare the same workload again after one optimization,
requiring no increase in failures or regression in financial correctness. Do not
set universal latency targets before seeing representative measurements.

## Next coverage

These are API and durable-chat timings, not click-to-render browser timings.
Follow with browser measurements of navigation, save-to-visible transaction,
split creation/editing and balance settlement using isolated fixtures and cleanup.
Measure reminder queue acknowledgement separately from ACS acceptance and inbox
delivery; an email `202` is not delivery latency. Voice and receipt uploads need
fixed sanitized files and explicit provider budgets. Keep these paid/write-heavy
scenarios opt-in before extending the harness.
