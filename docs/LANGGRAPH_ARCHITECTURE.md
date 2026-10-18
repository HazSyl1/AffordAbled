# AffordAbled LangGraph Chat Architecture

## Overview

AffordAbled uses a **bounded supervisor pattern** with LangGraph for its chat-based personal finance assistant. The architecture ensures:

1. **Safety** - Financial writes use explicit confirmation for transaction creation and other consequential mutations
2. **Bounded execution** - Max 3 workflow handoffs per turn, no infinite loops
3. **Database authority** - All financial facts come from DB, never LLM calculation
4. **User isolation** - Authenticated user_id injected server-side, never from LLM

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER MESSAGE                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ANALYZE_TURN (Preflight)                           │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │ 1. Pending proposal? → Handle confirm/cancel/edit                       ││
│  │ 2. Active capture session? → Resume via interrupt                       ││
│  │ 3. Multi-row batch detected? → Route to batch extraction                ││
│  │ 4. Deterministic transaction shortcut? → Fast path                      ││
│  │ 5. Guardrail assessment (semantic + keyword)                            ││
│  │ 6. Intent classification                                                ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
              ┌──────────┐    ┌──────────┐    ┌──────────┐
              │  BLOCK   │    │SHORTCUT  │    │SUPERVISOR│
              │(Refusal) │    │(Direct)  │    │(Dispatch)│
              └──────────┘    └──────────┘    └──────────┘
                                                   │
                                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SUPERVISOR NODE                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │ Decides ONE action per iteration:                                       ││
│  │  • run_workflow(id) - Execute a registered workflow                     ││
│  │  • ask_user - Pause for clarification (interrupt)                       ││
│  │  • finish - Complete the turn                                           ││
│  │  • refuse - Off-topic/blocked content                                   ││
│  │                                                                          ││
│  │ Registered: transaction | analytics | account_management               ││
│  │ | category_management | transaction_management | format_previous       ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          WORKFLOW_DISPATCH (Gate)                            │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │ Code-level validation (not LLM):                                        ││
│  │  • Is workflow_id in registered set?                                    ││
│  │  • Has this workflow already run this turn? (no-repeat)                 ││
│  │  • Under handoff limit? (max 3)                                         ││
│  │  • Arguments empty? (workflows read state directly)                     ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
         ▼                           ▼                           ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   TRANSACTION   │      │    ANALYTICS    │      │    CATEGORY     │
│     WORKFLOW    │      │    WORKFLOW     │      │   MANAGEMENT    │
└─────────────────┘      └─────────────────┘      └─────────────────┘
         │                           │                           │
         ▼                           ▼                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SPECIALIST IMPLEMENTATIONS                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Workflow Details

### 1. Transaction Workflow (Capture Agent Pattern)

