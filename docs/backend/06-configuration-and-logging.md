# Configuration & Logging

---

## Application Configuration

**File:** `app/core/config.py`

Configuration is managed via **pydantic-settings**: environment variables (and `backend/.env`) are loaded into a typed, validated `Settings` singleton. Names are case-sensitive.

### Settings Class

```python
class Settings(BaseSettings):
    # --- Environment ---
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_VERSION: str = "2.0.0"

    # --- LLM providers (only the active provider's key is required) ---
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    LLM_PROVIDER: Literal["groq", "openai", "anthropic", "gemini"] = "groq"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5.5"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-opus-4-8"
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"

    # --- Debate engine ---
    DEFAULT_DEBATE_MODE: Literal["quick", "standard", "thorough"] = "quick"
    MAX_DEBATE_ROUNDS: int = 2          # orchestrator-level fallbacks, aligned with
    CONSENSUS_THRESHOLD: float = 0.75   # the "standard" preset (API requests use
    MIN_DEBATE_ROUNDS: int = 2          # mode presets instead)
    AGENT_PROPOSAL_TIMEOUT: float = 45.0
    AGENT_CRITIQUE_TIMEOUT: float = 45.0
    AGENT_REVISION_TIMEOUT: float = 45.0
    AGENT_TOOL_TIMEOUT_MULTIPLIER: float = 1.5

    # --- Hybrid consensus gate tuning ---
    DRIFT_EARLY_STOP_THRESHOLD: float = 0.05
    MINORITY_REPORT_BAND: float = 0.20
    CONFIDENCE_CONVERGENCE_SPREAD: float = 0.15
    CONVERGENCE_ALLOW_ALL_CONFIDENT: bool = False
    ALL_CONFIDENT_THRESHOLD: float = 0.9
    MAX_DISSENTERS_FOR_CONSENSUS: int = 1
    MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS: int = 2
    CONSENSUS_POSITION_WEIGHT: float = 0.3
    POSITION_OVERLAP_FLOOR: float = 0.08
    POSITION_OVERLAP_CEILING: float = 0.19
    AGREEMENT_METHOD: Literal["stance", "lexical", "semantic"] = "stance"
    MAX_TOOL_CALLS_PER_ROUND: int = 3
    LLM_MAX_CONCURRENCY: int = 4

    # --- Application ---
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- Security ---
    ADMIN_API_TOKEN: str = ""
    RATE_LIMIT_PER_MINUTE: int = 30
    TRUSTED_PROXY_IPS: str = "127.0.0.1,::1"

    # --- Agents ---
    ENABLED_AGENTS: str = "Analyst,Risk,Strategy,Ethics,Moderator"

    # --- Persistence ---
    DATABASE_URL: str = "agentboard.db"
    CHECKPOINT_DATABASE_URL: str = "agentboard_checkpoints.db"
    DEBATE_TTL_DAYS: int = 90

    # --- LangSmith (optional) ---
    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "agentboard"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"

    # --- Semantic consensus (optional) ---
    SEMANTIC_CONSENSUS_ENABLED: bool = False
    SEMANTIC_MODEL: str = "all-MiniLM-L6-v2"
    SEMANTIC_CONSENSUS_WEIGHT: float = 0.5

    # --- Knowledge base ---
    KNOWLEDGE_BASE_DIR: str = "knowledge_base"
    KB_CHUNK_SIZE: int = 1000
    KB_CHUNK_OVERLAP: int = 200
    KB_SIMILARITY_THRESHOLD: float = 0.30
    KB_TOP_K: int = 5
    KB_EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    KB_MAX_FILE_MB: int = 10

    # --- Human-in-the-loop ---
    HITL_ENABLED: bool = True
```

### Validation built into Settings

