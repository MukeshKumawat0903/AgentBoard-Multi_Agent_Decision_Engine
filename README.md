# AgentBoard — Multi-Agent Decision Engine

A full-stack **multi-agent AI debate system** where specialised AI agents collaboratively analyse strategic questions, cross-examine each other's positions, and converge on a well-reasoned consensus decision — with knowledge-base RAG, agent memory, human-in-the-loop approval, scenario simulation, decision evaluation, and a full analytics dashboard.

Built with **FastAPI**, **LangGraph**, **Next.js 15**, **React 18**, **Tailwind CSS**, **recharts**, and multi-provider LLM support (**GROQ** / **OpenAI** / **Anthropic** / **Gemini**).

---

## Screenshots

### New Debate workspace

| Light | Dark |
|---|---|
| ![AgentBoard — New Debate workspace (light)](assets/screenshots/01-home-light.png) | ![AgentBoard — New Debate workspace (dark)](assets/screenshots/01-home-dark.png) |

The landing page **is** the New Debate workspace: type a question, pick a debate **mode** — `Quick` (2 rounds, no critiques), `Standard` (2 rounds, full critique), `Thorough` (6 rounds), or `Custom` (pick your own round count + consensus threshold) — choose which of the five core agents (Analyst · Risk · Strategy · Ethics · Moderator) take part, toggle intelligence options (Knowledge Base RAG, Agent Memory, Supervised HITL), and start. Agents then debate live and converge on a decision you can defend.

> **More views:** the live debate stream, final-decision panel, analytics dashboard, history, and compare pages render against live data. To capture them, start the backend (`uvicorn app.main:app`) with a valid `GROQ_API_KEY`, run the frontend, open each page, and drop the PNGs into `assets/screenshots/` — then embed them here with `![Caption](assets/screenshots/<file>.png)`.

---

## How It Works

```
User submits a strategic question
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│              LangGraph Debate Engine                     │
│           (SSE streams each step live)                   │
│                                                         │
│  Round 1: Proposals                                     │
│    📊 Analyst  ⚠️ Risk  🎯 Strategy  🤝 Ethics          │
│    (optional: 💰 FinancialEthics, 🔒 Security, etc.)    │
│                                                         │
│  Round 2: Cross-Examination                             │
│    Each agent critiques the others                      │
│                                                         │
│  Round 3: Revisions                                     │
│    Agents refine positions based on critiques           │
│                                                         │
│  Round N: Convergence                                   │
│    🏛️ Moderator synthesises; a 5-signal hybrid gate      │
│    decides converge vs. keep debating                   │
│                                                         │
│  (Supervised mode: HITL approval before finalisation)   │
│                                                         │
│  Termination: consensus reached / max rounds /          │
│               human override                            │
└─────────────────────────────────────────────────────────┘
         │
         ▼
Final Decision with confidence scores, risk flags,
alternatives, minority report, key disagreements,
structured (agent-vs-agent) disagreements,
agent contributions, token usage + estimated cost,
and full debate trace
(persisted to SQLite for history, comparison & analytics)
```

---

## Agents

### Core Agents (always available)

| Agent | Icon | Role | Special Ability |
|---|---|---|---|
| **Analyst** | 📊 | Objective data analyst | Web search + date tools for factual grounding |
| **Risk** | ⚠️ | Adversarial risk assessor | Categorises risks by type & severity |
| **Strategy** | 🎯 | Actionable strategy proposer | Date tool for time-sensitive reasoning; 2+ alternatives |
| **Ethics** | 🤝 | Ethics & compliance guardian | **VETO power** on ethical violations |
| **Moderator** | 🏛️ | Neutral synthesiser | Produces the final consensus decision |

### Domain Agents (activated via domain packs)

| Agent | Icon | Domain Pack | Focus |
|---|---|---|---|
| **FinancialEthics** | 💰 | Finance | Fiduciary & ESG ethics |
| **Security** | 🔒 | Engineering/Tech | Cybersecurity & attack surface |
| **Compliance** | 📋 | Legal | Regulatory & legal compliance |
| **PatientSafety** | 🏥 | Healthcare | Clinical risk & patient welfare |