The transaction workflow uses a **tool-calling capture agent** that drives its own conversation:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     TRANSACTION CAPTURE AGENT                                │
│                                                                              │
│  System: "Capture a single transaction. Call exactly ONE tool per turn."    │
│                                                                              │
│  Available Tools:                                                            │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ propose_transaction(type, amount, date, account?, category?, ...)      │ │
│  │   → Validates against REAL database (accounts, categories exist)       │ │
│  │   → Returns {ok: true, candidate} or {ok: false, error, options}       │ │
│  │   → NEVER writes to DB - only builds a proposal                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ ask_user(question)                                                     │ │
│  │   → Pauses via LangGraph interrupt()                                   │ │
│  │   → User reply resumes directly here, NOT back through supervisor      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ finish_turn(message)                                                   │ │
│  │   → Ends capture (unsupported request, user wants to stop)             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Turn Limit: 5 (after which → manual form fallback)                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼ (on successful proposal)
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TRANSACTION_FLOW (HITL Gate)                          │
│                                                                              │
│  Proposal is NEVER auto-committed. User must:                                │
│   • "confirm" → Write to database                                            │
│   • "cancel" → Discard proposal                                              │
│   • "edit" → Update proposal fields                                          │
│                                                                              │
│  This is the ONLY place create_transaction is called.                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2. Analytics Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ANALYTICS WORKFLOW                                   │
│                                                                              │
│  ┌──────────────────┐     ┌────────────────────┐     ┌──────────────────┐  │
│  │   QUERY_PLANNER  │ ──► │  QUERY_ORCHESTRATOR│ ──► │    DB TOOLS      │  │
│  │   (LLM interprets│     │  (Tool-calling)    │     │  (Deterministic) │  │
│  │    user request) │     │                    │     │                  │  │
│  └──────────────────┘     └────────────────────┘     └──────────────────┘  │
│                                                              │              │
│  Query Kinds:                                                ▼              │
│   • summary - "How much did I spend?"          ┌────────────────────────┐  │
│   • transaction_list - "Show my expenses"      │  COMPUTED FACTS (JSON) │  │
│   • account_balance - "What's my balance?"     │  ────────────────────  │  │
│   • spending_by_account - "Breakdown by card"  │  total_amount: 15000   │  │
│   • compare_periods - "vs last month"          │  transaction_count: 12 │  │
│                                                │  categories: [...]     │  │
│  All numbers come from DB aggregation,         └────────────────────────┘  │
│  NOT from LLM calculation.                               │              │
│                                                          ▼              │
│                                                ┌────────────────────────┐  │
│                                                │  LLM_QUERY_REPLY       │  │
│                                                │  (Compose natural      │  │
│                                                │   response from facts) │  │
│                                                └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3. Category Management Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      CATEGORY MANAGEMENT WORKFLOW                            │
│                                                                              │
│  Handles: create, rename, and delete category requests                       │
│                                                                              │
│  Uses LLM parsing chain (CategoryManagementRequest) to extract:              │
│   - operation: create | rename | delete                                      │
│   - category_name: extracted from user message                               │
│   - category_type: expense or income                                         │
│                                                                              │
│  Flow:                                                                       │
│   1. Parse request with LLM chain                                            │
│   2. Resolve existing categories by exact owned name                         │
│   3. If name missing -> ask "What should the new category be called?"        │
│   4. If type unclear -> ask "Should X be expense or income?"                 │
│   5. Validate: not duplicate, plausible name                                 │
│   6. Create/rename through the service; delete only after confirmation       │
│                                                                              │
│  Clarification uses LangGraph interrupt() for multi-turn conversation.       │
│  Delete warns that historical transactions lose the category link.          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4. Account and Transaction Management

- Account management supports create, rename, set-default, activate, and deactivate. Creation and deactivation use the generic mutation-confirmation gate.
- Category management supports create, rename, and confirmed deletion. Deletion warns that historical transactions lose the category link.
- Transaction management supports edit, soft-delete, and restore. All three operations require confirmation and revalidate ownership in the application service.
- Transaction selection is deterministic: an exact ID, the latest transaction, or a unique amount match. Ambiguous matches cause a clarification instead of a write.
- Transaction edits and deletion/restoration update account balances through `TransactionService`.

The generic `pending_mutation` checkpoint stores a bounded proposal (`entity`, `operation`, owned target ID, validated payload, and human-readable summary). A later confirm/cancel turn executes or discards it. The authenticated user ID always comes from server state.

### 5. Format Previous Result

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FORMAT_PREVIOUS WORKFLOW                                │
│                                                                              │
│  Handles: "Show that as a table", "Sort by date"                             │
│                                                                              │
│  Uses STORED results from prior analytics query.                             │
│  NO new database query - just reformats existing data.                       │
│                                                                              │
│  Preserves: date range, category scope, computed totals                      │
│  Changes: presentation (table/list), sort order                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Safety Invariants

### 1. Bounded Execution
```python
_MAX_SUPERVISOR_HANDOFFS = 3  # Per user turn
_REGISTERED_SUPERVISOR_WORKFLOWS = frozenset({
    'transaction', 'analytics', 'account_management', 'category_management',
    'transaction_management', 'format_previous'
})
```

### 2. No Repeated Workflows
```python
# In _workflow_dispatch_node:
workflow_key = json.dumps([workflow_id, arguments], sort_keys=True)
if workflow_key in executed_workflows:
    return {'supervisor_action': 'finish', ...}  # Stop, don't loop
```