- **Active provider key** — startup fails with `{PROVIDER}_API_KEY is required when LLM_PROVIDER={provider}` if the active provider's key is empty. Keys for other providers are optional (they can be supplied later through `/llm-settings`).
- **Data paths** — `DATABASE_URL`, `CHECKPOINT_DATABASE_URL`, `KNOWLEDGE_BASE_DIR` and `LOG_DIR` accept `sqlite:///…` URLs or plain paths; relative paths are resolved against `backend/`, so the server uses the same files whatever directory it's started from. `:memory:` is kept as is.
- **Enumerations** — `APP_ENV`, `LLM_PROVIDER` and `DEFAULT_DEBATE_MODE` reject unknown values at startup.
- **No secrets in errors** — `hide_input_in_errors=True`, so a validation error never prints input values (API keys).

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| **LLM providers** ||||
| `LLM_PROVIDER` | No | `groq` | Active provider: `groq`, `openai`, `anthropic`, `gemini` |
| `GROQ_API_KEY` | If provider is groq | `""` | GROQ key |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | If that provider is active | `""` | Provider keys; also used for per-agent overrides and runtime switching |
| `GROQ_MODEL` / `OPENAI_MODEL` / `ANTHROPIC_MODEL` / `GEMINI_MODEL` | No | see above | Model per provider |
| `GROQ_BASE_URL` | No | `https://api.groq.com/openai/v1` | GROQ API base URL |
| **Debate engine** ||||
| `DEFAULT_DEBATE_MODE` | No | `quick` | Mode used when a debate or simulation doesn't choose one, and the mode the UI pre-selects (`quick`, `standard`, `thorough`). Served at `GET /debate-modes` |
| `MAX_DEBATE_ROUNDS` / `MIN_DEBATE_ROUNDS` / `CONSENSUS_THRESHOLD` | No | `2` / `2` / `0.75` | Fallbacks when the graph runs without a mode preset |
| `AGENT_PROPOSAL_TIMEOUT` / `AGENT_CRITIQUE_TIMEOUT` / `AGENT_REVISION_TIMEOUT` | No | `45` | Per-phase agent timeout (s) |
| `AGENT_TOOL_TIMEOUT_MULTIPLIER` | No | `1.5` | Extra time for tool-using agents |
| `MAX_TOOL_CALLS_PER_ROUND` | No | `3` | Tool calls per agent call |
| `LLM_MAX_CONCURRENCY` | No | `4` | LLM calls in flight per provider (`0` = no cap) |
| `ENABLED_AGENTS` | No | `Analyst,Risk,Strategy,Ethics,Moderator` | Core agents enabled at runtime |
| **Consensus gate tuning** ||||
| `AGREEMENT_METHOD` | No | `stance` | How Rule 1 measures agreement: `stance` (confidence-weighted stance vote), `lexical` (confidence + word overlap; also the fallback), `semantic` (confidence + embedding cosine; needs `SEMANTIC_CONSENSUS_ENABLED`). A debate can override it with `agreement_method`. Served at `GET /debate-modes` |
| `CONSENSUS_POSITION_WEIGHT` | No | `0.3` | `lexical` method: weight of position overlap vs mean confidence |
| `POSITION_OVERLAP_FLOOR` / `POSITION_OVERLAP_CEILING` | No | `0.08` / `0.19` | Raw word overlap mapped to 0 (unrelated positions) … 1 (same stance reworded) |
| `DRIFT_EARLY_STOP_THRESHOLD` | No | `0.05` | Drift below this = agents stopped moving |
| `MINORITY_REPORT_BAND` | No | `0.20` | Fallback dissent rule when fewer than two agents voted (older debates): confidence gap below the mean that marks a dissenter. Otherwise a dissenter is an agent voting against the majority stance |
| `CONFIDENCE_CONVERGENCE_SPREAD` | No | `0.15` | Max confidence spread counted as converged |
| `CONVERGENCE_ALLOW_ALL_CONFIDENT` | No | `false` | Also count "every agent ≥ `ALL_CONFIDENT_THRESHOLD`" as converged. Off: redundant with the spread check at the defaults |
| `ALL_CONFIDENT_THRESHOLD` | No | `0.9` | "Everyone is confident" cut-off, only used with the flag above |
| `MAX_DISSENTERS_FOR_CONSENSUS` | No | `1` | Most agents voting against the majority stance at consensus |
| `MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS` | No | `2` | Most high/critical critiques still open after revision at consensus |
| **Semantic consensus** ||||
| `SEMANTIC_CONSENSUS_ENABLED` | No | `false` | Compute, log and emit embedding similarity every round (diagnostic) and allow the `semantic` agreement method. Doesn't change the score unless that method is chosen |
| `SEMANTIC_MODEL` | No | `all-MiniLM-L6-v2` | sentence-transformer model (reads the first 256 word-pieces of each position) |
| `SEMANTIC_CONSENSUS_WEIGHT` | No | `0.5` | `semantic` method: cosine vs confidence weight |
| **Application** ||||
| `APP_ENV` | No | `development` | `development`, `staging`, `production` (production refuses admin actions without a token) |
| `LOG_LEVEL` | No | `INFO` | Root log level |
| `LOG_DIR` | No | `logs` | Log directory (relative to `backend/`) |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | Origins allowed to call the API directly |
| **Security** ||||
| `ADMIN_API_TOKEN` | Recommended in production | `""` | Token (`X-Admin-Token`) for switching the provider, clearing agent memory, deleting KB documents. Empty: open in development, refused in production |
| `RATE_LIMIT_PER_MINUTE` | No | `30` | Per-client limit on debate/simulation starts |
| `TRUSTED_PROXY_IPS` | No | `127.0.0.1,::1` | IPs/CIDRs whose `X-Forwarded-For` is trusted (the Next.js server; Docker Compose adds `172.16.0.0/12`) |
| **Persistence** ||||
| `DATABASE_URL` | No | `agentboard.db` | Application SQLite database |
| `CHECKPOINT_DATABASE_URL` | No | `agentboard_checkpoints.db` | LangGraph checkpoint database |
| `DEBATE_TTL_DAYS` | No | `90` | Debates older than this are deleted at startup |
| **LangSmith** ||||
| `LANGSMITH_TRACING` | No | `false` | Enable tracing |
| `LANGSMITH_API_KEY` | If tracing | `""` | LangSmith key |
| `LANGSMITH_PROJECT` / `LANGSMITH_ENDPOINT` | No | `agentboard` / `https://api.smith.langchain.com` | Project and endpoint |
| **Knowledge base** ||||
| `KNOWLEDGE_BASE_DIR` | No | `knowledge_base` | ChromaDB directory (relative to `backend/`) |
| `KB_EMBEDDING_MODEL` | No | `all-MiniLM-L6-v2` | Embedding model |
| `KB_CHUNK_SIZE` / `KB_CHUNK_OVERLAP` | No | `1000` / `200` | Chunking (characters) |
| `KB_SIMILARITY_THRESHOLD` | No | `0.30` | Minimum similarity for a hit |
| `KB_TOP_K` | No | `5` | Chunks per query |
| `KB_MAX_FILE_MB` | No | `10` | Max upload size |
| **Human-in-the-loop** ||||
| `HITL_ENABLED` | No | `true` | Allow supervised debates |

