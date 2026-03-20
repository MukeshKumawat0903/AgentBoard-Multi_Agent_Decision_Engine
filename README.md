# AgentBoard — Multi-Agent Decision Engine

A full-stack **multi-agent AI debate system** where five specialised AI agents collaboratively analyse strategic questions, cross-examine each other's positions, and converge on a well-reasoned consensus decision.

Built with **FastAPI**, **LangGraph**, **Next.js 15**, **React 18**, **Tailwind CSS**, and multi-provider LLM support (**GROQ** / **OpenAI** / **Anthropic**).

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
│    📊 Analyst  ⚠️ Risk  🎯 Strategy  ⚖️ Ethics          │
│                                                         │
│  Round 2: Cross-Examination                             │
│    Each agent critiques the others                      │
│                                                         │
│  Round 3: Revisions                                     │
│    Agents refine positions based on critiques           │
│                                                         │
│  Round N: Convergence                                   │
│    🏛️ Moderator synthesises a final decision             │
│                                                         │
│  Termination: consensus reached / max rounds / veto     │
└─────────────────────────────────────────────────────────┘
         │
         ▼
Final Decision with confidence scores,
risk flags, alternatives, and full debate trace
(persisted to SQLite for history & comparison)
```

---

## The Five Agents

| Agent | Icon | Role | Special Ability |
|---|---|---|---|
| **Analyst** | 📊 | Objective data analyst | Market/data-driven positions |
| **Risk** | ⚠️ | Adversarial risk assessor | Categorises risks by type & severity |
| **Strategy** | 🎯 | Actionable strategy proposer | Always proposes 2+ alternatives |
| **Ethics** | ⚖️ | Ethics & compliance guardian | **VETO power** on ethical violations |
| **Moderator** | 🏛️ | Neutral synthesiser | Produces the final consensus decision |

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Framework | FastAPI 0.115 |
| Language | Python 3.11+ |
| Orchestration | LangGraph ≥ 0.2 (state-machine debate graph) |
| LLM Providers | GROQ, OpenAI, Anthropic (via LangChain) |
| Default Model | LLaMA 3.3 70B Versatile (GROQ) |
| Persistence | SQLite via aiosqlite (debates, decisions, SSE events) |
| Streaming | Server-Sent Events (SSE) via asyncio.Queue |
| Rate Limiting | slowapi (per-IP) |
| Validation | Pydantic v2 |
| Configuration | pydantic-settings + `.env` |
| Testing | pytest + pytest-asyncio (223 tests) |

### Frontend

| Component | Technology |
|---|---|
| Framework | Next.js 15.1.7 (App Router) |
| UI Library | React 18.3.1 |
| Language | TypeScript 5.5.4 |
| Styling | Tailwind CSS 3.4.4 |
| Theme | Dark / Light mode with localStorage persistence |

---

## Project Structure

```
AgentBoard-Multi_Agent_Decision_Engine/
├── backend/
│   ├── app/
│   │   ├── agents/              # 5 AI agent implementations
│   │   │   ├── base_agent.py    #   Abstract base (run → critique → revise)
│   │   │   ├── analyst_agent.py
│   │   │   ├── risk_agent.py
│   │   │   ├── strategy_agent.py
│   │   │   ├── ethics_agent.py
│   │   │   └── moderator_agent.py
│   │   ├── api/
│   │   │   ├── routes.py        # REST + SSE endpoints
│   │   │   └── dependencies.py  # Dependency injection
│   │   ├── orchestrator/
│   │   │   ├── debate_graph.py  # LangGraph state-machine debate flow
│   │   │   ├── lg_state.py      # LangGraph typed state definition
│   │   │   └── nodes.py         # Graph node functions (run_agents, critique, synthesise)
│   │   ├── services/
│   │   │   ├── llm_client.py    # Multi-provider LLM client (GROQ/OpenAI/Anthropic)
│   │   │   └── consensus.py     # Agreement scoring & semantic consensus
│   │   ├── schemas/             # Pydantic models
│   │   ├── core/                # Config, logging & rate limiting
│   │   ├── db/                  # SQLite persistence (CRUD, database init)
│   │   ├── utils/               # Custom exceptions
│   │   └── main.py              # FastAPI app entry point
│   ├── tests/                   # 223 unit & integration tests
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── app/                 # Next.js pages & layout
│       │   ├── debate/[threadId]/  # Live SSE streaming page
│       │   ├── history/         # Searchable debate history
│       │   └── compare/         # Side-by-side decision comparison
│       ├── components/          # 11 React components
│       ├── lib/                 # API client & TypeScript types
│       └── types/               # Fallback type stubs
├── docs/
│   ├── backend/                 # 7 backend documentation files
│   ├── frontend/                # 6 frontend documentation files
│   └── plan/                    # Project planning docs
├── command.md                   # Detailed setup & run guide
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

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check — status, version, provider configured |
| `POST` | `/debate/start` | Start a debate (synchronous V1, returns `FinalDecision`) |
| `POST` | `/debate/start-async` | Start a debate in background (returns `thread_id` + `stream_url`) |
| `GET` | `/debate/{thread_id}/stream` | SSE stream of live debate events |
| `GET` | `/debate/{thread_id}` | Get debate status and round history |
| `POST` | `/debate/{thread_id}/resume` | Resume a debate from the last LangGraph checkpoint |
| `GET` | `/decision/{thread_id}` | Retrieve the final decision for a completed debate |
| `GET` | `/history` | Paginated list of completed debates (search, pagination) |

