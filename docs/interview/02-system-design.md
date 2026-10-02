# 🏗️ System Design — High-Level Architecture

## End-to-End Data Flow

```
User (Browser)
  │
  │  POST /debate/start-async { query, mode, agents, domain_pack, ... }
  │
  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (port 8000)                    │
│                                                                  │
│  API Layer (routes.py)                                           │
│  ├─ Validates request (Pydantic DebateStartRequest)              │
│  ├─ Resolves mode presets (quick/standard/thorough)              │
│  ├─ Resolves agent list (custom selection or domain pack)        │
│  ├─ Creates DebateState with UUID thread_id                      │
│  ├─ Creates SSE queue + replay buffer                            │
│  ├─ Spawns asyncio.Task for background debate execution          │
│  └─ Returns { thread_id, stream_url } immediately                │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │           DebateGraph (LangGraph StateGraph)               │  │
│  │                                                            │  │
│  │  DebateGraphState = {                                      │  │
│  │    debate_state: DebateState,  ← single source of truth    │  │
│  │    should_continue: bool,                                  │  │
│  │    final_decision: FinalDecision | None,                   │  │
│  │    hitl_mode: bool,                                        │  │
│  │    ...                                                     │  │
│  │  }                                                         │  │
│  │                                                            │  │
│  │  START → proposals → critiques → revisions → convergence   │  │
│  │            ▲                                    │          │  │
│  │            │   should_continue=True             │          │  │
│  │            └────────────────────────────────────┘          │  │
│  │                                                 │          │  │
│  │                  should_continue=False           │          │  │
│  │                                                 ▼          │  │
│  │                                             finalize       │  │
│  │                                                 │          │  │
│  │                                                END         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                         │                                        │
│              Each node emits SSE events                          │
│                    ▼         ▼                                   │
│          asyncio.Queue    SQLite (debate_events table)           │
│                                                                  │
│  On completion:                                                  │
│  ├─ Persists DebateState → debates table                         │
│  ├─ Persists FinalDecision → decisions table                     │
│  └─ Saves agent memory (LLM-summarised lessons)                  │
└──────────────────────────────────────────────────────────────────┘
  │
  │  GET /debate/{thread_id}/stream  (SSE)
  │  Events: debate_started, round_started, phase_started,
  │          agent_output, critique_completed, synthesis,
  │          debate_completed, approval_required, final_decision, error
  │
  ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Next.js Frontend (port 3000)                    │
│                                                                  │
│  DebateStreamViewer                                              │
│  ├─ EventSource → SSE connection with auto-reconnect             │
│  ├─ Renders rounds as they arrive (AgentCard, CritiqueView)     │
│  ├─ Updates ConfidenceDriftChart (recharts)                      │
│  ├─ Shows HITLPanel if approval_required                         │
│  └─ FinalDecisionPanel on completion                             │
└──────────────────────────────────────────────────────────────────┘
```

---

## Why This Architecture Was Chosen

### 1. LangGraph State Machine (not freestyle agent chat)

**Decision:** Use a compiled `StateGraph` with explicit nodes and edges, not a free-form agent loop.

**Why:**
- **Deterministic flow control** — The debate follows a strict propose → critique → revise → converge pipeline. A free-form agent conversation would be unpredictable.
- **Checkpointing for free** — LangGraph's `AsyncSqliteSaver` persists every state transition automatically. This enables pause/resume, HITL interrupts, and crash recovery.
- **Conditional branching** — The "quick" mode skips critique/revision phases by routing `proposals → convergence` via conditional edges. This is a one-line config in a state graph but a mess of if-statements in procedural code.
- **Debuggability** — LangGraph Studio provides time-travel debugging over the state history.

**Alternative rejected:** *Procedural orchestration loop* — The first version actually used a `DebateController` class with a `while should_continue:` loop. This was replaced with LangGraph because the controller couldn't cleanly support HITL pauses, checkpointing, or conditional phase skipping.

### 2. SSE over WebSockets

**Decision:** Server-Sent Events instead of WebSockets for live streaming.

**Why:**
- **Unidirectional** — The server pushes events; the client only needs to listen. WebSockets' bidirectional capability is unnecessary for this use case.
- **Auto-reconnect** — The browser's `EventSource` API has built-in reconnection with `Last-Event-ID`. WebSockets require custom reconnection logic.
- **HTTP/2 compatible** — SSE works naturally with HTTP/2 multiplexing. No separate connection upgrade protocol needed.
- **Simpler server implementation** — `StreamingResponse` with an async generator is ~20 lines. WebSockets need connection lifecycle management.

**Alternative rejected:** *WebSockets* — Would be needed if the client sent frequent messages during the debate (e.g., real-time collaborative editing). The only client→server message during a debate is the HITL approval, which uses a regular POST endpoint.

### 3. Pydantic Structured Output (not JSON mode)

**Decision:** Use LangChain's `with_structured_output()` which binds a Pydantic model as a function/tool call schema.

**Why:**
- **Type-safe at the boundary** — Every LLM response is validated against a Pydantic schema. Invalid responses raise `LLMResponseError` instead of silently corrupting state.
- **No JSON parsing boilerplate** — The original `GroqClient` had 40+ lines of JSON extraction, regex fallback, and retry-on-parse-failure. `with_structured_output()` eliminates all of it.
- **Provider-agnostic** — Works with Groq, OpenAI, Anthropic, and Gemini via different underlying mechanisms (tool calling, function calling, JSON mode) but the same API.

**Alternative rejected:** *Prompt-based JSON enforcement* — "Return your response as JSON with these fields..." This works 90% of the time but fails silently on the other 10% (malformed JSON, extra fields, wrong types).