---

## Key Features

| Feature | Phase | Description |
|---|---|---|
| **Debate Modes** | P1 | Quick (2 rounds) · Standard (2 rounds) · Thorough (6 rounds), each with a `min_rounds` floor; round count is adjustable (2–6) per debate |
| **Hybrid Consensus Gate** | P1 | Converges only when 5 signals agree (position overlap, min rounds, dissent, open disagreements, confidence converged) — confidence alone can't end a debate |
| **Agent Registry** | P1 | Dynamic agent discovery, per-agent LLM overrides, enable/disable at runtime |
| **Per-Agent Model Routing** | P1 | Each agent can use a different provider/model (e.g. Moderator on GPT-5.5, others on Groq) |
| **Richer Final Output** | P1 | Minority report, key disagreements, structured (agent-vs-agent) disagreements, agent contribution scores |
| **Token & Cost Tracking** | P1 | Each decision reports aggregate `token_usage` and a best-effort `estimated_cost_usd` |
| **Debate Templates** | P2 | 16 built-in templates across Business, Technology, Strategy, Personal, Finance |
| **Export** | P2 | Markdown, PDF, and JSON export of final decisions |
| **Confidence Drift Chart** | P2 | Per-agent confidence line chart over debate rounds |
| **Knowledge Base RAG** | P3 | Upload PDF/TXT/MD → ChromaDB vector store → agents retrieve relevant context |
| **Controlled Tool Use** | P3 | DuckDuckGo web search, safe calculator, date tool — per-agent allow-list |
| **Agent Memory** | P3 | Agents remember lessons from past debates; injectable into new debates |
| **Domain Agent Packs** | P3 | Pre-configured agent sets for Finance, Engineering, Legal, Healthcare |
| **Human-in-the-Loop** | P4 | Supervised mode: approve, override, or add rounds before finalisation (dedicated `hitl` node) |
| **Cancellable Debates** | P4 | Cancel an in-flight async debate; the runner stops making LLM calls and emits a terminal `cancelled` event |
| **Scenario Simulation** | P4 | Run 2–5 parallel debates to test decision consistency (reports `runs_completed`) |
| **Decision Evaluation** | P4 | LLM-as-judge scores: completeness, consistency, actionability, risk awareness |
| **Analytics Dashboard** | P5 | KPI cards, debates/day trend, convergence curve, agent heatmap, quality scores |
| **LangSmith Tracing** | P5 | Full LLM call tracing via LangSmith (optional) |
| **Observability** | P5 | Structured JSON logging, X-Request-ID correlation, application metrics |

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Framework | FastAPI 0.115 |
| Language | Python 3.11+ |
| Orchestration | LangGraph ≥ 0.2 (state-machine debate graph) |
| LLM Providers | GROQ, OpenAI, Anthropic, Gemini (via LangChain) |
| Default Model | LLaMA 3.3 70B Versatile (GROQ) |
| Persistence | SQLite via aiosqlite (debates, decisions, SSE events, agent memory) |
| Migrations | Alembic (auto-applied on startup) |
| Streaming | Server-Sent Events (SSE) via asyncio.Queue |
| Knowledge Base | ChromaDB + sentence-transformers (all-MiniLM-L6-v2) |
| Rate Limiting | slowapi (per-IP) |
| Validation | Pydantic v2 |
| Configuration | pydantic-settings + `.env` |
| Testing | pytest + pytest-asyncio (~293 tests across 18 files) |

### Frontend

| Component | Technology |
|---|---|
| Framework | Next.js 15.1.7 (App Router) |
| UI Library | React 18.3.1 |
| Language | TypeScript 5.5.4 |
| Styling | Tailwind CSS 3.4.4 (semantic surface/line tokens) |
| Charts | recharts ^3.8.0 |
| Icons | lucide-react |
| Markdown | react-markdown + remark-gfm |
| Testing | Vitest + Testing Library (unit), Playwright (E2E) |
| Theme | Dark / Light mode with localStorage persistence |

---

