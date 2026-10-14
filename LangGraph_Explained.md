# AffordAbled LangGraph — A Practical Walkthrough

_Last updated: 2026-10-14_

This guide describes the **current implementation** of AffordAbled chat: what LangGraph is doing, what the supervisor decides, how transaction and analytics paths work, how state persists between HTTP requests, and what remains outside the current graph.

> **In one sentence:** LangGraph runs a typed, checkpointed workflow. The LLM interprets language and chooses among a small registry of workflows; Python controls graph transitions and tool execution; the database is authoritative for financial facts.

## 1. The basic mental model

Think of LangGraph as a flowchart whose boxes contain Python functions:

- **Graph:** the whole directed workflow.
- **Node:** one step, such as guardrail analysis, supervisor decision, or analytics execution.
- **Edge:** the transition to the next node. A conditional edge chooses from a fixed route map.
- **State:** the shared work-in-progress mapping for one conversation thread.
- **Reducer:** a merge rule. `messages` uses LangGraph’s `add_messages` reducer, so a new turn’s message is appended/merged with the existing messages.
- **Tool:** a registered callable for a bounded operation, such as reading this user’s transactions.
- **Checkpointer:** persistence for graph state between API calls. The same user-scoped thread key loads the previous state.
- **Interrupt:** a deliberate pause for transaction clarification/confirmation; a later turn on the same thread resumes it.

A node reads state and returns only the fields it changes. LangGraph merges that update, follows an edge, then runs the next node. The LLM cannot execute arbitrary Python or invent node names: it returns a structured decision that application code maps to a registered route.

### State fields you will see most often

| Field | Meaning |
|---|---|
| `messages` | User, assistant, and tool-call/result messages for the thread |
| `runtime_user_id` | Authenticated user ID set by the server |
| `runtime_timezone` | Validated IANA timezone for date windows and labels |
| `workflow_action` | Internal route marker such as `supervisor`, `build_proposal`, or `query_transactions` |
| `intent` | Intent classifier output; a hint, not the final workflow choice |
| `pending_proposal`, `hitl_active` | Pending transaction proposal and whether user input is awaited |
| `query_plan` | Current structured analytics plan |
| `last_finance_query_plan` | Last successful finance-query plan |
| `last_finance_query_result` | Last successful structured facts or transaction rows |
| `query_tool_call_ids` | Tool results the analytics finalizer expects to collect |
| `supervisor_handoff_count` | Registered workflows invoked this turn; maximum 3 |
| `supervisor_executed_workflows` | Normalized workflow/argument keys used to prevent repeats |
| `workflow_result` | Bounded typed summary; raw finance rows stay in trusted graph state |
| `pending_supervisor_question` | Clarification the next same-thread reply answers |
| `active_workflow_id` | Registered specialist currently being observed |

State is workflow context, not the transaction database. Totals and transaction rows come from database-backed services/tools. `last_finance_query_result` is checkpointed to support follow-ups; retention and data minimization must account for this stored transaction detail.

## 2. Current top-level graph

The diagram groups some Python nodes into readable workflow blocks. The routing note below explains one important detail: formatting goes through the analytics planner before reaching the formatter.

```mermaid
flowchart TD
    U[User message] --> API[Chat API authenticates user]
    API --> CK[Load checkpoint for user-scoped thread]
    CK --> PRE[Deterministic preflight]

    PRE -->|Pending proposal or active HITL| TX[Transaction flow resumes]
    PRE -->|Clear transaction shortcut enabled| TX
    PRE -->|Otherwise| SAFE[Guardrail and intent classification]
    SAFE -->|Hard block| REF[Safe refusal]
    SAFE -->|Eligible| SUP[LLM supervisor chooses structured action]

    SUP -->|run_workflow| DISP[Validate registry, args, budget, repeat guard]
    DISP -->|Allowed| SPECIALIST[Run one registered specialist]
    SPECIALIST --> OBS[Validate and summarize typed result]
    OBS -->|Successful read, budget remains| SUP
    OBS -->|Needs input, failure, transaction proposal, or budget exhausted| OUT
    SUP -->|ask_user| ASK[Checkpointed interrupt]
    ASK -->|Same-thread reply| CK
    SUP -->|finish| OUT
    SUP -->|refuse| REF

    SPECIALIST -->|Transaction| CTX[Load user's accounts and categories]
    CTX --> EX[Extract transaction candidate]
    EX --> EVAL[Validate fields and confidence]
    EVAL -->|Need details| HITL[Ask using graph interrupt]
    HITL -->|Same-thread reply resumes| EX
    EVAL -->|Ready| CARD[Return proposal]
    CARD -->|Explicit confirmation| WRITE[TransactionService writes]
    CARD -->|Edit or cancel| TX
    WRITE --> OUT[Workflow result]

    SPECIALIST -->|Analytics or format request| PLAN[LLM analytics planner]
    PLAN -->|Category unclear| ASK[Ask for clarification]
    PLAN -->|New query or drill-down| ORCH[Analytics query orchestrator]
    ORCH --> TOOLS[Registered user-scoped query tools]
    TOOLS --> FACTS[Database-derived totals or rows]
    FACTS --> FINAL[Fact-check reply and save structured result]
    FINAL --> OUT
    PLAN -->|format_previous| FORMAT[Sort/render saved rows without a DB query]
    FORMAT --> OUT

    DISP -->|Invalid, repeated, blocked, or over limit| ANSWER[Safe bounded exit]
    REF --> OUT
    ANSWER --> OUT
    OUT --> SAVE[Checkpoint updated messages and state]
    SAVE --> UI[Return response to frontend]
    UI -->|Next turn with same thread ID| CK
```

