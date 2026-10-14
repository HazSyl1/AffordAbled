# AffordAbled — LangGraph AI Graph: Codex Prompt + Implementation Plan

---

## PART 1 — CODEX PROMPT

## Status Update (2026-10-13)

- Execution progress and current remaining scope are tracked in `Final_Plan.md` (latest source of truth).
- Migration blocker for `conversation_storage_enabled` is fixed by using Alembic-safe revision id `a2_guardrail_logs_user_storage`.
- Database migration now upgrades cleanly to head; schema includes `users.conversation_storage_enabled` and `guardrail_logs`.
- Thread/message persistence, agent correction logging, exports re-download endpoint, and retention cleanup job scaffolding are implemented.
- Proactive insights are now emitted in chat query responses and surfaced in frontend chat flows.
- Frontend lint and production build now pass (`npm run lint`, `npm run build`) after switching Vite scripts to native config loading.
- Use this document as architecture/context reference, and `Final_Plan.md` for active implementation tracking.

Copy this entire prompt into Codex when you are ready to build the AI layer.

---

```
You are building the AI layer for AffordAbled — a personal finance app
built with FastAPI + PostgreSQL + Redis. The core wallet (accounts,
categories, transactions) already exists and works. You are now adding
the LangGraph multi-graph orchestrator on top of it.

Do NOT touch any existing code unless explicitly told to.
Only create new files inside the paths specified.

════════════════════════════════════════════════════════════
ARCHITECTURE OVERVIEW
════════════════════════════════════════════════════════════

Entry point: POST /api/v1/chat  (text)
             POST /api/v1/chat/voice  (audio → STT → same graph)

Every message flows through ONE entry point: the Orchestrator graph.
The Orchestrator routes to one of five specialist subgraphs:

  1. Transaction graph  — log / edit / delete transactions
  2. Analytics graph    — spending queries, summaries, comparisons
  3. Split graph        — bill splitting, contacts, settlement
  4. Memory graph       — read/write episodic, semantic, procedural memory
  5. File graph         — render PDF/Excel, upload to Blob, return SAS URL

The model used is: claude-sonnet-4-6 (via Azure AI Foundry)
Tracing: LangSmith (LANGCHAIN_TRACING_V2=true)
Checkpointer: AsyncPostgresSaver (same DATABASE_URL as main app)
STT: Azure Speech-to-Text (centralindia region)

════════════════════════════════════════════════════════════
CRITICAL RULES — READ BEFORE WRITING ANY CODE
════════════════════════════════════════════════════════════

1. The LLM never supplies user_id. Every tool reads user_id from
   graph config (configurable fields), never from tool arguments.

2. Every financial figure shown to the user comes from a tool call
   (a repository/service query), never from LLM text generation.

3. No transaction is committed without interrupt() + user confirmation.
   Read-only analytics never interrupt.

4. Tools are the ONLY way the agent interacts with the database.
   Agents never import repositories directly.

5. Each subgraph has its own focused system prompt and tool list.
   No subgraph sees tools it doesn't need.

6. All subgraphs are independently testable without the orchestrator.

════════════════════════════════════════════════════════════
FOLDER STRUCTURE TO CREATE
════════════════════════════════════════════════════════════

apps/api/app/infrastructure/ai/
├── __init__.py
├── checkpointer.py
├── context.py                  # memory context loader
├── providers/
│   ├── __init__.py
│   ├── foundry_chat_model.py   # Azure AI Foundry adapter
│   └── azure_speech.py         # STT adapter
├── guardrails/
│   ├── __init__.py
│   ├── semantic_guardrail.py   # vector similarity check
│   └── intent_classifier.py    # Haiku classifier
├── graphs/
│   ├── __init__.py
│   ├── orchestrator_graph.py
│   ├── transaction_graph.py
│   ├── analytics_graph.py
│   ├── split_graph.py
│   ├── memory_graph.py
│   └── file_graph.py
├── tools/
│   ├── __init__.py
│   ├── transaction_tools.py
│   ├── query_tools.py
│   ├── memory_tools.py
│   ├── split_tools.py
│   ├── file_tools.py
│   └── vision_tools.py
└── state/
    ├── __init__.py
    └── graph_state.py          # all TypedDict state definitions

apps/api/app/presentation/routers/
└── chat_router.py              # new router (add to main.py)

════════════════════════════════════════════════════════════
ENVIRONMENT VARIABLES (add to core/config.py + .env.example)
════════════════════════════════════════════════════════════

# Azure AI Foundry
AZURE_FOUNDRY_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_FOUNDRY_API_KEY=your_key
AZURE_FOUNDRY_DEPLOYMENT=claude-sonnet-4-6

# Azure Speech
AZURE_SPEECH_KEY=your_key
AZURE_SPEECH_REGION=centralindia

# Azure Blob Storage
AZURE_BLOB_CONNECTION_STRING=DefaultEndpointsProtocol=https;...
AZURE_BLOB_CONTAINER=exports

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls_your_key
LANGCHAIN_PROJECT=affordabled-development

════════════════════════════════════════════════════════════
STATE DEFINITIONS — state/graph_state.py
════════════════════════════════════════════════════════════

from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages

class TransactionProposal(TypedDict):
    merchant: Optional[str]
    amount: Optional[float]
    category_id: Optional[str]
    category_name: Optional[str]
    account_id: Optional[str]
    account_name: Optional[str]
    type: str                     # expense | income | transfer | refund
    date: str
    note: Optional[str]
    confidence: float
    split_detected: bool

class SplitProposal(TypedDict):
    transaction_proposal: TransactionProposal
    split_type: str               # equal | custom | smart
    total_amount: float
    members: list[dict]           # [{name, contact_id, amount}]

class OrchestratorState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    thread_id: str
    intent: Optional[str]         # classified intent
    guardrail_passed: bool
    memory_context: Optional[str] # formatted memory injected into prompt
    subgraph_result: Optional[dict]

class TransactionState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    thread_id: str
    proposal: Optional[TransactionProposal]
    user_action: Optional[str]    # confirm | edit | cancel
    committed_transaction_id: Optional[str]
    memory_context: Optional[str]

class AnalyticsState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    query_intent: Optional[str]
    results: Optional[list]
    needs_file: bool
    memory_context: Optional[str]

class SplitState(TypedDict):
    messages: Annotated[list, add_messages]
    user_id: str
    split_proposal: Optional[SplitProposal]
    user_action: Optional[str]
    memory_context: Optional[str]

class MemoryState(TypedDict):
    user_id: str
    operation: str                # read | write | decay | conflict
    memory_type: Optional[str]    # episodic | semantic | procedural
    payload: Optional[dict]

class FileState(TypedDict):
    user_id: str
    thread_id: str
    data: dict
    format: str                   # pdf | excel | table
    export_id: Optional[str]
    download_url: Optional[str]

════════════════════════════════════════════════════════════
CHECKPOINTER — checkpointer.py
════════════════════════════════════════════════════════════

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from app.core.config import settings

async def get_checkpointer() -> AsyncPostgresSaver:
    checkpointer = AsyncPostgresSaver.from_conn_string(settings.database_url)
    await checkpointer.setup()   # creates checkpoint tables if not exist
    return checkpointer

# Usage in graph compilation:
# graph = builder.compile(checkpointer=await get_checkpointer())

════════════════════════════════════════════════════════════
AZURE AI FOUNDRY ADAPTER — providers/foundry_chat_model.py
════════════════════════════════════════════════════════════

from langchain_openai import AzureChatOpenAI
from app.core.config import settings

def get_chat_model(temperature: float = 0.1) -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_endpoint=settings.azure_foundry_endpoint,
        api_key=settings.azure_foundry_api_key,
        azure_deployment=settings.azure_foundry_deployment,
        api_version="2024-02-01",
        temperature=temperature,
        max_tokens=2000,
    )

def get_classifier_model() -> AzureChatOpenAI:
    # Use a cheaper/faster model for classification if available
    # Otherwise same model at temperature=0
    return get_chat_model(temperature=0)

════════════════════════════════════════════════════════════
AZURE STT ADAPTER — providers/azure_speech.py
════════════════════════════════════════════════════════════

import azure.cognitiveservices.speech as speechsdk
from app.core.config import settings

class AzureSpeechAdapter:
    def __init__(self):
        self.config = speechsdk.SpeechConfig(
            subscription=settings.azure_speech_key,
            region=settings.azure_speech_region
        )
        self.config.speech_recognition_language = "en-IN"

    async def transcribe(self, audio_bytes: bytes) -> str:
        # Write bytes to temp stream
        stream = speechsdk.audio.PushAudioInputStream()
        stream.write(audio_bytes)
        stream.close()

        audio_config = speechsdk.audio.AudioConfig(stream=stream)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self.config,
            audio_config=audio_config
        )
        result = recognizer.recognize_once()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return result.text
        raise ValueError(f"STT failed: {result.reason}")

════════════════════════════════════════════════════════════
GUARDRAILS — guardrails/semantic_guardrail.py
════════════════════════════════════════════════════════════

from enum import Enum
from langchain_openai import AzureOpenAIEmbeddings
import numpy as np

class GuardrailDecision(Enum):
    ALLOW = "allow"
    BLOCK = "block"
    CLASSIFY = "classify"   # borderline → send to intent classifier

FINANCE_TOPICS = [
    "log a transaction or expense",
    "track spending and budget",
    "split a bill with friends",
    "check account balance",
    "analyse spending patterns",
    "generate financial report",
    "categorise expenses",
    "track income and salary",
    "manage personal finances",
    "recurring payments and subscriptions",
    "UPI payment bank transfer",
    "salary credited income",
]

OFF_TOPIC_EXAMPLES = [
    "write a poem or story",
    "explain science or history",
    "help with coding or programming",
    "sports news and entertainment",
    "general knowledge question",
    "recipe or cooking help",
    "political news current events",
]

class SemanticGuardrail:
    def __init__(self):
        self._finance_vectors = None
        self._off_topic_vectors = None
        self._embedder = None   # lazy init

    def _get_embedder(self):
        if not self._embedder:
            self._embedder = AzureOpenAIEmbeddings(...)
        return self._embedder

    async def _get_vectors(self):
        if self._finance_vectors is None:
            embedder = self._get_embedder()
            self._finance_vectors = await embedder.aembed_documents(FINANCE_TOPICS)
            self._off_topic_vectors = await embedder.aembed_documents(OFF_TOPIC_EXAMPLES)

    def _cosine_similarity(self, a, b):
        a, b = np.array(a), np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    async def check(self, message: str) -> GuardrailDecision:
        await self._get_vectors()
        embedder = self._get_embedder()
        msg_vec = await embedder.aembed_query(message)

        finance_score = max(
            self._cosine_similarity(msg_vec, fv)
            for fv in self._finance_vectors
        )
        off_topic_score = max(
            self._cosine_similarity(msg_vec, ov)
            for ov in self._off_topic_vectors
        )

        if finance_score > 0.75:
            return GuardrailDecision.ALLOW
        if off_topic_score > 0.80:
            return GuardrailDecision.BLOCK
        return GuardrailDecision.CLASSIFY

════════════════════════════════════════════════════════════
INTENT CLASSIFIER — guardrails/intent_classifier.py
════════════════════════════════════════════════════════════

import json
from app.infrastructure.ai.providers.foundry_chat_model import get_classifier_model

INTENT_PROMPT = """
Classify this personal finance app message into exactly one intent.
Message: "{message}"

Respond with JSON only, no other text:
{{
    "intent": "<one of: log_transaction | query_spending | split_request | generate_report | account_query | memory_related | off_topic>",
    "confidence": <0.0 to 1.0>
}}
"""

async def classify_intent(message: str) -> dict:
    model = get_classifier_model()
    response = await model.ainvoke(INTENT_PROMPT.format(message=message))
    try:
        return json.loads(response.content)
    except Exception:
        return {"intent": "off_topic", "confidence": 0.5}

════════════════════════════════════════════════════════════
MEMORY CONTEXT LOADER — context.py
════════════════════════════════════════════════════════════

# Loads all three memory types and formats them for system prompt injection.
# Called by Orchestrator at the start of every conversation turn.

async def load_memory_context(user_id: str, db) -> str:
    from app.infrastructure.database.repositories.memory_repo import MemoryRepository
    repo = MemoryRepository(db)

    semantic   = await repo.get_semantic(user_id)
    procedural = await repo.get_procedural(user_id)
    episodic   = await repo.get_recent_episodes(user_id, limit=10)
    contacts   = await repo.get_frequent_split_contacts(user_id, limit=5)

    parts = []

    if semantic:
        facts = "\n".join(f"  - {m.key}: {m.value}" for m in semantic)
        parts.append(f"WHAT YOU KNOW ABOUT THIS USER:\n{facts}")

    if procedural:
        rules = "\n".join(f"  - {m.trigger} → {m.action}" for m in procedural)
        parts.append(f"HOW THIS USER LIKES THINGS DONE:\n{rules}")

    if episodic:
        events = "\n".join(
            f"  - [{e.event_type}] {e.event_data}" for e in episodic
        )
        parts.append(f"RECENT CONTEXT (last {len(episodic)} events):\n{events}")

    if contacts:
        contact_lines = "\n".join(
            f"  - {c.name}: ₹{c.total_pending} pending"
            for c in contacts
        )
        parts.append(f"FREQUENT SPLIT CONTACTS:\n{contact_lines}")

    return "\n\n".join(parts) if parts else ""

════════════════════════════════════════════════════════════
ORCHESTRATOR GRAPH — graphs/orchestrator_graph.py
════════════════════════════════════════════════════════════

from langgraph.graph import StateGraph, END
from langgraph.types import Command
from app.infrastructure.ai.state.graph_state import OrchestratorState
from app.infrastructure.ai.guardrails.semantic_guardrail import SemanticGuardrail, GuardrailDecision
from app.infrastructure.ai.guardrails.intent_classifier import classify_intent
from app.infrastructure.ai.context import load_memory_context
from app.infrastructure.ai.graphs.transaction_graph import run_transaction_graph
from app.infrastructure.ai.graphs.analytics_graph import run_analytics_graph
from app.infrastructure.ai.graphs.split_graph import run_split_graph
from app.infrastructure.ai.graphs.memory_graph import run_memory_graph
from app.infrastructure.ai.graphs.file_graph import run_file_graph

guardrail = SemanticGuardrail()

# ── Node: load context ──────────────────────────────────
async def load_context_node(state: OrchestratorState, config):
    db = config["configurable"]["db"]
    user_id = state["user_id"]
    memory_context = await load_memory_context(user_id, db)
    return {"memory_context": memory_context}

# ── Node: guardrail check ───────────────────────────────
async def guardrail_node(state: OrchestratorState):
    last_message = state["messages"][-1].content
    decision = await guardrail.check(last_message)

    if decision == GuardrailDecision.BLOCK:
        return {"guardrail_passed": False}

    if decision == GuardrailDecision.CLASSIFY:
        result = await classify_intent(last_message)
        if result["intent"] == "off_topic" and result["confidence"] > 0.85:
            return {"guardrail_passed": False, "intent": "off_topic"}
        return {"guardrail_passed": True, "intent": result["intent"]}

    return {"guardrail_passed": True}

# ── Node: classify intent ───────────────────────────────
async def classify_node(state: OrchestratorState):
    last_message = state["messages"][-1].content
    result = await classify_intent(last_message)
    return {"intent": result["intent"]}

# ── Node: refusal ───────────────────────────────────────
async def refusal_node(state: OrchestratorState):
    from langchain_core.messages import AIMessage
    msg = AIMessage(content=(
        "I'm your finance assistant — I can only help with money matters. "
        "Want me to show your spending summary or log a transaction?"
    ))
    return {"messages": [msg]}

# ── Node: route to subgraph ─────────────────────────────
async def route_node(state: OrchestratorState, config):
    intent = state.get("intent", "off_topic")
    db     = config["configurable"]["db"]
    user_id = state["user_id"]

    if intent == "log_transaction":
        result = await run_transaction_graph(state, config)
    elif intent == "query_spending":
        result = await run_analytics_graph(state, config)
    elif intent == "split_request":
        result = await run_split_graph(state, config)
    elif intent == "memory_related":
        result = await run_memory_graph(state, config)
    elif intent == "generate_report":
        result = await run_file_graph(state, config)
    else:
        result = {"messages": []}

    # Log episodic event
    from app.infrastructure.ai.tools.memory_tools import log_episodic_event
    await log_episodic_event(user_id, "agent_response", {"intent": intent}, db)

    return {"subgraph_result": result, **result}

# ── Routing condition ───────────────────────────────────
def after_guardrail(state: OrchestratorState) -> str:
    if not state.get("guardrail_passed", True):
        return "refusal"
    if state.get("intent"):
        return "route"
    return "classify"

# ── Build graph ─────────────────────────────────────────
def build_orchestrator() -> StateGraph:
    builder = StateGraph(OrchestratorState)

    builder.add_node("load_context", load_context_node)
    builder.add_node("guardrail",    guardrail_node)
    builder.add_node("classify",     classify_node)
    builder.add_node("refusal",      refusal_node)
    builder.add_node("route",        route_node)

    builder.set_entry_point("load_context")
    builder.add_edge("load_context", "guardrail")

    builder.add_conditional_edges(
        "guardrail",
        after_guardrail,
        {"refusal": "refusal", "route": "route", "classify": "classify"}
    )

    builder.add_edge("classify", "route")
    builder.add_edge("refusal",  END)
    builder.add_edge("route",    END)

    return builder

════════════════════════════════════════════════════════════
TRANSACTION GRAPH — graphs/transaction_graph.py
════════════════════════════════════════════════════════════

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langchain_core.messages import SystemMessage
from app.infrastructure.ai.state.graph_state import TransactionState
from app.infrastructure.ai.providers.foundry_chat_model import get_chat_model
from app.infrastructure.ai.tools.transaction_tools import (
    create_transaction_proposal_tool,
    analyze_bill_image_tool,
    commit_transaction_tool,
    soft_delete_transaction_tool,
    restore_transaction_tool,
)
from app.infrastructure.ai.tools.memory_tools import update_semantic_memory_tool

SYSTEM_PROMPT = """
You are a transaction logging assistant for a personal finance app.

Your ONLY job: extract transaction details from the user's message
and create a proposal for the user to confirm.

Rules:
- Never invent amounts. Extract only what the user stated.
- If amount is unclear, ask the user — don't guess.
- Detect split signals: words like "split", "shared", "for N people",
  "among us", "divide", multiple people mentioned.
- Date defaults to today unless user specifies otherwise.
- Always call create_transaction_proposal — never respond with raw text.

{memory_context}
"""

tools = [
    create_transaction_proposal_tool,
    analyze_bill_image_tool,
    soft_delete_transaction_tool,
    restore_transaction_tool,
]

async def extract_node(state: TransactionState):
    model = get_chat_model().bind_tools(tools)
    system = SystemMessage(content=SYSTEM_PROMPT.format(
        memory_context=state.get("memory_context", "")
    ))
    response = await model.ainvoke([system] + state["messages"])
    return {"messages": [response]}

async def validate_node(state: TransactionState):
    # Check proposal has required fields
    proposal = state.get("proposal")
    if not proposal or not proposal.get("amount"):
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="Could you clarify the amount?")]}
    return {}

def check_split_signals(state: TransactionState) -> str:
    proposal = state.get("proposal", {})
    if proposal.get("split_detected"):
        return "split_graph"
    return "confirm"

async def confirm_node(state: TransactionState):
    # interrupt() pauses the graph and sends proposal to frontend
    # Frontend sends back: {"user_action": "confirm|edit|cancel", "proposal": {...}}
    user_response = interrupt({
        "type": "transaction_proposal",
        "proposal": state.get("proposal"),
    })
    return {
        "user_action": user_response.get("action"),
        "proposal": user_response.get("proposal", state.get("proposal")),
    }

def after_confirm(state: TransactionState) -> str:
    action = state.get("user_action", "cancel")
    if action == "confirm":  return "commit"
    if action == "edit":     return "extract"   # loop back
    return "discard"

async def commit_node(state: TransactionState, config):
    db = config["configurable"]["db"]
    result = await commit_transaction_tool(
        proposal=state["proposal"],
        user_id=state["user_id"],
        db=db
    )
    await update_semantic_memory_tool(
        user_id=state["user_id"],
        key="last_transaction_category",
        value=state["proposal"].get("category_name"),
        confidence=0.7,
        source="inferred",
        db=db,
    )
    from langchain_core.messages import AIMessage
    msg = AIMessage(content=f"Done! Logged ₹{state['proposal']['amount']} ✅")
    return {"messages": [msg], "committed_transaction_id": result["id"]}

async def discard_node(state: TransactionState):
    from langchain_core.messages import AIMessage
    return {"messages": [AIMessage(content="Okay, cancelled. Anything else?")]}

def build_transaction_graph() -> StateGraph:
    builder = StateGraph(TransactionState)

    builder.add_node("extract",  extract_node)
    builder.add_node("validate", validate_node)
    builder.add_node("confirm",  confirm_node)
    builder.add_node("commit",   commit_node)
    builder.add_node("discard",  discard_node)

    builder.set_entry_point("extract")
    builder.add_edge("extract", "validate")

    builder.add_conditional_edges(
        "validate",
        check_split_signals,
        {"split_graph": END, "confirm": "confirm"}
    )

    builder.add_conditional_edges(
        "confirm",
        after_confirm,
        {"commit": "commit", "edit": "extract", "discard": "discard"}
    )

    builder.add_edge("commit",  END)
    builder.add_edge("discard", END)

    return builder

async def run_transaction_graph(state, config):
    graph = build_transaction_graph().compile()
    return await graph.ainvoke(state, config)

════════════════════════════════════════════════════════════
ANALYTICS GRAPH — graphs/analytics_graph.py
════════════════════════════════════════════════════════════

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage
from app.infrastructure.ai.state.graph_state import AnalyticsState
from app.infrastructure.ai.providers.foundry_chat_model import get_chat_model
from app.infrastructure.ai.tools.query_tools import (
    get_transactions_tool,
    get_spending_summary_tool,
    compare_spending_tool,
    get_account_balances_tool,
    get_spending_patterns_tool,
    compare_to_baseline_tool,
    detect_anomaly_tool,
    detect_recurring_tool,
)

SYSTEM_PROMPT = """
You are a financial analytics assistant.

Your job: answer spending questions using ONLY tool results.
Never generate financial numbers yourself — call tools for all data.
When results are large (many rows), call generate_file instead of
listing everything inline.

{memory_context}
"""

tools = [
    get_transactions_tool,
    get_spending_summary_tool,
    compare_spending_tool,
    get_account_balances_tool,
    get_spending_patterns_tool,
    compare_to_baseline_tool,
    detect_anomaly_tool,
    detect_recurring_tool,
]

async def query_node(state: AnalyticsState):
    model = get_chat_model().bind_tools(tools)
    system = SystemMessage(content=SYSTEM_PROMPT.format(
        memory_context=state.get("memory_context", "")
    ))
    response = await model.ainvoke([system] + state["messages"])
    return {"messages": [response]}

def check_result_size(state: AnalyticsState) -> str:
    results = state.get("results", [])
    if len(results) > 10:
        return "file_graph"
    return "format"

async def format_node(state: AnalyticsState):
    # Results are inline — model already produced a response
    return {}

def build_analytics_graph() -> StateGraph:
    builder = StateGraph(AnalyticsState)

    builder.add_node("query",  query_node)
    builder.add_node("format", format_node)

    builder.set_entry_point("query")

    builder.add_conditional_edges(
        "query",
        check_result_size,
        {"file_graph": END, "format": "format"}
    )

    builder.add_edge("format", END)

    return builder

async def run_analytics_graph(state, config):
    graph = build_analytics_graph().compile()
    return await graph.ainvoke(state, config)

════════════════════════════════════════════════════════════
SPLIT GRAPH — graphs/split_graph.py
════════════════════════════════════════════════════════════

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from langchain_core.messages import SystemMessage
from app.infrastructure.ai.state.graph_state import SplitState
from app.infrastructure.ai.providers.foundry_chat_model import get_chat_model
from app.infrastructure.ai.tools.split_tools import (
    create_split_proposal_tool,
    calculate_smart_split_tool,
    search_split_contacts_tool,
    settle_split_member_tool,
    get_pending_splits_tool,
)

SYSTEM_PROMPT = """
You are a bill-splitting assistant.

Rules:
- Always search existing contacts first before creating new ones.
- For smart splits, call calculate_smart_split with bill image data.
- Equal split is the default when no breakdown is provided.
- Never calculate split amounts yourself — use calculate_smart_split.

{memory_context}
"""

tools = [
    create_split_proposal_tool,
    calculate_smart_split_tool,
    search_split_contacts_tool,
    settle_split_member_tool,
    get_pending_splits_tool,
]

async def detect_node(state: SplitState):
    model = get_chat_model().bind_tools(tools)
    system = SystemMessage(content=SYSTEM_PROMPT.format(
        memory_context=state.get("memory_context", "")
    ))
    response = await model.ainvoke([system] + state["messages"])
    return {"messages": [response]}

async def confirm_node(state: SplitState):
    user_response = interrupt({
        "type": "split_proposal",
        "split_proposal": state.get("split_proposal"),
    })
    return {
        "user_action": user_response.get("action"),
        "split_proposal": user_response.get("split_proposal", state.get("split_proposal")),
    }

def after_confirm(state: SplitState) -> str:
    action = state.get("user_action", "cancel")
    if action == "confirm":  return "commit"
    if action == "edit":     return "detect"
    if action == "disable":  return "commit_no_split"
    return "discard"

async def commit_node(state: SplitState, config):
    db = config["configurable"]["db"]
    from app.application.services.split_service import SplitService
    service = SplitService(db)
    await service.create_from_proposal(state["split_proposal"], state["user_id"])
    from langchain_core.messages import AIMessage
    return {"messages": [AIMessage(content="Split created ✅")]}

async def discard_node(state: SplitState):
    from langchain_core.messages import AIMessage
    return {"messages": [AIMessage(content="Split cancelled.")]}

def build_split_graph() -> StateGraph:
    builder = StateGraph(SplitState)

    builder.add_node("detect",  detect_node)
    builder.add_node("confirm", confirm_node)
    builder.add_node("commit",  commit_node)
    builder.add_node("discard", discard_node)

    builder.set_entry_point("detect")
    builder.add_edge("detect", "confirm")

    builder.add_conditional_edges(
        "confirm",
        after_confirm,
        {
            "commit":          "commit",
            "edit":            "detect",
            "commit_no_split": "commit",
            "discard":         "discard",
        }
    )

    builder.add_edge("commit",  END)
    builder.add_edge("discard", END)

    return builder

async def run_split_graph(state, config):
    graph = build_split_graph().compile()
    return await graph.ainvoke(state, config)

════════════════════════════════════════════════════════════
MEMORY GRAPH — graphs/memory_graph.py
════════════════════════════════════════════════════════════

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from app.infrastructure.ai.state.graph_state import MemoryState

async def read_node(state: MemoryState, config):
    from app.infrastructure.ai.context import load_memory_context
    db = config["configurable"]["db"]
    context = await load_memory_context(state["user_id"], db)
    return {"payload": {"memory_context": context}}

async def write_node(state: MemoryState, config):
    from app.infrastructure.ai.tools.memory_tools import update_semantic_memory_tool
    db = config["configurable"]["db"]
    payload = state.get("payload", {})
    confidence = payload.get("confidence", 0.5)

    if confidence < 0.85:
        user_response = interrupt({
            "type": "memory_confirm",
            "key":   payload.get("key"),
            "value": payload.get("value"),
        })
        if not user_response.get("confirmed"):
            return {}

    await update_semantic_memory_tool(
        user_id=state["user_id"],
        db=db,
        **payload
    )
    return {}

def route_operation(state: MemoryState) -> str:
    return state.get("operation", "read")

def build_memory_graph() -> StateGraph:
    builder = StateGraph(MemoryState)

    builder.add_node("read",  read_node)
    builder.add_node("write", write_node)

    builder.set_entry_point("read")

    builder.add_conditional_edges(
        "read",
        route_operation,
        {"read": END, "write": "write"}
    )

    builder.add_edge("write", END)

    return builder

async def run_memory_graph(state, config):
    graph = build_memory_graph().compile()
    return await graph.ainvoke(state, config)

════════════════════════════════════════════════════════════
FILE GRAPH — graphs/file_graph.py
════════════════════════════════════════════════════════════

from langgraph.graph import StateGraph, END
from app.infrastructure.ai.state.graph_state import FileState
from app.infrastructure.ai.tools.file_tools import (
    render_pdf_tool,
    render_excel_tool,
    upload_to_blob_tool,
    mint_sas_url_tool,
    insert_file_export_tool,
)

async def decide_format_node(state: FileState):
    # Format was decided by analytics graph — just validate
    fmt = state.get("format", "pdf")
    if fmt not in ("pdf", "excel", "table"):
        fmt = "pdf"
    return {"format": fmt}

def route_format(state: FileState) -> str:
    return state.get("format", "pdf")

async def render_pdf_node(state: FileState):
    pdf_bytes = await render_pdf_tool(state["data"])
    return {"rendered_bytes": pdf_bytes, "content_type": "application/pdf"}

async def render_excel_node(state: FileState):
    xlsx_bytes = await render_excel_tool(state["data"])
    return {"rendered_bytes": xlsx_bytes,
            "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

async def upload_node(state: FileState, config):
    db = config["configurable"]["db"]
    import uuid
    export_id = str(uuid.uuid4())
    ext = "pdf" if state["format"] == "pdf" else "xlsx"
    blob_path = f"exports/{state['user_id']}/{export_id}.{ext}"

    await upload_to_blob_tool(
        blob_path=blob_path,
        data=state["rendered_bytes"],
        content_type=state["content_type"],
    )
    await insert_file_export_tool(
        export_id=export_id,
        user_id=state["user_id"],
        thread_id=state["thread_id"],
        blob_path=blob_path,
        format=state["format"],
        content_type=state["content_type"],
        db=db,
    )
    sas_url = await mint_sas_url_tool(blob_path=blob_path, ttl_minutes=15)
    return {"export_id": export_id, "download_url": sas_url}

def build_file_graph() -> StateGraph:
    builder = StateGraph(FileState)

    builder.add_node("decide",       decide_format_node)
    builder.add_node("render_pdf",   render_pdf_node)
    builder.add_node("render_excel", render_excel_node)
    builder.add_node("upload",       upload_node)

    builder.set_entry_point("decide")

    builder.add_conditional_edges(
        "decide",
        route_format,
        {
            "pdf":   "render_pdf",
            "excel": "render_excel",
            "table": END,
        }
    )

    builder.add_edge("render_pdf",   "upload")
    builder.add_edge("render_excel", "upload")
    builder.add_edge("upload",       END)

    return builder

async def run_file_graph(state, config):
    graph = build_file_graph().compile()
    return await graph.ainvoke(state, config)

════════════════════════════════════════════════════════════
CHAT ROUTER — presentation/routers/chat_router.py
════════════════════════════════════════════════════════════

from fastapi import APIRouter, Depends, File, Form, UploadFile
from langchain_core.messages import HumanMessage
from app.core.dependencies import get_current_user, get_db
from app.infrastructure.ai.checkpointer import get_checkpointer
from app.infrastructure.ai.graphs.orchestrator_graph import build_orchestrator
from app.infrastructure.ai.providers.azure_speech import AzureSpeechAdapter
from app.infrastructure.ai.guardrails.rate_limiter import check_rate_limit

router = APIRouter(prefix="/api/v1", tags=["chat"])
stt = AzureSpeechAdapter()

async def _invoke(message: str, thread_id: str, user_id: str, db):
    await check_rate_limit(user_id, "chat", limit=50)

    checkpointer = await get_checkpointer()
    graph = build_orchestrator().compile(checkpointer=checkpointer)

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id":   user_id,
            "db":        db,
        }
    }

    state = {
        "messages":        [HumanMessage(content=message)],
        "user_id":         user_id,
        "thread_id":       thread_id,
        "guardrail_passed": True,
    }

    result = await graph.ainvoke(state, config)
    last_msg = result["messages"][-1]

    return {
        "message":      last_msg.content,
        "proposal":     result.get("proposal"),
        "split_proposal": result.get("split_proposal"),
        "download_url": result.get("download_url"),
        "thread_id":    thread_id,
    }

@router.post("/chat")
async def chat(
    body: dict,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    return await _invoke(
        message=body["message"],
        thread_id=body.get("thread_id", str(uuid.uuid4())),
        user_id=str(user.id),
        db=db,
    )

@router.post("/chat/voice")
async def chat_voice(
    audio: UploadFile = File(...),
    thread_id: str = Form(...),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await check_rate_limit(str(user.id), "voice", limit=20)
    audio_bytes = await audio.read()
    transcript = await stt.transcribe(audio_bytes)
    return await _invoke(
        message=transcript,
        thread_id=thread_id,
        user_id=str(user.id),
        db=db,
    )

════════════════════════════════════════════════════════════
DEPENDENCIES TO INSTALL
════════════════════════════════════════════════════════════

pip install langgraph langgraph-checkpoint-postgres langchain \
            langchain-openai langsmith azure-cognitiveservices-speech \
            azure-storage-blob fpdf2 openpyxl numpy

════════════════════════════════════════════════════════════
ADD TO main.py
════════════════════════════════════════════════════════════

from app.presentation.routers.chat_router import router as chat_router
app.include_router(chat_router)

════════════════════════════════════════════════════════════
WHAT NOT TO CHANGE
════════════════════════════════════════════════════════════

- Any existing router (accounts, transactions, categories, auth)
- Any existing repository or service
- Any existing SQLAlchemy model
- Database migrations already run
- Redux/RTK Query frontend code

Only ADD new files. Only IMPORT from existing services — do not rewrite them.
```

