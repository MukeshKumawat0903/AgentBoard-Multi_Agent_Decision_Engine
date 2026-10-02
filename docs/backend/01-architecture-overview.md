# Backend Architecture Overview

This document provides a high-level view of the AgentBoard backend — a FastAPI application that orchestrates multi-agent debates using **LangGraph** state-graph orchestration with multi-provider LLM support, real-time SSE streaming, and SQLite persistence.

---

## Tech Stack

Versions are the ones pinned in `backend/requirements.lock` (the set CI tests and Docker installs). `requirements.txt` lists the direct dependencies with the ranges the code supports.

| Layer | Technology | Pinned version |
|---|---|---|
| Framework | FastAPI (Starlette 1.0) + Uvicorn | 0.135.2 / 0.42.0 |
| Language | Python | 3.11 (image and CI) |
| Orchestration | LangGraph + SQLite checkpointer | 1.1.3 / checkpoint-sqlite 3.0.3 |
| LLM Providers | GROQ / OpenAI / Anthropic / Gemini via LangChain (`langchain-core` 1.4.7) | — |
| Default Model | LLaMA 3.3 70B Versatile (GROQ) | — |
| Validation | Pydantic v2 + pydantic-settings | 2.13.4 / 2.13.1 |
| Database | aiosqlite (async SQLite, WAL mode) | 0.22.1 |
| Migrations | Alembic | 1.18.4 |
| Rate Limiting | slowapi (per client IP, trusted-proxy aware) | 0.1.9 |
| Observability | LangSmith tracing (optional) | 0.7.22 |
| Knowledge Base | ChromaDB + sentence-transformers (CPU-only torch) | 1.5.9 / 6.1.0 |
| Semantic Consensus | sentence-transformers (optional) | 6.1.0 |
| PDF export | WeasyPrint | 69.0 |
| Logging | stdlib `logging` + JSON formatter, daily rotation | — |
| Testing / lint | pytest + pytest-asyncio, ruff, mypy | 9.0.3 / see `requirements-dev.lock` |

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py                    # FastAPI entry point, lifespan, middleware, exception handlers, /health
│   ├── __init__.py
│   │
│   ├── agents/                    # Specialised AI agents
│   │   ├── base_agent.py          # Abstract base class (ABC) for all agents, _call_structured()
│   │   ├── analyst_agent.py       # Objective data analyst
│   │   ├── risk_agent.py          # Adversarial risk assessor
│   │   ├── strategy_agent.py      # Actionable strategy proposer
│   │   ├── ethics_agent.py        # Ethics and compliance guardian (structured veto)
│   │   ├── moderator_agent.py     # Neutral synthesizer and final decision
│   │   ├── domain_agents.py       # Domain-specific agents (FinancialEthics, Security, Compliance, PatientSafety)
│   │   ├── registry.py            # Agent registry & per-agent LLM routing
│   │   └── tools.py               # Safe tool implementations: search, calculator, date
│   │
│   ├── api/                       # REST API layer
│   │   ├── routes.py              # Endpoint definitions (sync, async, SSE, HITL, history, jobs, admin)
│   │   ├── dependencies.py        # FastAPI Depends() factories & bounded in-memory stores
│   │   └── analytics.py           # Analytics endpoints (+ cache invalidation)
│   │
│   ├── core/                      # Application-wide config & cross-cutting concerns
│   │   ├── config.py              # pydantic-settings Settings singleton
│   │   ├── logging_config.py      # JSON-formatted structured logging
│   │   ├── rate_limiter.py        # Per-client-IP rate limiting (slowapi, trusted proxies)
│   │   ├── security.py            # require_admin dependency (X-Admin-Token)
│   │   ├── audit.py               # Audit event logger
│   │   ├── request_context.py     # Request-ID context variable for logs
│   │   └── metrics.py             # In-process metrics counters
│   │
│   ├── db/                        # SQLite persistence layer
│   │   ├── database.py            # Alembic migrations at startup, WAL, async connection
│   │   └── crud.py                # CRUD + history query + analytics aggregations
│   │
│   ├── orchestrator/              # LangGraph debate lifecycle management
│   │   ├── debate_graph.py        # StateGraph, checkpointer, SSE emission, checkpoint pruning
│   │   ├── lg_state.py            # DebateGraphState TypedDict (graph state schema)
│   │   └── nodes.py               # Node factories (proposals, critiques, revisions, convergence, hitl, finalize)
│   │
│   ├── schemas/                   # Pydantic v2 data models
│   │   ├── agent_response.py      # AgentResponse, CritiqueResponse
│   │   ├── api_models.py          # Request/response models, mode presets, DEFAULT_DEBATE_MODE resolution
│   │   ├── final_decision.py      # FinalDecision, VetoEntry, StructuredDisagreement, …
│   │   └── state.py               # DebateState, DebateRound
│   │
│   ├── services/                  # Services used by the API and the graph
│   │   ├── llm_client.py          # LangChainProvider, per-provider concurrency slot, server key map
│   │   ├── consensus.py           # ConsensusEngine, hybrid gate, SemanticConsensusEngine
│   │   ├── retriever.py           # Knowledge base RAG via ChromaDB (lazy, non-blocking init)
│   │   ├── agent_memory.py        # Agent memory store
│   │   ├── evaluator.py           # Decision quality evaluation (LLM-as-judge)
│   │   ├── exporter.py            # Markdown, HTML & PDF export
│   │   └── simulation.py          # Multi-run scenario simulation and stability metrics
│   │
│   ├── data/                      # Built-in data
│   │   ├── templates.py           # 17 built-in debate templates
│   │   └── domain_packs.py        # 4 domain packs (finance, engineering, legal, healthcare)
│   │
│   └── utils/                     # Cross-cutting utilities
│       ├── exceptions.py          # Custom exception hierarchy + public_error_message()
│       └── helpers.py
│
├── alembic/                       # Database migrations (applied automatically at startup)
│   ├── env.py
│   ├── script.py.mako
│   └── versions/                  # initial schema → phase3/4 tables → agent-memory NOCASE index
│
├── tests/                         # ~50 test modules (unit + integration), all LLM calls mocked
│   ├── conftest.py                # Isolates every test: temp DBs, checkpoint DB, KB dir and log dir
│   └── test_*.py                  # See 07-testing-strategy.md
│
├── logs/                          # Rotating daily log files (auto-created, git-ignored)
├── pyproject.toml                 # pytest, mypy and ruff configuration
├── requirements.txt               # Direct production dependencies (ranges)
├── requirements.lock              # Pinned production set (Docker)
├── requirements-dev.txt           # Dev/test tools + how to regenerate the locks
├── requirements-dev.lock          # Pinned production + dev set (CI, local venv)
├── Dockerfile                     # Multi-stage image, installs requirements.lock
├── .env.example                   # Environment variable template
└── .env                           # Local environment (git-ignored)
```

---

## Request Lifecycle

### Synchronous (POST /debate/start)

```
Client (Next.js, via the /backend/* route-handler proxy)
  │
  ▼
FastAPI (main.py)
  │  RequestIDMiddleware (X-Request-ID injection, request log with client IP)
  │  UploadSizeLimitMiddleware (rejects oversized /knowledge/upload bodies early)
  │  CORS middleware
  │  SlowAPI rate limiting (per client IP; X-Forwarded-For only from TRUSTED_PROXY_IPS)
  │  Exception handlers (502/503/429/500)
  ▼
API Router (routes.py)
  │  Dependency injection via dependencies.py
  │  Validates the request (mode presets, ≥ 2 debating agents, template id)
  ▼
DebateGraph (debate_graph.py)
  │  Creates DebateState with unique thread_id
  │  Builds LangGraph StateGraph with SQLite checkpointer
  │  Executes graph:
  │    ┌─────────────────────────────────────────────┐
  │    │  proposals → critiques → revisions          │
  │    │       → convergence (loop, hitl or finalize) │
  │    └──────────────┬──────────────────────────────┘
  │                   │ loop until consensus or max rounds
  │                   ▼
  │             ModeratorAgent.finalize()
  ▼
FinalDecision persisted to SQLite, checkpoints deleted, decision returned
```

### Asynchronous with SSE (POST /debate/start-async + GET /debate/{id}/stream)

```
Client (Next.js)
  │
  ├─ POST /debate/start-async → thread_id + stream_url (instant response)
  │
  ├─ GET /debate/{thread_id}/stream → SSE connection
  │     Server pushes events: debate_started, round_started, phase_started,
  │     agent_output, critique_completed, synthesis, tool_called, agent_timeout,
  │     approval_required (HITL), debate_resumed, debate_completed,
  │     final_decision, cancelled, error — plus a named `ping` every 20 s.
  │     Each event has an id; a reconnect resumes after Last-Event-ID.
  │
  ├─ Background task: DebateGraph.run() with event emission
  │     Each node emits typed events via _emit() → asyncio.Queue
  │     A writer persists events to SQLite; late joiners get a replay
  │
  ├─ HITL: in supervised mode the graph routes through a dedicated hitl
  │     node when convergence decides to stop. A LangGraph interrupt()
  │     pauses there and emits approval_required. POST /debate/{id}/approve
  │     (approve / override / add_round) answers with 202 and continues the
  │     debate in the background on the same stream.
  │
  └─ Final: debate_completed + final_decision events
```

Failed or interrupted debates that still have a checkpoint can be continued with `POST /debate/{id}/resume-async` (202, streams `debate_resumed` then the remaining events).

### Background jobs (simulations)

`POST /debate/simulate-async` returns a job id (202); the client polls `GET /debate/simulate/{job_id}` and can cancel with `POST /debate/simulate/{job_id}/cancel`. A single long request would outlive proxy timeouts, so the synchronous `POST /debate/simulate` is kept only for API clients.

---

## Runtime LLM Provider Switching

The backend supports switching between Groq, OpenAI, Anthropic, and Gemini **at runtime** via `GET/POST /llm-settings`, without a server restart.

- `reset_llm_client()` replaces the global `LangChainProvider` singleton in memory.
- Switching changes the provider for **every** user, so `POST /llm-settings` is an admin action: it requires the `X-Admin-Token` header when `ADMIN_API_TOKEN` is set, and is refused in production when no token is configured.
- The server's key for the chosen provider (`*_API_KEY` in `.env`) is used when present; otherwise the caller supplies one, held in memory only and never persisted. `GET /llm-settings` reports which providers have a server key (`server_keys`) and whether an admin token is required.
- One provider → key map (`server_api_key()`) is shared by the global client and per-agent model overrides; `server_default_model()` gives each provider's configured model.
- The available models per provider are defined in `PROVIDER_MODELS` (`app/schemas/api_models.py`).
- Some models (Anthropic Opus 4.7+/Fable, OpenAI `gpt-5*`) reject sampling parameters; `LangChainProvider._sampling_kwargs()` omits `temperature` for those so calls don't 400.
- `/health` reports the live provider: `llm: {provider, model, configured}`.

See [05-consensus-and-llm-client.md](05-consensus-and-llm-client.md) for detailed implementation and [02-api-reference.md](02-api-reference.md) for the endpoint specification.

---

## Key Design Principles

1. **Single Source of Truth** — `DebateState` is the sole mutable object. Every component reads from and writes to it.

2. **LangGraph Orchestration** — The debate lifecycle is modelled as a compiled `StateGraph` with typed nodes and conditional edges. SQLite checkpointing enables HITL pause/resume and resuming failed debates; checkpoints of finished debates are deleted, and startup prunes leftovers.

3. **Parallel Execution, Sequential Phases** — Within each phase, agent calls run concurrently via `asyncio.gather()` with configurable per-agent timeouts (default 45 s; tool-using agents get a 1.5× multiplier). A per-provider slot (`LLM_MAX_CONCURRENCY`, default 4) caps calls in flight so bursts don't trigger provider 429s; the slot is taken before an agent's timeout starts.

4. **Graceful Degradation** — If an individual agent fails (timeout, parse error), the debate continues with the remaining agents. If the moderator's per-round synthesis fails but agents produced output, a placeholder synthesis keeps the round alive. Rate-limit errors are classified (`LLMRateLimitError`) and the moderator backs off and retries.

5. **Structured Output via LangChain** — All LLM calls use `with_structured_output()` to enforce Pydantic schemas at the model level, through `BaseAgent._call_structured()` (logging, per-agent temperature and retries) — including the moderator.

6. **Multi-Provider LLM Support** — Swap between GROQ, OpenAI, Anthropic, and Gemini via `LLM_PROVIDER`. Only the active provider's key is required at startup.

7. **Real-Time SSE Streaming** — Typed events with ids, a 20 s `ping` keep-alive, Last-Event-ID resume, and a replay for late joiners. Streams of finished debates end after the terminal event.

8. **Dependency Injection** — External dependencies (LLM client, stores, settings, database) are injected via FastAPI's `Depends()`, making every component independently testable.

9. **Dual Storage** — Bounded in-memory stores (only finished debates are evicted) for live debates, with SQLite (WAL mode, so readers don't block the event writer; the writer retries when the database is busy) for history, events, recovery and analytics.

10. **Rate Limiting per Client** — `slowapi` keys limits on the real client IP; `X-Forwarded-For` is only trusted from `TRUSTED_PROXY_IPS` (the Next.js proxy), so one user can't exhaust everyone's quota.

11. **Agent Registry** — Dynamic agent discovery via `AgentRegistry` with per-agent LLM model overrides and tool allow-lists. A debate needs at least two agents besides the Moderator.

12. **Knowledge Base RAG** — Agents can retrieve context from uploaded documents via ChromaDB. The embedding model loads in the background at startup, so the API is available immediately.

13. **Human-in-the-Loop** — Supervised mode uses LangGraph `interrupt()` in a dedicated `hitl` node, so the moderator's synthesis never re-runs on resume. An override's feedback is passed to the final decision and shown as "Human reviewer direction".

14. **Hybrid Consensus Gate** — A debate converges only when all signals agree: normalised position agreement ≥ threshold, minimum rounds completed, few dissenting agents, few open high-severity disagreements, confidence has stabilised, and **no Ethics veto stands**. The moderator's own continue/stop opinion is advisory only. See [05-consensus-and-llm-client.md](05-consensus-and-llm-client.md).

15. **Token & Cost Accounting** — Every graph segment is wrapped in a LangChain usage callback; usage accumulates across HITL/resume segments (`token_usage_by_model`), so each `FinalDecision` carries total `token_usage` and a best-effort `estimated_cost_usd`.

16. **Graceful Cancellation** — Running or paused debates can be cancelled via `POST /debate/{thread_id}/cancel`; the debate ends with status `cancelled` and a terminal `cancelled` SSE event.

17. **Admin-only operations** — Switching the LLM provider, clearing agent memory and deleting knowledge-base documents go through `require_admin` (`X-Admin-Token`, constant-time comparison).

18. **Cheap by default** — Debates and simulations that don't pick a mode use `DEFAULT_DEBATE_MODE` (Quick unless configured), and the UI pre-selects it.