### .env File

The backend reads `backend/.env` (git-ignored). **`backend/.env.example` is the complete, commented template** — every setting with its default, grouped as above. Copy it and fill in the key of the provider you use:

```dotenv
LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
DEFAULT_DEBATE_MODE=quick
ADMIN_API_TOKEN=            # set one for any shared or production deployment
```

Keep comments on their own lines in `.env` — `run_all.bat` copies raw lines into environment variables, so an inline `# comment` would become part of the value.

### Singleton Access

```python
from app.core.config import settings

settings.LLM_PROVIDER
settings.DEFAULT_DEBATE_MODE
```

`settings` is created once at import time; the API layer also injects it with `Depends(get_settings)`.

---

## CORS Configuration

`app/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "Last-Event-ID", "X-Admin-Token"],
)
```

The browser normally reaches the API through the Next.js `/backend/*` proxy (same origin), so CORS only matters for direct calls. Add other origins to `CORS_ORIGINS` if needed.

---

## Structured Logging

**File:** `app/core/logging_config.py`

### JSON Formatter

```json
{
  "timestamp": "2026-02-28T12:00:00.000000+00:00",
  "level": "INFO",
  "logger": "agentboard.nodes",
  "message": "round_started",
  "module": "nodes",
  "function": "proposals_node",
  "line": 91,
  "request_id": "…"
}
```

Extra fields passed via `extra={...}` are included; the request id comes from `app/core/request_context.py`.

### Logger Hierarchy

```
agentboard                      # Root logger
  ├── agentboard.api            # API routes
  ├── agentboard.analytics
  ├── agentboard.audit          # Audit events
  ├── agentboard.orchestrator   # DebateGraph
  ├── agentboard.nodes          # Graph nodes
  ├── agentboard.agents.*       # Per agent
  ├── agentboard.db.*           # Persistence
  └── agentboard.services.*     # LLM client, consensus, KB, simulation
```

### Notable Log Events

| Logger | Event | Extra Fields |
|---|---|---|
| `agentboard` | `http_request_completed` | `request_id`, `method`, `path`, `status_code`, `duration_ms`, `client_ip` (real client, proxy-aware) |
| `agentboard` | `checkpoints_pruned` | `threads` |
| `agentboard.audit` | `audit_event` | `request_id`, `action`, `outcome`, `thread_id`, action-specific fields |
| `agentboard.api` | `api_debate_start` / `api_debate_complete` | `thread_id`, `termination_reason` |
| `agentboard.orchestrator` | `debate_total_timing` | `thread_id`, `total_rounds`, `termination_reason`, `total_elapsed_ms` |
| `agentboard.nodes` | `round_started`, `phase_timing` | `round`, `phase`, `elapsed_ms`, counts |
| `agentboard.nodes` | `round_finished` | `round`, `agreement_score`, `moderator_recommends_continue` |
| `agentboard.nodes` | `convergence_gate` | `round`, `min_rounds`, `agreement_score`, `agreement_method_used`, `stance_agreement_score`, `stance_tally`, `threshold`, `dissenting_agents` (names), `open_disagreements` (`[{critic, target, severity, status}]`), `confidence_converged`, `drift`, `active_vetoes`, `consensus`, `should_continue` |
| `agentboard.nodes` | `moderator_synthesis_failed` | `round`, `error` (placeholder synthesis used) |
| `agentboard.agents.*` | `llm_call_start` | `agent`, `round`, `action`, `prompt_chars`, `provider`, `model` |
| `agentboard.agents.*` | `llm_call_done` / `llm_call_failed` | `agent`, `round`, `action`, `elapsed_ms` |
| `agentboard.agents.*` | `synthesis_complete` (moderator) | `round`, `moderator_agreement_estimate`, `moderator_recommends_continue` |
| `agentboard.agents.*` | `moderator_rate_limited_retrying` | `schema`, `delay_s` |
| `agentboard.agents.*` | `tool_called` / `tool_cap_reached` | `agent`, `tool`, `output_snippet` |
| `agentboard.services.llm_client` | `LangChainProvider initialized` / `llm_client_switched` | `provider`, `model` |