---

## PART 2 — IMPLEMENTATION PLAN

Ordered steps. Complete each fully before moving to the next.
Each step has a proof-of-life check so you know it worked.

---

### Step 0 — Prerequisites

Before writing any AI code, confirm:

```
[ ] Phase 1 (accounts, categories, transactions) fully working
[ ] Azure AI Foundry deployment confirmed (Sonnet 4.6)
[ ] Azure Speech resource created (centralindia)
[ ] Azure Blob Storage container created (exports/)
[ ] LangSmith account created, project affordabled-development
[ ] Redis running (for rate limiting)
[ ] All env vars added to .env and core/config.py
```

---

### Step 1 — Plumbing (no agent yet)

**Goal:** prove the infrastructure works before writing any graph logic.

Files to create:
```
infrastructure/ai/providers/foundry_chat_model.py
infrastructure/ai/providers/azure_speech.py
infrastructure/ai/checkpointer.py
```

Write a throwaway test script:
```python
# test_plumbing.py (delete after)
import asyncio
from app.infrastructure.ai.providers.foundry_chat_model import get_chat_model
from app.infrastructure.ai.checkpointer import get_checkpointer

async def main():
    # 1. Model responds
    model = get_chat_model()
    response = await model.ainvoke("Hello, respond with one word only.")
    print("Model:", response.content)

    # 2. Checkpointer connects
    cp = await get_checkpointer()
    print("Checkpointer: OK")

asyncio.run(main())
```