## Project Structure

```
AgentBoard-Multi_Agent_Decision_Engine/
├── backend/
│   ├── app/
│   │   ├── agents/                # Agent implementations
│   │   │   ├── base_agent.py      #   Abstract base (run → critique → revise)
│   │   │   ├── analyst_agent.py   #   📊 Data-driven analyst
│   │   │   ├── risk_agent.py      #   ⚠️ Risk assessor
│   │   │   ├── strategy_agent.py  #   🎯 Strategy proposer
│   │   │   ├── ethics_agent.py    #   🤝 Ethics guardian
│   │   │   ├── moderator_agent.py #   🏛️ Consensus synthesiser
│   │   │   ├── domain_agents.py   #   💰🔒📋🏥 Domain-specific agents
│   │   │   ├── registry.py        #   Agent registry & per-agent LLM routing
│   │   │   └── tools.py           #   Tool implementations (search, calc, date)
│   │   ├── api/
│   │   │   ├── routes.py          # REST + SSE endpoints
│   │   │   ├── analytics.py       # Analytics endpoints (P5)
│   │   │   └── dependencies.py    # Dependency injection & per-thread locks
│   │   ├── orchestrator/
│   │   │   ├── debate_graph.py    # LangGraph state-machine debate flow
│   │   │   ├── lg_state.py        # LangGraph typed state definition
│   │   │   └── nodes.py           # 5 graph node factories + HITL interrupt
│   │   ├── services/
│   │   │   ├── llm_client.py      # Multi-provider LLM client
│   │   │   ├── consensus.py       # Agreement scoring & semantic consensus
│   │   │   ├── retriever.py       # Knowledge base RAG (ChromaDB)
│   │   │   ├── agent_memory.py    # Agent memory store
│   │   │   ├── evaluator.py       # Decision quality evaluation (LLM-as-judge)
│   │   │   ├── exporter.py        # Markdown & PDF export
│   │   │   └── simulation.py      # Multi-run scenario simulation
│   │   ├── schemas/               # Pydantic models (state, responses, API)
│   │   ├── core/                  # Config, logging, metrics, rate limiting, audit
│   │   ├── db/                    # SQLite persistence (CRUD, migrations)
│   │   ├── data/                  # Templates & domain pack definitions
│   │   ├── utils/                 # Custom exceptions
│   │   └── main.py                # FastAPI app entry point & lifespan
│   ├── alembic/                   # Database migration scripts
│   ├── tests/                     # ~293 unit & integration tests (18 files)
│   └── Notebooks/                 # 9 learning/exploration notebooks
├── frontend/
│   └── src/
│       ├── app/                   # Next.js pages & layout
│       │   ├── debate/[threadId]/ #   Live SSE streaming page
│       │   ├── history/           #   Searchable debate history
│       │   ├── compare/           #   Side-by-side comparison
│       │   ├── simulate/          #   Scenario simulation (P4)
│       │   ├── knowledge/         #   Knowledge base management (P3)
│       │   ├── memory/            #   Agent memory browser (P3)
│       │   └── analytics/         #   Analytics dashboard (P5)
│       ├── components/            # 21 components + ui/ design-system primitives + __tests__/
│       ├── lib/                   # API client, types, SSE reducer, hooks
│       └── types/                 # Fallback type stubs
├── docs/
│   ├── backend/                   # 7 backend documentation files
│   ├── frontend/                  # 6 frontend documentation files
│   ├── plan/                      # Roadmap & migration plans
│   └── Future_Scope/              # Future scope documents
├── command.md                     # Detailed setup & run guide
└── README.md
```

---

## Quick Start

### Prerequisites

