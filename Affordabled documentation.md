# AffordAbled — Complete Architecture & Decision Documentation

> **Document status:** Phase 1 complete. Phase 2 in progress.

---

## Table of Contents

1. [Guiding Principles](#1-guiding-principles)
2. [Tech Stack](#2-tech-stack)
3. [Phase 1 — Core Wallet](#3-phase-1--core-wallet)
4. [Phase 2 — AI Layer](#4-phase-2--ai-layer)
   - [4.1 Model & Providers](#41-model--providers)
   - [4.2 Multi-Graph Orchestrator Architecture](#42-multi-graph-orchestrator-architecture)
   - [4.3 Graph Flows — Detailed](#43-graph-flows--detailed)
   - [4.4 Complete Tool List](#44-complete-tool-list)
   - [4.5 Memory System](#45-memory-system)
   - [4.6 Human In The Loop](#46-human-in-the-loop)
   - [4.7 File Exports](#47-file-exports)
   - [4.8 Split Feature](#48-split-feature)
   - [4.9 Guardrails](#49-guardrails)
   - [4.10 Evaluation Pipeline](#410-evaluation-pipeline)
   - [4.11 Thread Management](#411-thread-management)
   - [4.12 Rate Limiting](#412-rate-limiting)
5. [Authentication](#5-authentication)
6. [Notifications](#6-notifications)
7. [Dashboard & Design System](#7-dashboard--design-system)
8. [Deployment Architecture](#8-deployment-architecture)
9. [Testing Strategy](#9-testing-strategy)
10. [Database Schema](#10-database-schema)
11. [Folder Structure](#11-folder-structure)
12. [API Endpoints](#12-api-endpoints)
13. [Build Order](#13-build-order)
14. [Open Items](#14-open-items)

---

## 1. Guiding Principles

- AI proposes, deterministic code validates and executes. The agent never fabricates numbers — every financial figure comes from a repository/service call, not from LLM text generation.
- No AI-created transaction is committed without an explicit user confirmation step.
- Every tool the agent can call is scoped to the authenticated `user_id` server-side. The LLM never supplies `user_id` as an argument.
- Keep the wallet fully usable without AI. AI is an enhancement layer on top of the plain CRUD app from Phase 1.
- AI failures never break core wallet functionality.
- Always offer a manual alternative when AI is unavailable.
- Conversational recovery over hard errors.
- External-integration execution rule: whenever a phase item depends on Azure or any external service, implementation handoff must include (1) resource provisioning steps, (2) required env vars/secrets, and (3) a concrete verification call/checklist.

---

## 2. Tech Stack

### Backend
| Technology | Purpose |
|---|---|
| FastAPI + Python 3.11 | Backend API |
| PostgreSQL | Primary database |
| SQLAlchemy + Alembic | ORM + migrations |
| Redis | Cache + Celery broker |
| Celery | Notification worker |
| Celery Beat | Scheduled tasks |

### AI
| Technology | Purpose |
|---|---|
| Sonnet 4.6 via Azure AI Foundry | Chat, reasoning, vision |
| LangGraph | Agent graph orchestration |
| LangGraph Postgres checkpointer | Conversation persistence |
| Azure Speech-to-Text (`centralindia`) | Voice input transcription |
| LangSmith | Tracing and evaluation |

### Storage & Services
| Technology | Purpose |
|---|---|
| Azure Blob Storage | File exports |
| Azure Key Vault | Secrets (managed identity) |
| Azure Container Registry | Docker images |
| Resend | Email notifications |
| pywebpush + VAPID | Web push notifications |
| Sentry | Runtime error tracking |

### Frontend
| Technology | Purpose |
|---|---|
| React + Vite + TypeScript | Frontend framework |
| Redux Toolkit + RTK Query | State + server state |
| react-hook-form + zod | Forms + validation |
| Recharts | Charts and graphs |
| Framer Motion | Animations |
| Tailwind CSS | Styling |
| Authlib | Google OAuth |

---

## 3. Phase 1 — Core Wallet

**Status: APPROVED — proceed.**

### Scope

1. **Categories** vertical slice — entity, repository, service, router, migration (mirrors `accounts`)
2. **Transactions** vertical slice — expense/income/transfer/refund, paise amounts, category + account references, ownership + transfer-balance validation in `TransactionService`, soft delete (`deleted_at` column)
3. Account balance updates wired into transaction create/update
4. Frontend: `features/categories`, `features/transactions`, `TransactionsPage`, `CreateTransactionForm` organism
5. Tests: one smoke test per router, one financial-rule test per service

### Exit Gate

Full manual ledger works end-to-end before any AI exists.

### Transaction Actions (every transaction)

- Edit manually → standard form (no AI)
- Chat about it → opens agent with transaction as context
- Delete → soft delete (recoverable)
- Undo delete → restores the transaction

---

## 4. Phase 2 — AI Layer

**Status: FULLY CONFIRMED — begin after Phase 1 exit gate.**

---

### 4.1 Model & Providers

| Capability | Decision |
|---|---|
| Chat / reasoning / extraction | Sonnet 4.6 via Azure AI Foundry |
| Image analysis (receipts, bills) | Sonnet native vision — no separate OCR |
| Voice input | Azure Speech-to-Text |
| Voice output (TTS) | Dropped entirely |
| Tracing / observability | LangSmith |

**Azure Speech region:** `centralindia`

**LangSmith projects:**
```
affordabled-development
affordabled-staging
affordabled-production
```

**Chat endpoints:**
```
POST /api/v1/chat        → text input → directly into orchestrator
POST /api/v1/chat/voice  → audio → Azure STT → same orchestrator
```

---

### 4.2 Multi-Graph Orchestrator Architecture

Instead of a single monolithic graph, AffordAbled uses an **orchestrator pattern** — one routing graph that delegates to specialist subgraphs.

**Why orchestrator over single graph:**
- Single graph becomes unmanageable at this feature scope
- Each subgraph has a focused prompt and specific tools only
- Independently testable and debuggable
- One failure does not affect other flows
- Clean conditional routing at every decision point

#### Graph Map

```
                    User Message
                         ↓
              ┌──────────────────────┐
              │   ORCHESTRATOR GRAPH  │
              │                      │
              │  classify intent     │
              │  load user context   │
              │  route to subgraph   │
              │  handle errors       │
              │  proactive insights  │
              └──────────┬───────────┘
                         ↓
         ┌───────────────┼───────────────┐
         ↓               ↓               ↓
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ TRANSACTION │  │  ANALYTICS  │  │    SPLIT    │
│    GRAPH    │  │    GRAPH    │  │    GRAPH    │
└─────────────┘  └─────────────┘  └─────────────┘
         ↓               ↓
┌─────────────┐  ┌─────────────┐
│   MEMORY    │  │    FILE     │
│    GRAPH    │  │    GRAPH    │
└─────────────┘  └─────────────┘
```

#### Orchestrator Routing Logic

```python
def route_intent(state: OrchestratorState) -> str:
    intent = state.classified_intent

    if intent == Intent.LOG_TRANSACTION:    return "transaction_graph"
    elif intent == Intent.QUERY_SPENDING:   return "analytics_graph"
    elif intent == Intent.SPLIT_REQUEST:    return "split_graph"
    elif intent == Intent.GENERATE_REPORT:  return "file_graph"
    elif intent == Intent.MEMORY_RELATED:   return "memory_graph"
    else:                                   return "refusal"
```

---

### 4.3 Graph Flows — Detailed

#### Orchestrator Graph

```
User message
      ↓
Load user context (semantic + procedural memory + split contacts)
      ↓
Semantic guardrail check
      ↓ (blocked?) → return refusal with finance suggestion
Intent classification (Haiku)
      ↓
Route to subgraph
      ↓
Collect subgraph result
      ↓
Update episodic memory
      ↓
Check for proactive insights (anomaly, recurring, budget threshold)
      ↓
Return final response to user
```

#### Transaction Graph

```
Input: raw message (text or image)
      ↓
Extract: amount, merchant, category, date, account
      ↓
Image attached? → analyze_bill_image tool
      ↓
Validate extraction:
  amount > 0?
  account exists for user?
  category valid?
      ↓
Split signals detected?
  yes → hand off to Split Graph
  no  → continue
      ↓
Build proposal
      ↓
interrupt() → human confirmation card
      ↓
user edits?   → update proposal → show card again (loop)
user cancels? → discard → return to orchestrator
user confirms? → TransactionService.create()
      ↓
Update semantic memory (monthly averages)
Update procedural memory (reinforce matching rules)
      ↓
Trigger anomaly check
      ↓
Return: "Logged ✅" + optional insight
```

#### Analytics Graph

```
Input: user question
      ↓
Parse query intent:
  spending_summary / period_comparison /
  category_breakdown / balance_check / pattern_query
      ↓
Select and call tools:
  get_transactions / get_spending_summary /
  compare_spending / get_account_balances /
  get_spending_patterns / compare_to_baseline
      ↓
Result large? (>10 rows)
  yes → trigger File Graph (PDF/Excel)
  no  → format inline (text or table)
      ↓
Format response:
  plain text bubble
  highlighted insight card
  download link (if file generated)
      ↓
Return to orchestrator
```

#### Split Graph

```
Input: transaction proposal + split signals
      ↓
Determine split type:
  equal  → divide total equally
  custom → user sets each amount
  smart  → read bill image line items per person
      ↓
Smart split path:
  analyze line items from bill image
  group by person (veg/nonveg/shared etc)
  calculate per-person amounts
      ↓
search_split_contacts (autocomplete existing contacts)
      ↓
Build split proposal:
  member names + per-person amounts + total pending
      ↓
interrupt() → enhanced confirmation card
      ↓
user disables split? → return to Transaction Graph (commit without split)
user edits members?  → update → show again (loop)
user confirms?
  → TransactionService.create()
  → SplitService.create()
  → split_contacts totals updated
      ↓
Return: confirmed transaction + split summary
```

#### Memory Graph

```
Input: memory operation type
      ↓
read:
  load episodic (recent 10 events)
  load semantic (all user facts)
  load procedural (all user rules)
  inject into orchestrator context
      ↓
write (semantic/procedural):
  confidence >= 0.85 → auto save silently
  confidence < 0.85  → interrupt() ask user to confirm
      ↓
decay (scheduled):
  inferred facts older than 90 days → reduce confidence 10%
  user_confirmed facts → never decay
      ↓
conflict (procedural):
  correction count >= 3 on same pattern → update rule
  log rule change as episodic event
```

#### File Graph

```
Input: data + format hint from Analytics Graph
      ↓
Determine format:
  agent decides: text / table / PDF / Excel
  triggers: "report", "export", "download",
            "spreadsheet", result > 10 rows
      ↓
text/table → format inline → return to Analytics Graph
      ↓
PDF/Excel:
  render bytes deterministically (fpdf2 / openpyxl)
      ↓
PUT to Azure Blob: exports/{user_id}/{export_id}.{ext}
      ↓
Insert file_exports row (status = ready)
      ↓
Mint 15 min SAS URL
      ↓
Return download link to orchestrator
```

#### Key Conditional Decision Points

```python
# Transaction graph — split detection
def check_split_signals(state: TransactionState) -> str:
    if state.split_detected:
        return "split_graph"
    return "build_proposal"

# Transaction graph — confirmation loop
def handle_confirmation(state: TransactionState) -> str:
    if state.user_action == "confirm":   return "commit_transaction"
    elif state.user_action == "edit":    return "build_proposal"
    else:                                return "discard"

# Analytics graph — file decision
def check_result_size(state: AnalyticsState) -> str:
    if len(state.results) > 10:
        return "file_graph"
    return "format_response"

# Memory graph — confidence routing
def check_confidence(state: MemoryState) -> str:
    if state.confidence >= 0.85:
        return "auto_save"
    return "ask_user"
```

---

### 4.4 Complete Tool List

#### Transaction Tools
| Tool | Subgraph | What it does |
|---|---|---|
| `create_transaction_proposal` | Transaction | NLP extraction → confirm → commit |
| `update_transaction_proposal` | Transaction | Edit suggestion → confirm → commit |
| `soft_delete_transaction` | Transaction | Marks deleted, recoverable |
| `restore_transaction` | Transaction | Undoes soft delete |

#### Query Tools
| Tool | Subgraph | What it does |
|---|---|---|
| `get_transactions(filters)` | Analytics | date, category, account, type, amount range |
| `get_account_balances()` | Analytics | All balances for authenticated user |
| `get_spending_summary(period, group_by)` | Analytics | Agent picks grouping per question |
| `compare_spending(period_a, period_b)` | Analytics | Period vs period comparison |
| `get_spending_patterns()` | Analytics | Behavioral baselines from history |
| `compare_to_baseline()` | Analytics | Anomaly flagging vs user history |

#### Memory Tools
| Tool | Subgraph | What it does |
|---|---|---|
| `log_episodic_event` | Memory | Records a user action event |
| `get_recent_episodes` | Memory | Fetches recent context (last 10) |
| `get_semantic_memory` | Memory | Loads user facts into prompt |
| `update_semantic_memory` | Memory | Saves inferred or confirmed fact |
| `get_procedural_rules` | Memory | Loads behavioral rules into prompt |
| `update_procedural_rule` | Memory | Saves a learned behavioral rule |

#### Split Tools
| Tool | Subgraph | What it does |
|---|---|---|
| `create_split_proposal` | Split | Creates split alongside transaction |
| `calculate_smart_split` | Split | Divides bill by line items per person |
| `get_pending_splits` | Split | All unsettled splits for user |
| `settle_split_member` | Split | Marks one person as settled |
| `get_split_contacts` | Split | Loads contacts for agent context |
| `search_split_contacts` | Split | Autocomplete during proposal |

#### File Tools
| Tool | Subgraph | What it does |
|---|---|---|
| `generate_file(data, format)` | File | Renders PDF/Excel → Blob → SAS URL |

#### Vision Tools
| Tool | Subgraph | What it does |
|---|---|---|
| `analyze_bill_image` | Transaction/Split | Sonnet reads bill → extracts line items + total |

#### Intelligence Tools
| Tool | Subgraph | What it does |
|---|---|---|
| `detect_anomaly` | Orchestrator | Flags unusual spend vs user baseline |
| `detect_recurring` | Orchestrator | Identifies recurring transaction patterns |

**Isolation rule:** every tool takes `user_id` from authenticated request/graph config — never from LLM tool-call arguments.

---

### 4.5 Memory System

Three memory types, all stored in Postgres — no vector DB needed until RAG (Phase 5).

#### Episodic Memory — What Happened

```sql
user_episodic_memory (
    id,
    user_id,
    event_type,    -- transaction_created/edited/deleted/restored
                   -- agent_correction, query, split_created
                   -- proposal_cancelled, procedural_rule_updated
    event_data,    -- JSON: event-specific details
    created_at
)
```

- Auto-logged on every meaningful user action (deterministic code, no agent decision)
- Retention policy (nightly cleanup job):
  - `transaction_created`: 90 days
  - `agent_correction`: 365 days (valuable longer)
  - `query`: 30 days
  - `transaction_deleted`: 90 days

#### Semantic Memory — What Agent Knows About User

```sql
user_semantic_memory (
    id,
    user_id,
    key,           -- "salary_date", "food_budget", "merchant_preference"
    value,         -- "1st", "5000", JSON
    confidence,    -- 0.0 to 1.0
    source,        -- "inferred" or "user_confirmed"
    updated_at
)
```

- `confidence >= 0.85` → saved automatically (silently)
- `confidence < 0.85` → `interrupt()` asks user to confirm
- User-confirmed facts: never decay
- Inferred facts: decay 10% every 90 days without reinforcement (weekly job)
- Below `0.5` confidence → flagged for removal

#### Procedural Memory — How User Likes Things Done

```sql
user_procedural_memory (
    id,
    user_id,
    trigger,       -- "merchant:zomato", "category:transport"
    action,        -- JSON: { category: "food delivery", round_to: 10 }
    confidence,
    source,        -- "learned_from_correction" or "user_defined"
    updated_at
)
```

- Saved after 3 corrections of the same pattern (threshold)
- Conflict resolution: 3 new corrections within 30 days override old rule
- Rule changes logged as episodic event

#### Context Injection — Every Conversation

```python
system_prompt = f"""
You are AffordAbled's personal finance assistant for {user.name}.

WHAT YOU KNOW ABOUT THIS USER (Semantic):
{format_semantic(semantic_memory)}

HOW THIS USER LIKES THINGS DONE (Procedural):
{format_procedural(procedural_rules)}

RECENT CONTEXT (Episodic — last 10 events):
{format_episodic(recent_episodes)}

FREQUENT SPLIT CONTACTS:
{format_contacts(split_contacts_with_balances)}

Rules:
- Never generate financial numbers yourself
- Always confirm before logging transactions
- Every figure comes from a tool call
- Only help with personal finance topics
"""
```

#### "What Claude Knows About Me" Page

User-facing memory management at `/memory`:
- **Facts Claude knows** (Semantic) → view / edit / delete
- **How Claude behaves** (Procedural) → view / edit / delete
- **Recent activity** (Episodic) → read only
- **[Reset all memory]** → nuclear option

#### Scheduled Memory Jobs

```python
# Nightly — episodic cleanup
async def cleanup_episodic_memory():
    for event_type, days in RETENTION_POLICY.items():
        await memory_repo.delete_old_episodes(event_type, days)

# Weekly — semantic decay
async def decay_semantic_confidence():
    await memory_repo.decay_confidence(
        source="inferred",
        older_than_days=90,
        decay_factor=0.1
    )
```

#### Self-Learning Loop

```
User corrects agent (e.g. Zomato → food delivery)
        ↓
Correction logged as episodic event
        ↓
correction_count for this pattern checked
        ↓
count >= 3 → procedural rule saved automatically
        ↓
Next interaction: rule applied, no correction needed

Cross-user signal:
Zomato misclassified for 200+ users
        ↓
Analytics detect pattern in agent_corrections
        ↓
System prompt updated globally
        ↓
Fixed for all users
```

---

### 4.6 Human In The Loop

#### Confirmation Card — Inline In Chat

All fields inline editable by default. No separate edit mode.

```
┌─────────────────────────────────┐
│ 🧾 Log this transaction?        │
│                                 │
│ Merchant  [Swiggy        ]  ✏️  │
│ Amount    [₹500          ]  ✏️  │
│ Category  [Food delivery ]  ✏️  │
│ Date      [Today         ]  ✏️  │
│ Account   [SBI           ]  ✏️  │
│                                 │
│ [Confirm ✅] [Cancel ❌]        │
│ 💬 Continue chatting →          │
└─────────────────────────────────┘
```

#### Three Actions

**Confirm ✅**
- Commits via `TransactionService.create()`
- Updates episodic, semantic, procedural memory
- Shows proactive insight if relevant
- Chat bubble: "Done! Logged ₹500 🎉"

**Cancel ❌**
- Proposal discarded, nothing committed
- Logs `proposal_cancelled` episodic event
- Chat bubble: "Okay, cancelled. Anything else?"

**Continue chatting 💬**
- Returns to chat view
- Proposal stays alive in `GraphState.pending_proposal`
- User can modify via natural language
- "Actually make it 600" → updates proposal → card shown again

#### Proposal Lifetime In Graph State

```python
class GraphState(TypedDict):
    messages: list
    pending_proposal: TransactionProposal | None  # lives until resolved
    user_id: str
    thread_id: str
```

Proposal survives multiple chat turns until explicitly confirmed or cancelled.

#### Split-Enhanced Card

When split is detected, additional section appears below transaction fields:

```
┌─────────────────────────────────┐
│ [transaction fields above...]   │
│                                 │
│ ┌─────────────────────────────┐ │
│ │ 🔀 Split detected           │ │
│ │ ₹6000 among 5 people        │ │
│ │                             │ │
│ │ 1. Sarthak (you)  ₹1200 ✓  │ │
│ │ 2. [Name...    ]  ₹1200    │ │
│ │ 3. [Name...    ]  ₹1200    │ │
│ │                             │ │
│ │ ● Equal  ○ Custom           │ │
│ │ [Disable split ✕]           │ │
│ └─────────────────────────────┘ │
│                                 │
│ [Confirm ✅] [Cancel ❌]        │
└─────────────────────────────────┘
```

#### Frontend State Machine

```
IDLE
  ↓ user sends message
AGENT_THINKING
  ↓ proposal returned
PROPOSAL_SHOWN
  ↓ user edits
PROPOSAL_EDITING
  ↓
PROPOSAL_SHOWN
  ↓            ↓              ↓
CONFIRM      CANCEL      CONTINUE_CHAT
  ↓            ↓              ↓
COMMITTED    IDLE          IDLE (proposal in state)
```

#### Agent Response Shape

```typescript
{
  message: string,
  proposal: {
    merchant: string,
    amount: number,
    category: string,
    date: string,
    account_id: string,
    account_name: string,
    type: "expense" | "income" | "transfer",
    confidence: number,
    split?: SplitProposal
  } | null,  // null = plain chat response
  insight?: InsightCard | null
}
```

---

### 4.7 File Exports

#### Flow — Synchronous, No Queue

```
Agent decides to generate file
        ↓
FastAPI generate_file tool:
  1. Render PDF/Excel bytes (fpdf2 / openpyxl)
  2. PUT to Blob: exports/{user_id}/{export_id}.{ext}
  3. Insert file_exports row: status = ready
  4. Mint 15 min SAS URL
  5. Return URL to orchestrator
        ↓
Agent returns inline download link to user
```

Total time: under 1 second for typical financial report.

#### File Export Table

```sql
file_exports (
    id,
    user_id,
    thread_id,
    blob_path,       -- never a URL, just the path — permanent
    filename,
    format,          -- "pdf" or "excel"
    content_type,
    size_bytes,
    status,          -- "ready" or "failed"
    created_at
)
```

#### Re-download Flow

```
User clicks download (any session)
        ↓
GET /api/v1/exports/{export_id}/download-url
        ↓
Server looks up blob_path (scoped to user_id ownership check)
        ↓
Mints fresh 15 min SAS URL
        ↓
User downloads ✅
```

#### When Agent Generates A File

Agent autonomously decides — not only when user says "PDF":
- User asks for "report", "export", "download", "spreadsheet"
- Query result has more than 10 rows
- User asks to compare multiple periods or categories
- Single-fact answers stay as plain text

#### Libraries

| Format | Library | Reason |
|---|---|---|
| PDF | `fpdf2` | Pure Python, no system deps, container friendly |
| Excel | `openpyxl` | Standard, well maintained |

#### SAS TTL: 15 minutes

Fresh URL minted on every click — TTL only needs to cover the download window.

---

### 4.8 Split Feature

#### Split Types

- **Equal** — divide total equally among all members
- **Custom** — user sets each person's amount manually
- **Smart** — agent reads bill image line items, splits by what each person ordered

#### Smart Split Example

```
Bill image: dinner for 5
  Veg thali x2:    ₹1200
  Non-veg thali x3: ₹2800
  Dessert x5:      ₹2000 (shared)

Smart split:
  Veg person:     ₹600 + ₹400 = ₹1000 each
  Non-veg person: ₹933 + ₹400 = ₹1333 each
```

#### Split Contacts

```sql
split_contacts (
    id,
    user_id,
    name,
    nickname,
    phone,           -- optional, future remind feature
    avatar_color,    -- auto assigned
    total_pending,   -- denormalized running total
    total_settled,   -- denormalized historical total
    last_split_at,
    created_at
)
```

- Created implicitly on first use (no separate add contact flow)
- Autocomplete shows existing contacts + their current pending balance
- Full per-contact history page

#### Split Tables

```sql
splits (
    id,
    transaction_id,
    user_id,         -- who paid
    total_amount,
    split_type,      -- "equal" / "custom" / "smart"
    created_at
)

split_members (
    id,
    split_id,
    split_contact_id,
    name,            -- denormalized
    amount,
    is_owner,        -- true for the app user
    status,          -- "pending" / "settled"
    settled_at,
    created_at
)
```

#### Transaction List Badge

```
Swiggy     ₹500    [🔀 ₹400 pending]
```

Tapping badge → split detail with per-member status and settle buttons.

#### Dashboard Split Tracker Widget

Grouped by contact — shows everything each person owes across all transactions:

```
🔀 Split Tracker — Total pending: ₹14,200
  👤 Rahul    ₹8,400  6 splits   [View] [Remind]
  👤 Priya    ₹3,600  3 splits   [View] [Remind]
```

#### Manual Split

Always available on any transaction via **[🔀 Add Split]** button — even after the fact.

#### AI Split Detection Signals

```python
split_signals = [
    "split", "divide", "shared", "together",
    "people", "friends", "group", "each",
    "for X people", "among us"
]
# Also: multiple covers on restaurant bill, group booking reference
```

No signal + no image → no split suggested (default off).
Signal detected → split card shown, ON by default.

---

### 4.9 Guardrails

Three layers operating in sequence:

#### Layer 1 — Semantic Similarity (Fastest)

```python
# One-time setup at startup
FINANCE_TOPICS = [
    "log a transaction or expense",
    "track spending and budget",
    "split a bill with friends",
    "check account balance",
    # ... more
]

# On every message
message_vector = await embedder.embed(message)
finance_score  = max(cosine_similarity(message_vector, fv) for fv in finance_vectors)

# Three zones
if finance_score > 0.75:  return Decision.ALLOW         # clearly finance
if finance_score < 0.25:  return Decision.BLOCK          # clearly off-topic
else:                     return Decision.NEEDS_CLASSIFICATION  # borderline → Layer 2
```

#### Layer 2 — Intent Classifier (Borderline Only)

Uses Claude Haiku (cheap + fast) to classify borderline messages:

```python
class DetectedIntent(Enum):
    LOG_TRANSACTION
    QUERY_SPENDING
    SPLIT_REQUEST
    GENERATE_REPORT
    ACCOUNT_QUERY
    MEMORY_RELATED
    OFF_TOPIC
```

#### Layer 3 — System Prompt (Always Present)

Agent itself refuses non-finance requests. Refusal format:
> "I'm your finance assistant — I can only help with money matters. Want me to [relevant finance suggestion]?"

#### Guardrail Logging

```sql
guardrail_logs (
    id, user_id, message, intent,
    confidence, triggered, layer, created_at
)
```

Used to identify abuse patterns and improve classifier over time.

#### Borderline Handling

```
"Is inflation affecting my spending?" → finance-adjacent → ALLOW
"Should I invest my savings?"         → finance-adjacent → ALLOW with disclaimer
"What's the USD to INR rate?"         → useful for finance → ALLOW
"Write a poem about my expenses"      → off-topic → BLOCK
"Explain machine learning"            → off-topic → BLOCK
```

---

### 4.10 Evaluation Pipeline

#### Dataset — Built From Production

```sql
eval_dataset (
    id,
    input_message,
    input_image,
    expected_output,   -- correct transaction proposal
    actual_output,     -- what agent produced
    user_action,       -- "confirmed" / "edited" / "cancelled"
    corrections,       -- JSON: what user changed
    eval_type,         -- "extraction" / "guardrail" / "memory"
    passed,
    created_at
)
```

**Auto-labelling logic:**
- User confirms without edits → `passed = true`
- User edits before confirming → `passed = false`, expected = corrected version
- User cancels → ambiguous, logged but not labelled

#### Metrics Tracked

```
Extraction accuracy:
  amount_accuracy, category_accuracy,
  merchant_accuracy, date_accuracy

Guardrail accuracy:
  true_positive_rate (correctly blocked)
  false_positive_rate (incorrectly blocked)

Overall:
  confirmation_rate   -- % confirmed without edits
  edit_rate           -- % edited before confirming
  cancellation_rate   -- % cancelled

Per-dimension:
  per_category_accuracy
  per_merchant_accuracy
```

#### Analytics Tables

```sql
agent_corrections (
    id, user_id, thread_id, message_id,
    field,         -- "category" / "amount" / "merchant"
    agent_value,   -- what agent suggested
    user_value,    -- what user changed it to
    merchant,
    created_at
)

agent_metrics (
    id, period,
    total_proposals, confirmed_count,
    edited_count, cancelled_count,
    accuracy_rate, top_corrections,
    created_at
)
```

#### Improvement Loop — Weekly

```
Run LangSmith eval suite
        ↓
Identify top corrections across users
(e.g. "Zomato misclassified as groceries — 234 users")
        ↓
Update system prompt
        ↓
Re-run eval → measure improvement
        ↓
Repeat weekly
```

#### Privacy

- Conversation storage enabled by default
- Users can opt-out (stored in `users.conversation_storage_enabled`)
- Data used to improve service (disclosed in ToS)

---

### 4.11 Thread Management

```sql
chat_threads (
    id,
    user_id,
    type,             -- "general" / "transaction"
    title,            -- auto-generated from first message
    transaction_id,   -- null for general threads
    created_at,
    last_message_at,
    expires_at        -- created_at + 90 days
)

chat_messages (
    id, thread_id, user_id, role,
    content, tool_calls, tool_results,
    proposal, user_action, corrections,
    created_at,
    expires_at        -- created_at + 90 days
)
```

| Decision | Choice |
|---|---|
| Thread creation | User controlled — explicit new chat |
| Thread types | General + Transaction-scoped |
| History | Full list, infinite scroll, grouped by date |
| Retention | 90 days |
| Conversation storage | Opt-out (default on) |

**Transaction-scoped thread:** opened via "Chat about this" on any transaction. Opens `/chat?transaction_id=xyz` — agent receives transaction as context automatically.

---

### 4.12 Rate Limiting

Redis-based, per user:

| Endpoint | Limit | Window |
|---|---|---|
| `POST /chat` | 50 messages | Per day |
| `POST /chat/voice` | 20 messages | Per day |
| `POST /exports` | 10 exports | Per day |
| `POST /chat` | 10 messages | Per minute (burst) |
| All endpoints | 200 requests | Per minute |

Remaining count shown in chat header: `💬 AffordAbled AI [38/50 msgs]`

When limit reached — friendly message shown with manual alternatives.

---

## 5. Authentication

### JWT Structure

```python
# Access token (15 min, response body)
{
    "sub": "user_id",
    "email": "user@gmail.com",
    "name": "Sarthak",
    "iat": 1234567890,
    "exp": 1234567890,
    "type": "access"
}

# Refresh token (30 days, httpOnly cookie)
{
    "sub": "user_id",
    "type": "refresh",
    "exp": 1234567890
}
```

### Refresh Token Cookie

```python
response.set_cookie(
    key="refresh_token",
    value=refresh_token,
    httponly=True,       # JS blocked
    secure=True,         # HTTPS only
    samesite="lax",      # CSRF protection
    max_age=60*60*24*30  # 30 days
)
```

### Login Methods

**Email + Password:**
```
POST /api/v1/auth/login
→ validate credentials
→ return access token (body)
→ set refresh token (httpOnly cookie)
```

**Google OAuth (via Authlib):**
```
GET /api/v1/auth/google
→ redirect to Google consent screen
→ Google returns auth code
→ exchange for profile
→ find or create user
→ same token flow
```

### Auto Token Refresh (RTK Query)

```typescript
const baseQueryWithReauth = async (args, api, extraOptions) => {
    let result = await baseQuery(args, api, extraOptions)
    if (result.error?.status === 401) {
        const refresh = await baseQuery(
            { url: '/auth/refresh', method: 'POST', credentials: 'include' },
            api, extraOptions
        )
        if (refresh.data) {
            api.dispatch(setAccessToken(refresh.data.access_token))
            result = await baseQuery(args, api, extraOptions)
        } else {
            api.dispatch(logout())
        }
    }
    return result
}
```

### Users Table

```sql
users (
    id, email, name, avatar_url,
    hashed_password,          -- null if Google auth
    auth_provider,            -- "email" / "google"
    google_id,                -- null if email auth
    conversation_storage_enabled,
    notification_email_enabled,
    notification_push_enabled,
    created_at, last_login_at
)
```

### Auth Endpoints

```
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
GET  /api/v1/auth/google
GET  /api/v1/auth/google/callback
GET  /api/v1/auth/me
```

---

## 6. Notifications

### Architecture

```
FastAPI publishes event
        ↓
Redis queue (Celery broker)
        ↓
Celery Worker processes event:
  → checks triggers
  → checks user preferences
  → sends via channels
        ↓
Channels:
  Resend → email
  pywebpush → web push
  notifications table → in-app
```

### Channel Routing

| Trigger | Email | Push |
|---|---|---|
| Split reminder | ✅ | ✅ |
| Split settled | ❌ | ✅ |
| Budget 80% | ❌ | ✅ |
| Budget exceeded | ✅ | ✅ |
| Anomaly detected | ✅ | ✅ |
| Weekly summary | ✅ | ❌ |
| Monthly report | ✅ | ❌ |
| New login | ✅ | ❌ |

### Scheduled Jobs (Celery Beat)

```python
beat_schedule = {
    "weekly-summary":   crontab(hour=9, minute=0, day_of_week=0),    # Sunday 9am
    "monthly-report":   crontab(hour=9, minute=0, day_of_month=1),   # 1st of month
    "split-reminders":  crontab(hour=10, minute=0, day_of_week=1),   # Monday 10am
    "anomaly-check":    crontab(minute=0),                            # Hourly
}
```

### Notification Tables

```sql
notifications (
    id, user_id, type, channel,
    title, body, data,
    read, sent_at, created_at
)

notification_preferences (
    id, user_id,
    channel,   -- "email" / "push"
    trigger,   -- from NotificationTrigger enum
    enabled,
    created_at
)
```

### Three Processes

```
Process 1 — FastAPI:        handles HTTP requests, publishes events
Process 2 — Celery Worker:  processes notification events, sends emails/push
Process 3 — Celery Beat:    fires scheduled tasks (summaries, reminders)
```

---

## 7. Dashboard & Design System

### Color Tokens

```css
:root {
  --brand-primary:  #A855F7;   /* purple-400 */
  --brand-hover:    #9333EA;   /* purple-500 */
  --brand-active:   #7C3AED;   /* purple-600 */
  --brand-subtle:   rgba(168, 85, 247, 0.1);

  --bg-app:         #09090B;   /* gray-950 */
  --bg-card:        #0F0F11;   /* gray-900 */
  --bg-elevated:    #1C1C1F;   /* gray-800 */
  --bg-border:      #28282D;   /* gray-700 */

  --text-primary:   #FFFFFF;
  --text-secondary: #9CA3AF;
  --text-muted:     #6B7280;

  --positive:       #4ADE80;   /* green-400 — income */
  --negative:       #F87171;   /* red-400 — expense */
  --warning:        #FACC15;   /* yellow-400 */
  --info:           #60A5FA;   /* blue-400 */

  --card-radius:    16px;
  --btn-radius:     12px;
  --input-radius:   10px;
}
```

### Typography

- **Font:** Inter (Google Fonts)
- **Scale:** xs(12) → sm(14) → base(16) → lg(18) → xl(20) → 2xl(24) → 3xl(30) → 4xl(36)
- **Weights:** 400 body / 500 labels / 600 titles / 700 hero numbers

### Dashboard Widget Order

1. Hero balance card (gradient purple, total + per-account)
2. Quick actions (Add / Split / Report / Chat)
3. Spending overview (bar chart + category breakdown + period toggle)
4. Recent transactions (last 5, with split badges)
5. Split tracker (grouped by contact, pending totals)
6. AI insights (swipeable proactive insight cards)
7. 6-month trend (line chart, spending vs income)

### Navigation

```
Bottom nav: 🏠 Home | 💳 Transactions | 🔀 Splits | 👤 Profile
FABs above nav: [🎤] mic shortcut  [💬] chat
```

### Page Routes

```
/                         Dashboard
/transactions             Transaction list
/transactions/:id         Transaction detail
/categories               Categories
/accounts                 Accounts
/splits                   Split tracker
/splits/:id               Split detail
/contacts                 Split contacts
/contacts/:id             Contact detail + history
/chat                     AI Chat (sidebar + main)
/chat/:thread_id          Specific thread
/exports                  File exports history
/memory                   What Claude knows about me
/notifications            Notification center
/settings                 Settings
/settings/profile         Profile
/settings/notifications   Notification preferences
/auth/login               Login
/auth/register            Register
```

### In-Chat Display

| Content type | Display |
|---|---|
| Normal response | Chat bubble |
| Transaction proposal | Inline editable card |
| Insight | Highlighted card (purple border) |
| File download | Inline link in chat bubble |
| Refusal | Chat bubble with suggestion |

### Libraries

- Charts: Recharts
- Animation: Framer Motion (under 200ms all transitions)
- Light mode: tokens defined, implement later

---

## 8. Deployment Architecture

### Local Development

```yaml
# docker-compose.yml — one command: docker-compose up
services:
  api:     FastAPI (uvicorn --reload)
  worker:  Celery worker
  beat:    Celery beat
  web:     React (vite dev)
  db:      PostgreSQL 15
  redis:   Redis alpine
```

### Cloud — Azure Container Apps

```
Environment: affordabled-env

affordabled-api      FastAPI      scale: 1-10 replicas (HTTP based)
affordabled-web      React/nginx  scale: 1-5  replicas (HTTP based)
affordabled-worker   Celery       scale: 1-5  replicas (queue depth based)
affordabled-beat     Celery Beat  scale: 1    always singleton
```

### External Azure Services

```
Azure Database for PostgreSQL  (primary DB)
Azure Cache for Redis          (rate limiting + Celery broker)
Azure Blob Storage             (file exports)
Azure Container Registry       (Docker images)
Azure Key Vault                (all secrets via managed identity)
Azure Speech Services          (STT, centralindia region)
Azure AI Foundry               (Sonnet 4.6)
```

### Secrets — Azure Key Vault

All secrets stored in Key Vault, pulled via managed identity (no credentials in code):
```
database-url, redis-url, jwt-secret,
google-client-id, google-client-secret,
langsmith-api-key, azure-speech-key,
azure-blob-connection-string, resend-api-key,
vapid-private-key, anthropic-api-key,
sentry-dsn
```

### CI/CD — GitHub Actions

```
PR pipeline:
  → unit + integration tests
  → type check + lint
  → must pass to merge

Staging pipeline (on merge to main):
  → build + push Docker images to ACR
  → deploy to staging Container Apps
  → run Alembic migrations

Production pipeline (on v* tag):
  → requires manual approval
  → same deploy flow to production
```

### Branch Strategy

```
feature/*  →  PR  →  main  →  [auto] staging  →  v* tag  →  [manual] production
```

### Monitoring

| Tool | Purpose |
|---|---|
| Azure metrics | Container health, CPU, memory, requests |
| LangSmith | AI traces, token usage, tool call success |
| Sentry | Runtime errors |
| Azure Log Analytics | Centralised logs from all containers |

---

## 9. Testing Strategy

### Testing Pyramid

| Layer | Tool | Runs When |
|---|---|---|
| Unit | pytest | Every commit |
| Integration | pytest + test DB | Every PR |
| AI Tools | pytest | Every PR |
| Guardrails | pytest | Every PR |
| Extraction (LLM) | pytest + real LLM | Nightly |
| E2E | Playwright | Nightly |
| Eval pipeline | LangSmith experiments | Weekly |

### Unit Tests — What To Cover

```
Transaction validation rules
Split calculation (equal, custom, smart)
Balance updates after transaction
Memory confidence decay
Procedural rule threshold (3 corrections)
Anomaly detection logic
Budget threshold checks
Cross-user isolation
```

### Integration Tests — What To Cover

```
All auth endpoints
Transaction CRUD + balance updates
Soft delete + restore flow
Split creation + settlement
File export generation
Notification preferences
Repository methods + complex aggregations
```

### AI-Specific Tests

**Tool tests (deterministic — run on every PR):**
```python
# Tools never return another user's data
# Spending summary math is correct
# Anomaly detection flags correctly
# Guardrail blocks/allows correctly
```

**Extraction tests (LLM — run nightly):**
```python
@pytest.mark.llm
@pytest.mark.parametrize("input,expected", [
    ("spent 500 on swiggy", {"amount": 500, "merchant": "Swiggy"}),
    ("salary credited 45000", {"amount": 45000, "type": "income"}),
    ("paid 6000 for dinner for 5 people", {"amount": 6000, "split": True}),
])
async def test_transaction_extraction(input, expected): ...
```

### E2E Tests (Playwright — 5 critical flows)

1. Complete transaction log flow (chat → proposal → confirm → list)
2. Split creation and settlement flow
3. Google OAuth login flow
4. File export generation and download
5. Voice input → transcription → transaction

### Coverage Targets

```
Unit:        80% minimum
Integration: all endpoints covered
LLM:         top 20 extraction cases
E2E:         5 critical flows only
```

### Test Markers

```ini
# pytest.ini
markers =
    unit: fast unit tests
    integration: tests requiring DB
    llm: tests making real LLM calls (nightly)
    e2e: end to end browser tests (nightly)
```

---

## 10. Database Schema

```sql
-- CORE
users (id, email, name, avatar_url, hashed_password, auth_provider,
       google_id, conversation_storage_enabled,
       notification_email_enabled, notification_push_enabled,
       created_at, last_login_at)

accounts (id, user_id, name, type, balance, currency, created_at)

categories (id, user_id, name, icon, color, type, created_at)

transactions (id, user_id, account_id, category_id, type, amount,
              merchant, note, date, deleted_at, created_at, updated_at)

-- SPLITS
splits (id, transaction_id, user_id, total_amount, split_type, created_at)

split_members (id, split_id, split_contact_id, name, amount,
               is_owner, status, settled_at, created_at)

split_contacts (id, user_id, name, nickname, phone, avatar_color,
                total_pending, total_settled, last_split_at, created_at)

-- AI MEMORY
user_episodic_memory (id, user_id, event_type, event_data, created_at)

user_semantic_memory (id, user_id, key, value,
                      confidence, source, updated_at)

user_procedural_memory (id, user_id, trigger, action,
                        confidence, source, updated_at)

-- CHAT
chat_threads (id, user_id, type, title, transaction_id,
              created_at, last_message_at, expires_at)

chat_messages (id, thread_id, user_id, role, content,
               tool_calls, tool_results, proposal, user_action,
               corrections, created_at, expires_at)

-- ANALYTICS & EVAL
agent_corrections (id, user_id, thread_id, message_id,
                   field, agent_value, user_value, merchant, created_at)

agent_metrics (id, period, total_proposals, confirmed_count,
               edited_count, cancelled_count, accuracy_rate,
               top_corrections, created_at)

guardrail_logs (id, user_id, message, intent,
                confidence, triggered, layer, created_at)

eval_dataset (id, input_message, input_image, expected_output,
              actual_output, user_action, corrections,
              eval_type, passed, created_at)

-- FILES
file_exports (id, user_id, thread_id, blob_path, filename,
              format, content_type, size_bytes, status, created_at)

-- NOTIFICATIONS
notifications (id, user_id, type, channel, title, body,
               data, read, sent_at, created_at)

notification_preferences (id, user_id, channel, trigger,
                          enabled, created_at)

-- LANGGRAPH (auto managed)
checkpoints (managed by LangGraph Postgres checkpointer)
```

---

## 11. Folder Structure

```
AffordAbled/
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── core/
│   │   │   │   ├── config.py
│   │   │   │   ├── security.py
│   │   │   │   └── dependencies.py
│   │   │   │
│   │   │   ├── domain/
│   │   │   │   ├── entities/
│   │   │   │   │   ├── transaction.py
│   │   │   │   │   ├── account.py
│   │   │   │   │   ├── category.py
│   │   │   │   │   ├── split.py
│   │   │   │   │   └── split_contact.py
│   │   │   │   └── ports.py
│   │   │   │       # ChatModel, SpeechToTextService,
│   │   │   │       # ObjectStorageService, TokenService
│   │   │   │
│   │   │   ├── application/
│   │   │   │   ├── services/
│   │   │   │   │   ├── transaction_service.py
│   │   │   │   │   ├── account_service.py
│   │   │   │   │   ├── category_service.py
│   │   │   │   │   ├── split_service.py
│   │   │   │   │   ├── memory_service.py
│   │   │   │   │   ├── file_export_service.py
│   │   │   │   │   └── notification_service.py
│   │   │   │   └── use_cases/
│   │   │   │
│   │   │   ├── infrastructure/
│   │   │   │   ├── database/
│   │   │   │   │   ├── models/
│   │   │   │   │   └── repositories/
│   │   │   │   │       ├── transaction_repo.py
│   │   │   │   │       ├── account_repo.py
│   │   │   │   │       ├── category_repo.py
│   │   │   │   │       ├── split_repo.py
│   │   │   │   │       ├── memory_repo.py
│   │   │   │   │       ├── file_exports_repo.py
│   │   │   │   │       └── notification_repo.py
│   │   │   │   │
│   │   │   │   ├── ai/
│   │   │   │   │   ├── providers/
│   │   │   │   │   │   ├── foundry_chat_model.py
│   │   │   │   │   │   └── azure_speech.py
│   │   │   │   │   ├── graphs/
│   │   │   │   │   │   ├── orchestrator_graph.py
│   │   │   │   │   │   ├── transaction_graph.py
│   │   │   │   │   │   ├── analytics_graph.py
│   │   │   │   │   │   ├── split_graph.py
│   │   │   │   │   │   ├── memory_graph.py
│   │   │   │   │   │   └── file_graph.py
│   │   │   │   │   ├── tools/
│   │   │   │   │   │   ├── transaction_tools.py
│   │   │   │   │   │   ├── query_tools.py
│   │   │   │   │   │   ├── memory_tools.py
│   │   │   │   │   │   ├── split_tools.py
│   │   │   │   │   │   ├── file_tools.py
│   │   │   │   │   │   └── vision_tools.py
│   │   │   │   │   ├── guardrails/
│   │   │   │   │   │   ├── semantic_guardrail.py
│   │   │   │   │   │   └── intent_classifier.py
│   │   │   │   │   └── checkpointer.py
│   │   │   │   │
│   │   │   │   ├── storage/
│   │   │   │   │   └── azure_blob.py
│   │   │   │   │
│   │   │   │   └── celery/
│   │   │   │       ├── celery_app.py
│   │   │   │       └── tasks/
│   │   │   │           ├── notification_tasks.py
│   │   │   │           └── scheduled_tasks.py
│   │   │   │
│   │   │   └── presentation/
│   │   │       └── routers/
│   │   │           ├── auth_router.py
│   │   │           ├── accounts_router.py
│   │   │           ├── transactions_router.py
│   │   │           ├── categories_router.py
│   │   │           ├── splits_router.py
│   │   │           ├── contacts_router.py
│   │   │           ├── memory_router.py
│   │   │           ├── exports_router.py
│   │   │           ├── notifications_router.py
│   │   │           └── chat_router.py
│   │   │
│   │   ├── alembic/
│   │   │   └── versions/
│   │   ├── tests/
│   │   │   ├── conftest.py
│   │   │   ├── unit/
│   │   │   ├── integration/
│   │   │   ├── ai/
│   │   │   └── e2e/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── web/
│       └── src/
│           ├── features/
│           │   ├── auth/
│           │   ├── dashboard/
│           │   ├── transactions/
│           │   ├── categories/
│           │   ├── accounts/
│           │   ├── splits/
│           │   ├── contacts/
│           │   ├── chat/
│           │   ├── memory/
│           │   ├── exports/
│           │   └── notifications/
│           ├── store/
│           │   ├── store.ts
│           │   ├── slices/
│           │   │   ├── authSlice.ts
│           │   │   └── uiSlice.ts
│           │   └── services/
│           │       ├── api.ts
│           │       ├── authApi.ts
│           │       ├── transactionsApi.ts
│           │       ├── splitsApi.ts
│           │       ├── chatApi.ts
│           │       └── memoryApi.ts
│           ├── components/
│           │   ├── ui/
│           │   └── organisms/
│           │       ├── TransactionProposalCard.tsx
│           │       ├── SplitProposalCard.tsx
│           │       ├── InsightCard.tsx
│           │       └── ChatInput.tsx
│           └── Dockerfile
│
├── docker-compose.yml
└── .github/
    └── workflows/
        ├── pr.yml
        ├── staging.yml
        └── production.yml
```

---

## 12. API Endpoints

### Auth
```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
GET    /api/v1/auth/google
GET    /api/v1/auth/google/callback
GET    /api/v1/auth/me
```

### Accounts
```
GET    /api/v1/accounts
POST   /api/v1/accounts
GET    /api/v1/accounts/{id}
PATCH  /api/v1/accounts/{id}
DELETE /api/v1/accounts/{id}
```

### Categories
```
GET    /api/v1/categories
POST   /api/v1/categories
PATCH  /api/v1/categories/{id}
DELETE /api/v1/categories/{id}
```

### Transactions
```
GET    /api/v1/transactions
POST   /api/v1/transactions
GET    /api/v1/transactions/{id}
PATCH  /api/v1/transactions/{id}
DELETE /api/v1/transactions/{id}
POST   /api/v1/transactions/{id}/restore
POST   /api/v1/transactions/{id}/split
```

### Splits
```
GET    /api/v1/splits
GET    /api/v1/splits/{id}
PATCH  /api/v1/splits/{id}/members/{member_id}
```

### Split Contacts
```
GET    /api/v1/split-contacts
GET    /api/v1/split-contacts/{id}
PATCH  /api/v1/split-contacts/{id}
DELETE /api/v1/split-contacts/{id}
GET    /api/v1/split-contacts/search?q=
```

### Chat
```
POST   /api/v1/chat
POST   /api/v1/chat/voice
GET    /api/v1/chat/threads
GET    /api/v1/chat/threads/{thread_id}
DELETE /api/v1/chat/threads/{thread_id}
```

### Memory
```
GET    /api/v1/memory/semantic
PATCH  /api/v1/memory/semantic/{id}
DELETE /api/v1/memory/semantic/{id}
GET    /api/v1/memory/procedural
PATCH  /api/v1/memory/procedural/{id}
DELETE /api/v1/memory/procedural/{id}
GET    /api/v1/memory/episodic
DELETE /api/v1/memory
```

### Exports
```
GET    /api/v1/exports
GET    /api/v1/exports/{id}/download-url
```

### Notifications
```
GET    /api/v1/notifications
PATCH  /api/v1/notifications/{id}/read
DELETE /api/v1/notifications/{id}
GET    /api/v1/notifications/preferences
PATCH  /api/v1/notifications/preferences
POST   /api/v1/notifications/subscribe
```

---

## 13. Build Order

### Phase 1 — Core Wallet (Current, Approved)
- [x] Categories vertical slice
- [x] Transactions vertical slice (with soft delete)
- [x] Balance update wiring
- [x] Frontend features
- [x] Tests per convention

**Exit gate: full manual ledger works end-to-end.**

### Phase 2 — AI Foundation
- [x] Redis setup
- [x] Azure Speech adapter + STT endpoint
- [ ] LangGraph Postgres checkpointer
- [ ] Basic orchestrator → single node → `/api/v1/chat` (prove round trip)
- [ ] Semantic guardrail + intent classifier
- [ ] Prove two-turn conversation persists across HTTP requests
- [ ] Enable dashboard quick actions: `Chat` and `Voice` (wire to `/api/v1/chat` and `/api/v1/chat/voice` after round-trip is stable)

### Phase 3 — AI Features
- [ ] Memory system (all three types + cleanup jobs)
- [ ] Transaction Graph (extraction, proposal, confirm, commit)
- [ ] Analytics Graph (query tools, spending summary, comparison)
- [ ] Split Graph (detection, smart split, contacts)
- [ ] Bill image analysis (vision tools)
- [ ] File Graph (PDF/Excel + Blob + SAS URL)
- [ ] Enable dashboard quick action: `Image` (bill/receipt capture + vision extraction flow)

### Phase 4 — Intelligence Layer
- [ ] Proactive insights (anomaly, recurring, budget threshold)
- [ ] Notification system (Celery + Resend + pywebpush)
- [ ] Evaluation pipeline (LangSmith + weekly loop)
- [ ] "What Claude knows about me" page
- [ ] Self-learning improvement loop

### Phase 5 — RAG (Deferred)
- [ ] pgvector extension
- [ ] Embedding pipeline for transactions
- [ ] `find_similar_past_transactions` tool
- [ ] No graph redesign needed — purely additive

---

## 14. Open Items

All major decisions are confirmed. Remaining items deferred intentionally:

| Item | Status | Notes |
|---|---|---|
| Mobile wrapper (PWA vs Capacitor vs RN) | Deferred | Affects native push notifications |
| Native push notifications | Deferred | Depends on wrapper decision |
| Light mode implementation | Deferred | Tokens defined, implement later |
| RAG / pgvector | Phase 5 | Additive, no redesign needed |
| Budget entity | Post-Phase 3 | Needed for budget alerts feature |
| SAS download link expiry UX | Decided (15 min) | Fresh URL on every click |
| Tiered rate limits (free vs pro) | Post-launch | Single limit for v1 |

---

*Document last updated: September 2026*
*Phase 1: Complete | Phase 2: In progress*