Proof of life: model returns a response, no DB errors.

---

### Step 2 — State definitions + context loader

Files to create:
```
infrastructure/ai/state/graph_state.py
infrastructure/ai/context.py
```

At this point there is no graph yet — just data structures.
Run the memory repo test to verify context loads:
```python
# Requires a test user with some semantic memory rows
context = await load_memory_context("test-user-id", db)
print(context)
```

Proof of life: context string prints without errors (empty is fine if no memory rows yet).

---

### Step 3 — Guardrails

Files to create:
```
infrastructure/ai/guardrails/semantic_guardrail.py
infrastructure/ai/guardrails/intent_classifier.py
```

Write a test:
```python
guardrail = SemanticGuardrail()

cases = [
    ("spent 500 on swiggy",     "ALLOW"),
    ("what did I spend today?",  "ALLOW"),
    ("write me a poem",          "BLOCK"),
    ("explain machine learning", "BLOCK"),
    ("is my spending normal?",   "ALLOW"),
]

for message, expected in cases:
    result = await guardrail.check(message)
    print(f"{message[:30]:30} → {result.value:10} (expected {expected})")
```

Proof of life: at least 4/5 cases correct.

---

### Step 4 — Basic orchestrator (no subgraphs)

Build the orchestrator with stub subgraphs that just echo back.