### The exact analytics route

Formatting an earlier result does **not** go directly from supervisor to formatter:

```text
supervisor chooses format_previous
  → Python maps it to the registered analytics route
  → query_planner sees the previous structured result
  → query_planner emits action=format_previous
  → _route_after_query_plan selects format_previous_result
  → formatter sorts/renders saved rows without calling the database
```

This separates **which capability handles the request?** (supervisor) from **what query/presentation action should analytics perform?** (analytics planner).

### Main graph nodes

| Node | Responsibility |
|---|---|
| `analyze_turn` | Pending proposal/HITL preflight, optional transaction shortcut, guardrail, intent hint |
| `supervisor` | Choose a registered workflow action using bounded context and the latest typed result |
| `workflow_dispatch` | Validate the workflow registry, empty arguments, handoff budget, repeat guard, and block state |
| `workflow_observer` | Validate specialist outcome and build a bounded `WorkflowResult` summary |
| `supervisor_ask_user` / `supervisor_finish` | Pause for clarification or finish the current turn |
| `populate_user_context` | Load authenticated user’s active accounts/categories for transaction handling |
| `extract_transaction_candidate` | Extract a transaction candidate; does not write it |
| `evaluate_transaction_candidate` | Validate completeness/confidence and choose clarification or proposal flow |
| `hitl_clarification` | Pause with `interrupt()` for missing transaction details |
| `transaction_flow` | Present/edit/cancel/confirm proposal; write only after confirmation |
| `query_planner` | Interpret query kind, period, categories, follow-up, and formatting action |
| `query_orchestrator` | Build one or more registered query-tool calls |
| `query_tool_executor` | Execute registered summary/transaction query tools |
| `query_tool_finalize` | Combine facts, validate reply, and save prior result |
| `format_previous_result` | Sort/render saved rows without a new database query |
| `assistant_default` / `assistant_refusal` | Safe response or refusal |

## 3. What happens on each API turn

### Step 1 — Start or resume a thread

The chat API authenticates the user and sends the orchestrator the message, application thread ID, and optional browser timezone. The orchestrator prefixes the thread ID with the authenticated user ID, loads its checkpoint, then adds a `HumanMessage`.

If a checkpoint contains a LangGraph interrupt, the new message resumes that node. Otherwise, it is a regular graph input. The frontend needs to send the same returned thread ID for continuity.

The app also stores SQL chat-thread/message history for product listing and display. That is distinct from LangGraph checkpointing: SQL history is product history; the checkpoint restores execution state.

### Step 2 — Preflight and safety

Before asking the supervisor, `analyze_turn` handles deterministic ongoing work:

1. A pending proposal reply becomes confirm, cancel, edit, or wait—not a new unrelated workflow.
2. Active transaction clarification resumes extraction or accepts cancellation.
3. If enabled, a clear current message containing a transaction action and amount can use the deterministic transaction shortcut.
4. Otherwise the guardrail and intent classifier examine the current message with bounded recent context.
5. A hard guardrail block refuses before supervisor dispatch. Eligible turns go to the supervisor.

Intent is an **input hint**, not the final workflow choice.

### Step 3 — Supervisor decision

The supervisor calls the LLM with a structured `SupervisorAction`:

- `action`: `run_workflow`, `ask_user`, `finish`, or `refuse`
- `workflow_id`: required only for `run_workflow`; one registered capability
- `arguments`: must be empty while workflows consume authenticated turn/checkpoint state
- `confidence`: confidence in its route
- `rationale`: short explanation for diagnostics
- `response`: optional safe clarification/final message

Python checks the action, workflow allowlist, empty argument contract, hard guardrail, per-turn handoff budget, and repeat-call key before dispatch. The prompt explicitly says split, memory, account-balance specialist, and file-export workflows are not registered yet. The model cannot create them by naming them.