**Interactive docs:** http://localhost:8000/docs (Swagger UI)

### Example

```bash
curl -X POST http://localhost:8000/debate/start \
  -H "Content-Type: application/json" \
  -d '{"query": "Should our company expand into the Asian market in Q3?", "max_rounds": 3}'
```

---

## Configuration

All backend settings are configured via `backend/.env`:

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | **Yes** (if using GROQ) | — | Your GROQ API key |
| `LLM_PROVIDER` | No | `groq` | LLM provider: `groq`, `openai`, or `anthropic` |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Model name for the selected provider |
| `MAX_DEBATE_ROUNDS` | No | `4` | Maximum rounds per debate (2–8) |
| `CONSENSUS_THRESHOLD` | No | `0.75` | Agreement score to stop early |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | Allowed frontend origins |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./agentboard.db` | SQLite database path |
| `RATE_LIMIT_PER_MINUTE` | No | `10` | API rate limit per IP per minute |
| `OPENAI_API_KEY` | No | — | Required if `LLM_PROVIDER=openai` |
| `ANTHROPIC_API_KEY` | No | — | Required if `LLM_PROVIDER=anthropic` |

Frontend: `frontend/.env.local` contains `NEXT_PUBLIC_API_URL=http://localhost:8000`.

---

## Testing

```bash
cd backend
.\venv\Scripts\activate

# Run all 223 tests (fast, no API calls)
pytest -v --tb=short

# Run a specific test file
pytest tests/test_consensus.py -v

# Skip integration tests (that hit GROQ API)
pytest -m "not integration" -v
```

**Test coverage:**

| Area | File | Focus |
|---|---|---|
| Schemas | `test_schemas.py` | Pydantic model validation, bounds, defaults |
| Base Agent | `test_base_agent.py` | LLM calling, parsing, error handling |
| Agents | `test_agents.py` | Prompt construction, context-awareness |
| LLM Client | `test_llm_client.py` | Retry logic, rate limits, JSON parsing |
| Consensus | `test_consensus.py` | Agreement scoring, drift detection |
| Orchestrator | `test_orchestrator.py` | State machine, termination, graceful degradation |
| API | `test_api.py` | Endpoints, status codes, validation errors |

---

## Frontend Features

- **Live SSE Streaming** — Real-time debate progress via Server-Sent Events; agent outputs, critiques, and syntheses appear as they are produced
- **Debate Input** — Textarea with 10-char minimum validation + max-rounds slider (2–8)
- **Decision View** — Colour-coded confidence/agreement meters, risk flags, alternatives, dissenting opinions
- **Debate Trace** — Expandable vertical timeline showing every round's agent outputs and critiques
- **Debate History** — Searchable, paginated list of completed debates with agreement scores
- **Compare View** — Side-by-side comparison of two debate decisions with comparative highlighting
- **Dark Mode** — Toggle with flash-free initialisation and `localStorage` persistence
- **JSON Export** — Download the complete decision as a JSON file
- **Agent Colour Coding** — Each agent has a unique colour identity across all components

---

## Documentation

Detailed documentation is available in the `docs/` folder:

### Backend (`docs/backend/`)

| File | Topic |
|---|---|
| `01-architecture-overview.md` | Tech stack, directory structure, request lifecycle |
| `02-api-reference.md` | All endpoints, schemas, SSE events, curl examples, error codes |
| `03-agent-system.md` | All 5 agents, BaseAgent ABC, prompt construction |
| `04-debate-engine.md` | LangGraph debate graph, phases, checkpointing, termination |
| `05-consensus-and-llm-client.md` | Scoring formulas, multi-provider LLM client, semantic consensus |
| `06-configuration-and-logging.md` | Settings, env vars, CORS, rate limiting, structured logging |
| `07-testing-strategy.md` | 223 tests, fixtures, pytest config, test categories |

### Frontend (`docs/frontend/`)

| File | Topic |
|---|---|
| `01-architecture-overview.md` | Tech stack, directory structure, SSE streaming flow |
| `02-pages-and-routing.md` | Root layout, home, debate stream, history, compare pages |
| `03-component-library.md` | All 11 components — DebateStreamViewer, CompareContent, etc. |
| `04-api-integration-and-types.md` | API client, SSE connection, TypeScript interfaces |
| `05-styling-and-dark-mode.md` | Tailwind config, dark mode, colour system |
| `06-configuration-and-setup.md` | Next.js config, TypeScript, dependencies, build output |

See also: [command.md](command.md) for the complete step-by-step setup guide.

---

## License

This project is for educational and personal use.