Files to create:
```
infrastructure/ai/graphs/orchestrator_graph.py   (stub version)
presentation/routers/chat_router.py
```

Register the router in main.py.

Test with curl:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "thread_id": "test-123"}'
```

Proof of life: 200 response with a message field.

Test conversation persistence:
```bash
# Send two messages with the same thread_id
# Second response should reference the first
curl ... -d '{"message": "my name is sarthak", "thread_id": "abc"}'
curl ... -d '{"message": "what is my name?", "thread_id": "abc"}'
# Should say "Sarthak"
```

Proof of life: agent remembers across HTTP requests via Postgres checkpointer.

---

### Step 5 — Tool stubs

Before building real tools, create stub versions that return hardcoded data.
This lets you test the graphs without needing real DB connections.

Files to create (stubs):
```
infrastructure/ai/tools/transaction_tools.py
infrastructure/ai/tools/query_tools.py
infrastructure/ai/tools/memory_tools.py
infrastructure/ai/tools/split_tools.py
infrastructure/ai/tools/file_tools.py
infrastructure/ai/tools/vision_tools.py
```

Each tool at this stage just returns:
```python
@tool
async def get_spending_summary_tool(period: str, group_by: str) -> dict:
    """Stub — replace with real DB call"""
    return {"food": 4500, "transport": 2000}