Supervisor calls have a 30-second timeout. If a call fails, times out, or confidence is below `0.55`, Python uses a restricted fallback to a registered workflow or safe finish/refusal. The enum is mapped to fixed graph routes; the LLM never supplies an executable node name.

### Step 4 — Specialist workflow

The supervisor dispatches one workflow at a time. Each specialist returns to a deterministic observer, which validates a `WorkflowResult` (`workflow_id`, `status`, bounded summary, data reference, and side-effect class). A successful read workflow may return control to the supervisor for a second distinct capability. The loop stops on user input, failure, transaction proposal/commit, or the three-handoff limit.

#### Transaction example

User: “I spent ₹500 at Cafe Roma today.”

1. Load this user’s accounts and categories.
2. Extract fields and validate account/category/completeness/confidence.
3. If required details are missing or uncertain, pause with an interrupt and ask.
4. Return a proposal for review.
5. Only explicit confirmation invokes `TransactionService` to write the transaction.

The LLM proposes; application validation and HITL decide whether anything is committed.

#### Analytics example

User: “How much did I spend this month on Food and Travel?”

1. The planner returns a structured plan: summary, `this_month`, categories `[Food, Travel]`, timezone, confidence.
2. The query orchestrator creates one category-scoped summary call per selected category.
3. Tools resolve category IDs/date boundaries and query only the authenticated user’s transactions.
4. The database supplies totals/counts. The reply LLM may phrase them, but fact validation rejects changed or omitted required values.
5. Finalization saves the plan and structured facts/rows in graph checkpoint state.

#### Follow-up example

After a monthly summary, the user asks **“Where?”**. The supervisor selects analytics; the planner inherits the previous month/category scope and requests matching expense rows.

Then the user asks **“Sort these by date and show me in a table.”** The supervisor selects `format_previous`. The planner emits `action=format_previous`, then Python routes to the deterministic formatter. It sorts saved rows and renders the table—no second database query and no LLM rewrite of row values.

## 4. Message sequence

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant API as FastAPI Chat API
    participant Graph as LangGraph
    participant CP as Checkpointer
    participant Guard as Guardrail and intent
    participant Sup as Supervisor
    participant Plan as Analytics planner
    participant Tools as Query tools
    participant DB as Database
    participant UI as Frontend

    User->>API: Message, thread ID, timezone
    API->>Graph: Authenticated user ID and HumanMessage
    Graph->>CP: Load user-scoped checkpoint
    CP-->>Graph: Messages and workflow state
    Graph->>Graph: Preflight proposal, HITL, transaction shortcut
    Graph->>Guard: Guardrail and intent hint
    Guard-->>Graph: Block, allow, or needs-classification
    alt Hard guardrail block
        Graph-->>API: Safe refusal
    else Eligible request
        Graph->>Sup: Current message, recent context, prior result
        Sup-->>Graph: run_workflow / ask_user / finish / refuse
        alt run_workflow
            Graph->>Graph: Validate allowlist, args, handoff limit, repeat guard
            Graph->>Graph: Execute one fixed specialist route
            Graph->>Sup: Bounded typed workflow result
            opt Successful read and budget remains
                Sup-->>Graph: Select next distinct registered workflow or finish
            end
        else ask_user
            Graph-->>API: Checkpointed clarification interrupt
            User->>API: Answer on same thread
            API->>CP: Resume supervisor checkpoint
        else Transaction workflow
            Graph->>DB: Load scoped account/category context
            Graph-->>User: Proposal or clarification interrupt
            User->>API: Confirm, edit, or cancel on same thread
            API->>CP: Resume graph checkpoint
            Graph->>DB: TransactionService write after explicit confirmation
        else Analytics workflow
            Graph->>Plan: Interpret query or follow-up
            Plan->>Tools: Build registered query calls
            Tools->>DB: Read user-scoped finance data
            DB-->>Tools: Computed totals or rows
            Tools-->>Graph: Facts and tool result
            Graph->>Plan: Finalize, fact-check, save prior result
        else Format previous result
            Graph->>Plan: Select format_previous action
            Plan-->>Graph: Route to deterministic formatter
            Graph-->>Graph: Sort and render saved rows without a DB call
        else finish or refuse
            Graph-->>Graph: Safe final response or refusal
        end
    end
    Graph->>CP: Save messages and updated state
    Graph-->>API: Response, proposal, or insights
    API-->>UI: JSON response
    UI-->>User: Assistant message or table