### 4. SQLite (not PostgreSQL)

**Decision:** SQLite for all persistence (debates, decisions, events, agent memory, analytics).

**Why:**
- **Zero infrastructure** — No database server to install, configure, or maintain. The file is created automatically.
- **Sufficient for single-instance** — AgentBoard is designed as a single-user application. SQLite handles concurrent reads and serialised writes perfectly for this workload.
- **Alembic migrations work** — Schema evolution is handled through the same migration tooling as PostgreSQL.
- **Portable** — The entire database is one file. Copy it and you have the full history.

**Alternative for production:** *PostgreSQL* — Required if scaling to multi-user, multi-server deployment. The migration path is straightforward: change `DATABASE_URL` to a PostgreSQL connection string, update `aiosqlite` to `asyncpg`.

### 5. In-Memory State + DB Persistence (not pure DB)

**Decision:** Active debates live in Python dicts (`_debate_store`, `_decision_store`); completed debates are persisted to SQLite.

**Why:**
- **Performance** — SSE event emission needs sub-millisecond access to debate state. DB round-trips would add latency to every agent output event.
- **Simplicity** — `asyncio.Queue` for SSE broadcasting is far simpler than DB-based pub/sub.
- **Recovery** — The DB acts as a durable backup. If the server crashes, orphaned debates are recovered as "error" status on restart.

**Trade-off acknowledged:** This means active debates are lost on server crash. The mitigation is checkpointing (LangGraph saves state per-transition) and the `_persist_debate_state` callback that writes to SQLite after every phase.

### 6. Agent Registry Pattern

**Decision:** A centralised `AgentRegistry` where agents are registered at startup with their configs, and instantiated on-demand per debate.

**Why:**
- **Runtime configurability** — Enable/disable agents via environment variable (`ENABLED_AGENTS=Analyst,Risk,Ethics`) without code changes.
- **Per-agent model routing** — The Moderator can use GPT-4o while other agents use Groq Llama, configured per-agent in the registry.
- **Domain pack activation** — Domain agents (FinancialEthics, Security, etc.) are registered but disabled globally; activated per-debate when a domain pack is selected.
- **Tool allow-listing** — Each agent's permitted tools are stored in its config and enforced at registration time.

---

## Architecture Diagram — Layer Responsibilities

```
┌────────────────────────────────────────────────────────────────┐
│                       PRESENTATION LAYER                        │
│  Next.js 15 │ React 18 │ Tailwind │ recharts │ EventSource    │
│  App Router pages, shared components, keyboard-friendly UX     │
└──────────────────────────┬─────────────────────────────────────┘
                           │ HTTP REST + SSE
┌──────────────────────────┴─────────────────────────────────────┐
│                         API LAYER                               │
│  FastAPI │ Pydantic validation │ Rate limiting │ CORS          │
│  routes.py (debate CRUD + SSE) │ analytics.py (read-only)     │
│  dependencies.py (DI container for stores, queues, locks)      │
└──────────────────────────┬─────────────────────────────────────┘
                           │
┌──────────────────────────┴─────────────────────────────────────┐
│                     ORCHESTRATION LAYER                          │
│  LangGraph StateGraph │ DebateGraphState TypedDict              │
│  5 node factories: proposals, critiques, revisions,             │
│                     convergence, finalize                        │
│  Conditional edges for mode-based routing + HITL interrupt      │
└──────────┬───────────────┬──────────────┬──────────────────────┘
           │               │              │
┌──────────┴──────┐ ┌─────┴──────┐ ┌─────┴──────────────────────┐
│   AGENT LAYER   │ │  SERVICES  │ │        DATA LAYER          │
│  BaseAgent ABC  │ │ LLM Client │ │  SQLite (aiosqlite)        │
│  5 core agents  │ │ Consensus  │ │  debates, decisions,       │
│  4 domain agents│ │ RAG/KB     │ │  events, agent_memory      │
│  Tool registry  │ │ Memory     │ │  Alembic migrations        │
│  Agent registry │ │ Evaluator  │ │  LangGraph checkpoints     │
│                 │ │ Simulator  │ │                             │
│                 │ │ Exporter   │ │  ChromaDB (RAG vectors)    │
└─────────────────┘ └────────────┘ └─────────────────────────────┘
```

---

## Alternatives That Could Have Been Used

| Decision | Alternative | Why Rejected |
|----------|------------|--------------|
| LangGraph | AutoGen, CrewAI | AutoGen lacks structured state machines. CrewAI is sequential pipeline. LangGraph gives checkpointing + conditional routing + HITL interrupts. |
| FastAPI | Django, Flask | FastAPI: native async, Pydantic integration, auto OpenAPI docs. Django is overkill; Flask lacks native async. |
| SQLite | PostgreSQL, MongoDB | Zero-infrastructure requirement. SQLite is sufficient for single-instance. Upgrade path to Postgres exists via Alembic. |
| SSE | WebSockets, Long polling | SSE is simpler for unidirectional streaming. Built-in reconnect. No need for bidirectional comms. |
| ChromaDB | Pinecone, Weaviate, FAISS | ChromaDB is local, free, persistent. No cloud dependency. FAISS lacks persistence. Pinecone adds a service to manage. |
| sentence-transformers | OpenAI embeddings | Local embeddings = no API cost, no latency, works offline. Trade-off: lower quality than ada-002 but sufficient for consensus measurement. |
| Pydantic v2 | dataclasses, attrs | Pydantic provides validation, JSON serialization, OpenAPI schema generation. It's the natural choice with FastAPI. |
| Next.js App Router | Pages Router, Vite+React | App Router: server components, nested layouts, built-in error boundaries. Still uses client components for interactive pages. |