```

---

### Step 6 — Transaction graph

Files to create:
```
infrastructure/ai/graphs/transaction_graph.py
```

Replace transaction tool stubs with real implementations:
```
tools/transaction_tools.py → connect to TransactionService
```

Test end to end:
```bash
curl ... -d '{"message": "spent 500 on swiggy", "thread_id": "tx-test-1"}'
# Should return a proposal card
# Then simulate confirm:
curl ... -d '{"message": "confirm", "thread_id": "tx-test-1"}'
# Should commit and return success
```

Proof of life: transaction appears in DB after confirm.

---

### Step 7 — Analytics graph

Files to create:
```
infrastructure/ai/graphs/analytics_graph.py
```

Replace query tool stubs with real implementations:
```
tools/query_tools.py → connect to TransactionRepository
```

Test:
```bash
curl ... -d '{"message": "what did I spend this week?", "thread_id": "an-1"}'
# Should return spending breakdown from real DB data
```

Proof of life: response contains actual figures from DB, not made-up numbers.

---

### Step 8 — Memory graph + context injection

Files to create:
```
infrastructure/ai/graphs/memory_graph.py
```

Replace memory tool stubs with real implementations:
```
tools/memory_tools.py → connect to MemoryRepository
```

Test:
1. Add a semantic memory row manually to DB
2. Start a new conversation
3. Agent's first response should reference that memory

Proof of life: agent uses stored user preferences without being told.

---

### Step 9 — Split graph

Files to create:
```
infrastructure/ai/graphs/split_graph.py
```

Replace split tool stubs:
```
tools/split_tools.py → connect to SplitService + SplitContactRepository
```

Test:
```bash
curl ... -d '{"message": "paid 600 for dinner for 3 people", "thread_id": "sp-1"}'
# Should return split proposal with 200 each
# Confirm → split appears in DB
```

Proof of life: split and split_members rows created in DB after confirm.

---

### Step 10 — Voice endpoint

Wire Azure STT into the voice endpoint.

Test with an actual audio file:
```bash
curl -X POST http://localhost:8000/api/v1/chat/voice \
  -H "Authorization: Bearer $TOKEN" \
  -F "audio=@test_audio.wav" \
  -F "thread_id=voice-test-1"