### 3. User ID Injection
```python
# User ID comes from authenticated request, NEVER from LLM arguments
user_id = self._user_id_from_state(state)  # Server-injected
# NOT: user_id = tool_args.get('user_id')  # Never trust model
```

### 4. Mutation HITL
```python
# The ONLY place a transaction is written:
if action == 'confirm_proposal':
    transaction = await self._transaction_service.create_transaction(...)
# Never auto-committed, even with 100% confidence

# Other consequential changes use the generic pending_mutation gate:
# account create/deactivate, category delete, and transaction edit/delete/restore.
```

### 5. Guardrail Hard Blocks
```python
if guardrail_assessment.decision == GuardrailDecision.BLOCK:
    # Cannot be overridden by supervisor or any workflow
    return {'workflow_action': 'refusal', ...}
```

## Multi-Row Batch Transactions

For pasted ledger entries (2-10 rows):

```
User pastes:
  "Oct 13, 2026 Food INR 500
   Oct 14, 2026 Travel INR 1200
   Oct 15, 2026 Food INR 300"

Flow:
1. _count_transaction_rows() detects 3 rows (date+amount pattern)
2. _llm_batch_extraction_chain extracts each as TransactionExtractionOutput
3. _build_transaction_batch_proposals validates ALL rows:
   - Exact category match required
   - Exact account match required
   - Direction inferred from category type
   - ALL-OR-NOTHING: any invalid row rejects entire batch
4. pending_proposals_queue holds ordered proposals
5. Frontend shows sequential forms: "1 of 3", "2 of 3", "3 of 3"
6. Each form submission → separate create_transaction call
7. Cancel/close clears remaining queue
```

## Checkpoint & Resume

LangGraph checkpoints enable multi-turn conversations:

```python
# Thread ID format: "{user_id}:{thread_id}"
checkpoint_thread_id = f'{user_id}:{thread_id}'

# On interrupt (asking user a question):
human_response = interrupt({'question': question, ...})

# On next user message, resume directly into the capture agent:
if state_snapshot.interrupts:
    graph_input = Command(resume=message, update={...})
```

The capture agent's clarification loop resumes **directly**, not through the supervisor.

## State Shape (Key Fields)

```python
class ChatGraphState(TypedDict):
    # Core
    messages: list[BaseMessage]
    runtime_user_id: str
    runtime_timezone: str

    # Supervisor
    supervisor_action: str  # run_workflow | ask_user | finish | refuse
    supervisor_workflow_id: str  # transaction | analytics | ...
    supervisor_handoff_count: int  # ≤3
    supervisor_executed_workflows: list[str]  # No repeats
    workflow_result: dict  # Bounded summary from specialist

    # Transaction
    pending_proposal: dict | None  # Awaiting HITL confirmation
    pending_proposals_queue: list[dict] | None  # Batch queue
    pending_mutation: dict | None  # Generic account/category/transaction mutation
    transaction_capture_active: bool
    transaction_capture_turn_count: int  # ≤5

    # Analytics
    query_plan: dict  # FinanceQueryPlan
    last_finance_query_result: dict  # For format_previous

    # Guardrails
    guardrail_decision: str
    guardrail_confidence: float
```

## Adding a New Workflow

1. **Add to registry:**
   ```python
   _REGISTERED_SUPERVISOR_WORKFLOWS = frozenset({
       'transaction', 'analytics', 'category_management',
       'format_previous', 'your_new_workflow'
   })
   ```

2. **Create specialist node:**
   ```python
   async def _your_workflow_node(self, state: ChatGraphState) -> dict[str, Any]:
       # Implementation
       pass
   ```

3. **Wire in graph builder:**
   ```python
   builder.add_node('your_workflow', self._your_workflow_node)
   # Add edges from workflow_dispatch and to workflow_observer
   ```

4. **Update dispatcher routing:**
   ```python
   # In _workflow_dispatch_node
   workflow_action = {
       ...existing...,
       'your_new_workflow': 'your_action_name',
   }[workflow_id]
   ```

5. **Add observer handling:**
   ```python
   # In _workflow_observer_node
   elif workflow_id == 'your_new_workflow':
       status = ...
       summary = ...
   ```