### Noise Suppression

`uvicorn.access` and `httpx` are set to `WARNING`.

### Setup and File Logging

The lifespan calls `setup_logging(settings.LOG_LEVEL, settings.LOG_DIR)`. Calling it again closes and replaces the previous handlers.

- **File:** `LOG_DIR/agentboard.log` (default `backend/logs/`)
- **Rotation:** at midnight; rotated files are named `agentboard.log.YYYY-MM-DD`
- **Retention:** 30 rotated files

Tests point `LOG_DIR` at a temporary directory, so they never write to `backend/logs`.

### Request Correlation

`RequestIDMiddleware` binds every request to a correlation id: an incoming `X-Request-ID` is echoed back, otherwise a UUID4 is generated and returned. The id appears in API and audit logs.

### Metrics Endpoint

`GET /metrics` returns start time and uptime, request count and average latency, responses by status, per-route counters, and business-event counters (debate starts, approvals, evaluations, knowledge mutations). See the API reference for the shape.

---

## Rate Limiting

**File:** `app/core/rate_limiter.py`

```python
limiter = Limiter(key_func=client_ip)
```

`client_ip(request)` returns the real client address: when the direct peer is in `TRUSTED_PROXY_IPS` (IPs or CIDR ranges), the right-most `X-Forwarded-For` hop is used — the one the nearest proxy added (earlier entries can be written by the client); otherwise, or if that hop isn't a valid IP, the peer address. A client can't spoof its address by sending its own `X-Forwarded-For`, and users behind the Next.js proxy don't share one quota. The same function feeds request and audit logs.

- `SlowAPIMiddleware` enforces limits; exceeding one returns **429**.
- `POST /debate/start`, `/debate/start-async`: `RATE_LIMIT_PER_MINUTE`/minute (default 30).
- `POST /debate/simulate`, `/debate/simulate-async`: the per-minute limit **and** 2/hour.
- `POST /knowledge/upload`: 10/minute.

---

## Admin Authentication

**File:** `app/core/security.py`

`require_admin` is a FastAPI dependency on `POST /llm-settings`, `DELETE /memory/{agent}` and `DELETE /knowledge/documents/{doc}`:

- `ADMIN_API_TOKEN` set → the request needs a matching `X-Admin-Token` (constant-time compare), else **401** `admin_token_required`.
- Not set → allowed in development; **403** `admin_disabled` in production.

`admin_token_required()` tells the frontend (via `GET /llm-settings`) whether to ask for the token.

---

## Application Lifespan

**File:** `app/main.py`

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.LOG_LEVEL, settings.LOG_DIR)
    app_metrics.reset()
    if settings.LANGSMITH_TRACING and settings.LANGSMITH_API_KEY:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")   # + API key, project, endpoint
    run_migrations()                                  # Alembic upgrade head + WAL mode
    await cleanup_old_debates(db, settings.DEBATE_TTL_DAYS)
    await prune_finished_checkpoints(...)             # drop checkpoints of decided/unknown debates, VACUUM
    kb = KnowledgeBase(...); set_knowledge_base(kb)
    app.state.kb_warm_task = asyncio.create_task(kb.warm())   # embedding model loads in the background
    set_memory_store(AgentMemoryStore(database_url=settings.DATABASE_URL))
    # register the 5 core agents (with tool allow-lists) and 4 domain agents (disabled)
    yield
    # shutdown: log
```

Because the knowledge base warms up in the background, `/health` answers immediately on a fresh start; the KB reports itself unavailable (upload → 501) until it is ready, and retries initialisation after a failure.

### Middleware Stack

Order a request passes through (the last `add_middleware` call is outermost):

1. `CORSMiddleware`
2. `RequestIDMiddleware` — `X-Request-ID`, request log with client IP
3. `UploadSizeLimitMiddleware` — rejects `POST /knowledge/upload` with a `Content-Length` over `KB_MAX_FILE_MB` (413) before the body is parsed
4. `SlowAPIMiddleware` — rate limits
5. Routers (`routes.py`, `analytics.py`) and exception handlers