- **Python 3.11+** — [python.org](https://www.python.org/downloads/)
- **Node.js 18+** (LTS) — [nodejs.org](https://nodejs.org/)
- **GROQ API Key** (free) — [console.groq.com](https://console.groq.com/)

### 1. Backend

```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
copy .env.example .env          # then add your GROQ_API_KEY
uvicorn app.main:app --reload --port 8000
```

Alembic migrations run automatically on startup.

### 2. Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

### 3. Open

Navigate to **http://localhost:3000**, type a strategic question, and start a debate.

---

## API Endpoints

### Debate

| Method | Path | Description |
|---|---|---|
| `POST` | `/debate/start` | Start a debate (synchronous, returns `FinalDecision`) |
| `POST` | `/debate/start-async` | Start a debate in background (returns `thread_id` + `stream_url`) |
| `GET` | `/debate/{thread_id}/stream` | SSE stream of live debate events |
| `GET` | `/debate/{thread_id}` | Get debate status and round history |
| `POST` | `/debate/{thread_id}/resume` | Resume from the last LangGraph checkpoint |
| `POST` | `/debate/{thread_id}/cancel` | Cancel an in-flight async debate |
| `POST` | `/debate/{thread_id}/approve` | Human-in-the-loop: approve / override / add round (JSON body) |
| `POST` | `/debate/simulate` | Run 2–5 parallel debates for consistency testing |
| `GET` | `/decision/{thread_id}` | Retrieve the final decision |
| `GET` | `/decision/{thread_id}/export` | Export as Markdown, PDF, or JSON |
| `POST` | `/decision/{thread_id}/evaluate` | LLM-as-judge quality evaluation |

### Discovery & Configuration

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check — status, version, provider configured |
| `GET` | `/metrics` | Application metrics snapshot (requests, routes, business events) |
| `GET` | `/agents` | List all registered agents with config |
| `GET` | `/templates` | Browse debate templates (filterable by category) |
| `GET` | `/domain-packs` | List available domain agent packs |
| `GET` | `/history` | Paginated debate history (search, sort, filter) |
| `GET` | `/history/{thread_id}` | Retrieve a single history item |
| `GET` / `POST` | `/llm-settings` | View / switch the active LLM provider & model at runtime |

### Intelligence (Phase 3)

| Method | Path | Description |
|---|---|---|
| `POST` | `/knowledge/upload` | Upload PDF/TXT/MD to knowledge base |
| `GET` | `/knowledge/documents` | List uploaded documents |
| `DELETE` | `/knowledge/documents/{name}` | Delete a document |
| `GET` | `/memory/{agent_name}` | Get recent memory entries for an agent |
| `DELETE` | `/memory/{agent_name}` | Clear all memory for an agent |

### Analytics (Phase 5)

| Method | Path | Description |
|---|---|---|
| `GET` | `/analytics/overview` | KPIs: total debates, avg rounds, consensus rate |
| `GET` | `/analytics/agents` | Per-agent confidence, contribution, agreement matrix |
| `GET` | `/analytics/convergence` | Agreement-by-round, mode/domain breakdowns |
| `GET` | `/analytics/quality` | Quality scores by template, mode, domain pack |

**Interactive docs:** http://localhost:8000/docs (Swagger UI)

### Example

```bash
curl -X POST http://localhost:8000/debate/start-async \
  -H "Content-Type: application/json" \
  -d '{"query": "Should our company expand into the Asian market in Q3?", "mode": "standard"}'
```

---

## Configuration

All backend settings are configured via `backend/.env`:

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** | — | Your GROQ API key |
| `LLM_PROVIDER` | No | `groq` | Active provider: `groq` / `openai` / `anthropic` / `gemini` |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Model for GROQ provider |
| `OPENAI_API_KEY` | No | — | Required if `LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | No | `gpt-5.5` | Model for OpenAI provider |
| `ANTHROPIC_API_KEY` | No | — | Required if `LLM_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL` | No | `claude-opus-4-8` | Model for Anthropic provider |
| `GEMINI_API_KEY` | No | — | Required if `LLM_PROVIDER=gemini` |
| `GEMINI_MODEL` | No | `gemini-3.5-flash` | Model for Gemini provider |
| `MAX_DEBATE_ROUNDS` | No | `2` | Orchestrator-level max rounds (fallback when not API-resolved) |
| `MIN_DEBATE_ROUNDS` | No | `2` | Floor on rounds before consensus may be declared |
| `CONSENSUS_THRESHOLD` | No | `0.75` | Position-agreement score to stop early (0.0–1.0) |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | Allowed frontend origins |
| `DATABASE_URL` | No | `agentboard.db` | SQLite database path |
| `CHECKPOINT_DATABASE_URL` | No | `agentboard_checkpoints.db` | LangGraph checkpoint DB |
| `RATE_LIMIT_PER_MINUTE` | No | `30` | API rate limit per IP |
| `ENABLED_AGENTS` | No | `Analyst,Risk,Strategy,Ethics,Moderator` | Comma-separated enabled agent names |
| `DEBATE_TTL_DAYS` | No | `90` | Auto-cleanup debates older than N days |
| `KNOWLEDGE_BASE_DIR` | No | `knowledge_base` | ChromaDB vector store directory |
| `HITL_ENABLED` | No | `True` | Enable human-in-the-loop approval |
| `SEMANTIC_CONSENSUS_ENABLED` | No | `False` | Use semantic embeddings for consensus |
| `LANGSMITH_TRACING` | No | `False` | Enable LangSmith LLM call tracing |
| `LANGSMITH_API_KEY` | No | — | LangSmith API key |
| `LANGSMITH_PROJECT` | No | `agentboard` | LangSmith project name |

Frontend: `frontend/.env.local` contains `NEXT_PUBLIC_API_URL=http://localhost:8000`.

---

## Testing

```bash
cd backend

# Run all ~293 tests (fast, mocked — no API calls)
pytest -v --tb=short

# Skip integration tests (that need a real API key)
pytest -m "not integration" -v

# Run a specific test file
pytest tests/test_consensus.py -v

# Frontend: typecheck + unit tests + lint
cd ../frontend
npm run verify          # lint + tsc --noEmit + vitest
npm run e2e             # Playwright end-to-end (needs the app running)
```

**Test coverage (backend, 18 files):**

| Area | File | Focus |
|---|---|---|
| Schemas | `test_schemas.py` | Pydantic model validation, bounds, defaults |
| Base Agent | `test_base_agent.py` | LLM calling, structured output, KB/memory/tool hooks |
| Agents | `test_agents.py` | All 5 core agents — prompt construction, context-awareness |
| LLM Client | `test_llm_client.py` | Provider factory, retry, sampling guard |
| Consensus | `test_consensus.py` | Agreement scoring (V1/V1.5/V2), drift, hybrid gate signals |
| Orchestrator | `test_orchestrator.py` | State machine, termination, contribution, graceful degradation |
| HITL | `test_hitl.py` | Supervised interrupt + approve/override/add_round |
| Simulation / Evaluation | `test_simulation_service.py`, `test_evaluation_service.py` | Stability metrics; LLM-as-judge + caching |
| Retriever / Memory | `test_retriever.py`, `test_agent_memory.py` | RAG chunking/retrieval; memory store |
| Registry / Contracts | `test_registry_extended.py`, `test_contracts.py` | Overrides + tool validation; API contracts |
| API / Cleanup | `test_api.py`, `test_db_cleanup.py`, `test_sse_cleanup.py` | Endpoints; TTL purge; SSE lifecycle |
| Analytics / Observability | `test_analytics.py`, `test_observability.py` | Analytics + caching; metrics, Request-ID, audit |

---

## Frontend Features

- **Debate Templates** — 16 built-in templates across 5 categories with one-click start
- **Domain Pack Selector** — Finance, Engineering, Legal, Healthcare agent configurations
- **Debate Mode Selector** — Quick / Standard / Thorough presets plus a Custom option (pick round count 2–6 and consensus threshold)
- **Agent Chips** — Toggle agents on/off; Moderator always required
- **Intelligence Toggles** — Knowledge Base, Agent Memory, Supervised mode
- **Live SSE Streaming** — Real-time agent outputs, tool calls, critiques, syntheses as they are produced
- **Connection Status** — ● Connected / ↺ Reconnecting / ✕ Disconnected with auto-reconnect, plus REST-polling fallback if SSE keeps failing
- **Cancel** — Stop an in-flight debate so the backend stops making LLM calls
- **HITL Approval Panel** — Approve, override, or extend the debate in supervised mode
- **Confidence Drift Chart** — Per-agent confidence line chart (recharts) over rounds
- **Decision Panel** — Markdown-rendered decision & rationale, risk flags, minority report, key disagreements, structured (agent-vs-agent) disagreements, contribution scores, token usage + estimated cost, full trace
- **Export & Copy** — Markdown, PDF, or JSON download; one-click copy of the decision text
- **Decision Evaluation** — LLM-as-judge quality scores (completeness, consistency, actionability, risk awareness)
- **Scenario Simulation** — Run 2–5 parallel debates; stability rating, variance, stable risk flags
- **History Browser** — Search, filter (termination reason), sort (newest/oldest/highest agreement), paginate
- **Compare View** — Side-by-side decisions with confidence delta, risk flag diff, "Run both again" → simulation
- **Knowledge Base Manager** — Upload/delete PDF, TXT, MD documents; chunk counts
- **Agent Memory Browser** — Per-agent memory entries with clear option
- **Analytics Dashboard** — Three tabs: Overview (KPIs, trends, convergence), Agents (confidence, heatmap), Quality (scores by mode/template/domain)
- **Dark Mode** — Toggle with flash-free initialisation and `localStorage` persistence
- **Keyboard Navigation** — J/K to scroll rounds, Esc to deselect
- **Error Boundaries** — Per-route error handling with retry/recovery UI

---

## Phase Implementation Status

| Phase | Name | Status |
|---|---|---|
| **Phase 0** | Minimal Stability Baseline | ✅ Complete |
| **Phase 1** | Platform Configurability | ✅ Complete |
| **Phase 2** | Core Product Features | ✅ Complete |
| **Phase 3** | Intelligence Features | ✅ Complete |
| **Phase 4** | Advanced Debate Mechanics (4.1–4.3) | ✅ Complete |
| **Phase 4.4** | Advanced Mechanics (branching, voting, coalition) | ⬚ Planned |
| **Phase 5** | Analytics & Evaluation | ✅ Complete |
| **Phase 6** | Testing Hardening | 🔄 In Progress |
| **Phase 7–9** | Deployment, Security, Multi-User | ⬚ Planned |

See [docs/plan/platform_feature_extensions_roadmap.md](docs/plan/platform_feature_extensions_roadmap.md) for the full roadmap.

---

## Documentation

Detailed documentation is available in the `docs/` folder:

### Backend (`docs/backend/`)

| File | Topic |
|---|---|
| `01-architecture-overview.md` | Tech stack, directory structure, request lifecycle, design principles |
| `02-api-reference.md` | All 25+ endpoints, schemas, 13 SSE event types, error codes |
| `03-agent-system.md` | 9 agents, BaseAgent ABC, registry, tools, domain agents |
| `04-debate-engine.md` | LangGraph graph, 6 nodes, hybrid gate, HITL node, modes, checkpointing |
| `05-consensus-and-llm-client.md` | Hybrid consensus gate, scoring formulas, multi-provider LLM client, cost estimation |
| `06-configuration-and-logging.md` | All settings, env vars, structured logging, metrics, LangSmith |
| `07-testing-strategy.md` | ~293 tests, 18 test files, fixtures, pytest config |

### Frontend (`docs/frontend/`)

| File | Topic |
|---|---|
| `01-architecture-overview.md` | Tech stack, directory structure, SSE flow, state management |
| `02-pages-and-routing.md` | 8 routes, error boundaries, layout, all pages |
| `03-component-library.md` | 21 components + 6 ui/ primitives — props, state, features |
| `04-api-integration-and-types.md` | 27 API functions, SSE connection, TypeScript interfaces, 13 SSE event types |
| `05-styling-and-dark-mode.md` | Tailwind config, semantic surface/line tokens, dark mode, agent colour system |
| `06-configuration-and-setup.md` | Next.js config, TypeScript, dependencies, build output |

See also: [command.md](command.md) for the complete step-by-step setup guide.

---

## License

This project is for educational and personal use.