# Should transcribe and respond as if typed
```

Proof of life: spoken "spent 300 on chai" creates a transaction proposal.

---

### Step 11 — File graph

Files to create:
```
infrastructure/ai/graphs/file_graph.py
tools/file_tools.py  (real implementation: fpdf2 + openpyxl + Azure Blob)
```

Test:
```bash
curl ... -d '{"message": "give me a PDF report of this month", "thread_id": "file-1"}'
# Should return a download_url
curl "<that url>"
# Should download a real PDF
```

Proof of life: PDF downloads and contains real data.

---

### Step 12 — Bill image analysis

Wire vision tools into transaction and split graphs.

Test:
- Upload a photo of a receipt via the chat attachment
- Agent should extract merchant, amount, line items

Proof of life: agent correctly reads a real receipt image.

---

### Step 13 — Evaluation pipeline

Once all graphs work:

1. Create eval_dataset table (migration)
2. Start collecting corrections from production usage
3. Set up LangSmith experiment
4. Run first eval baseline

```python
# Weekly eval run
from langsmith import evaluate
results = evaluate(
    orchestrator.invoke,
    data="affordabled-extraction-eval",
    evaluators=[extraction_accuracy_evaluator],
    experiment_prefix="week-1"
)
```

---

### Step 14 — Load testing + rate limiting

Wire rate limiting into both chat endpoints:
```
tools/ (or middleware/) → check Redis counter per user per day
```

Load test:
```bash
# Send 55 messages — should block at 50
for i in $(seq 1 55); do
  curl ... -d '{"message": "test '$i'", "thread_id": "rate-test"}'