```

## 5. What the LLM does vs. Python

| LLM responsibilities | Application/LangGraph responsibilities |
|---|---|
| Classify intent as a hint | Authenticate; establish user/thread identity |
| Choose a registered supervisor workflow | Enforce guardrail blocks, fixed routes, and ownership |
| Interpret dates/categories/query kind/follow-up action | Resolve IDs/date windows; execute user-scoped tools |
| Phrase a response from computed facts | Calculate totals/counts and validate required facts |
| Suggest transaction fields | Validate proposal and require explicit confirmation before writes |
| Select table/list presentation intent | Sort/render saved rows while preserving exact facts |

Language understanding can be probabilistic; financial writes and financial numbers remain application/database responsibilities.

## 6. Limits of the current supervisor

- It is a **bounded coordinator**, not an unrestricted agent. A turn invokes at most three registered workflows, and repeated calls are rejected.
- It only knows registered workflows. Split, long-term memory, account-balance specialist, and file-export specialist are not available in chat yet.
- Analytics runs its own query planner/orchestrator after the high-level supervisor choice.
- Only implemented workflows are registered; there is no analytics → file-export handoff because file export is not implemented.
- A supervisor choice never grants arbitrary function access, user IDs, or direct database writes.

## 7. Safety and failure behavior

- **User isolation:** checkpoint IDs include authenticated user scope; tools obtain identity from trusted graph state.
- **Guardrails:** an explicit block exits before the supervisor. Contextual uncertainty can be evaluated with prior conversation.
- **Transaction writes:** a proposal is not committed until explicit user confirmation.
- **Financial facts:** tools calculate; LLM prose is checked against required amounts/counts/rows.
- **Unsupported workflow:** fixed enum/routing prevents arbitrary node selection; respond that a capability is unavailable rather than inventing a result.
- **LLM failure/low confidence:** restricted fallback chooses only registered workflows.
- **Interrupt/resume:** HITL pauses the graph and resumes on the same thread.
- **Checkpoint privacy:** prior analytics rows are saved for follow-ups. Production data-retention/deletion policy must cover checkpoint data.

## 8. Testing and inspection

### Automated tests

Backend tests use stubbed structured LLM decisions for deterministic routing. They cover supervisor selection/fallback, guardrail precedence, user/thread history, monthly summary → “where?” → table, and formatting from saved rows.

Run in `apps/api`:

- `pytest -q tests/test_chat.py` — graph, supervisor, and follow-up tests
- `pytest -q` — full backend suite
- `ruff check .` — backend lint

Run in `apps/web`:

- `npm run lint`
- `npm run build`

The graph-node acceptance test proves deterministic state transitions; it does not replace an opt-in HTTP test against the configured real model and PostgreSQL checkpointer.

### Inspect a traced turn

`LangGraphChatOrchestrator.graph_mermaid()` returns Mermaid for the compiled graph. `save_graph_assets()` writes graph assets to `apps/api/artifacts/langgraph/`; generated files can become stale, so Python graph construction is authoritative.

For a turn, inspect these fields without logging raw sensitive content:

1. User-scoped thread ID.
2. Preflight action and guardrail decision.
3. Supervisor workflow, confidence, rationale, and fallback use.
4. Query plan action, period, and category scope.
5. Registered tool names and sanitized arguments.
6. Tool result count and fact-validation outcome.
7. Whether structured results were checkpointed and which node produced the reply.

## 9. Source-code map

- State and supervisor decision schema: [langgraph_chat_orchestrator.py](apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py#L297)
- Graph registration and edge wiring: [langgraph_chat_orchestrator.py](apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py#L590)
- Checkpoint load/resume and invocation: [langgraph_chat_orchestrator.py](apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py#L716)
- Preflight and supervisor handoff: [langgraph_chat_orchestrator.py](apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py#L804)
- Supervisor call and workflow mapping: [langgraph_chat_orchestrator.py](apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py#L911)
- Analytics planning/orchestration: [langgraph_chat_orchestrator.py](apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py#L1659)
- Prior-result formatter: [langgraph_chat_orchestrator.py](apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py#L1869)
- Query result finalization: [langgraph_chat_orchestrator.py](apps/api/app/infrastructure/ai/langgraph_chat_orchestrator.py#L1974)
- Database analytics tools: [langgraph_finance_tools.py](apps/api/app/infrastructure/ai/tools/langgraph_finance_tools.py)
- Shared frontend table renderer: [AssistantMessageContent.tsx](apps/web/src/components/molecules/AssistantMessageContent/AssistantMessageContent.tsx)

## 10. Current status and next steps

The single-dispatch supervisor and category workflow are merged to `main` in PR #9. The bounded multi-step loop is being developed on `feature/langgraph-multi-step-supervisor`. The action/dispatcher/observer loop and same-thread clarification resume have focused test coverage, and Ruff passes. A full backend run was interrupted during execution, so a clean complete-suite result is still outstanding. Remaining checks include a clean full-suite pass, regenerated graph asset review, checkpoint retention/data-minimization documentation, and optionally a live-model/PostgreSQL integration pass before PR review/merge.