done
# Messages 51+ should return 429
```

---

### Milestone Checklist

```
[ ] Step 1  — Model + checkpointer connected
[ ] Step 2  — State + context loader
[ ] Step 3  — Guardrails (4/5 cases pass)
[ ] Step 4  — /chat endpoint responds, conversation persists
[ ] Step 5  — Tool stubs created
[ ] Step 6  — Transaction graph: propose → confirm → commit
[ ] Step 7  — Analytics graph: real figures from DB
[ ] Step 8  — Memory graph: agent uses stored preferences
[ ] Step 9  — Split graph: split created in DB after confirm
[ ] Step 10 — Voice: spoken input creates proposals
[ ] Step 11 — File graph: PDF/Excel downloads work
[ ] Step 12 — Bill image: receipt correctly read
[ ] Step 13 — Eval pipeline baseline established
[ ] Step 14 — Rate limiting blocks at 50 msgs/day
```

---

### Common Mistakes To Avoid

```
1. Importing repositories directly inside graph nodes
   → Always go through tools

2. LLM generating financial numbers in its response text
   → All numbers must come from tool results

3. Committing transactions without interrupt()
   → interrupt() is mandatory before any write

4. Using the same thread_id for different users
   → thread_id is always scoped to user_id in config

5. Running file_graph synchronously with large datasets
   → Render is fast (<1s) — no queue needed — but don't block

6. Skipping the stub phase (Step 5)
   → Stubs let you test graph logic independently of DB

7. Building all graphs before proving Step 4 works
   → Prove persistence first — everything else builds on it
```

---

*Document version: September 2026*
*Phase 1: Complete | Phase 2 AI layer: Ready to implement*
