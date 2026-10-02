# Testing Strategy

The backend has about **520 tests in 48 modules**, covering schemas, agents, the LangGraph engine, consensus, the LLM client, persistence, the HTTP API, SSE and security. Every LLM call is mocked (or replaced by a fake LLM driving the **real** LangGraph engine), so the suite needs no API keys and finishes in about 15 seconds.

CI runs it on every push and pull request to `main` (`.github/workflows/docker-publish.yml`, job `test-backend`): `pip install -r requirements-dev.lock` on Python 3.11, then `ruff check .`, `mypy app` and `pytest -q`. The Docker images are only built when this job (and the frontend job) pass.

---

## Isolation — tests never touch your data

`tests/conftest.py` makes every test hermetic:

| Fixture | Scope | What it does |
|---|---|---|
| `_migrated_db_template` | session | Runs the Alembic migrations once into a template database |
| `_isolated_storage` | autouse | Copies that template into the test's `tmp_path` and points `DATABASE_URL`, `CHECKPOINT_DATABASE_URL`, `KNOWLEDGE_BASE_DIR` and `LOG_DIR` there; afterwards closes any log file handlers opened inside it |
| `mock_llm_client` | function | `LangChainProvider` with `ainvoke_structured` returning valid models |
| `sample_agent_response` | function | An Analyst `AgentResponse` |
| `sample_debate_state` | function | A `DebateState` with one round of 4 agent outputs |

A dummy `GROQ_API_KEY` is set so `Settings` validate. `test_test_isolation.py` guards the harness itself: the suite can never write to `backend/agentboard.db`, the checkpoint database or `backend/logs`.

---

## Test Modules

### Core models and agents

| Module | Covers |
|---|---|
| `test_schemas.py` | Pydantic models: bounds, defaults, UUIDs, round-trips; the default mode (Quick) and explicit modes |
| `test_contracts.py` | Every endpoint's response matches its schema; SSE payload shapes |
| `test_base_agent.py` | `BaseAgent` structured calls, KB / memory / tool hooks, errors |
| `test_agents.py` | The specialised agents' prompts for all three phases |
| `test_registry_extended.py` | Registry: overrides, per-agent temperature/retries, tool validation |
| `test_provider_keys.py` | One provider→key map for the global client and per-agent overrides (incl. Gemini) |
| `test_agent_selection.py` | At least two debating agents besides the Moderator (models + HTTP 422) |
| `test_calculator_tool.py` | Calculator: arithmetic and math functions only, no access to Python names (skipped where `numexpr` can't import) |
| `test_ethics_veto.py` | Structured veto: schema, gate blocking, decision and exports, checkpoint round-trip |
| `test_moderator_signals.py` | The gate, not the moderator, decides; moderator calls use `_call_structured` |

### Engine and consensus

| Module | Covers |
|---|---|
| `test_orchestrator.py` | LangGraph nodes, routing, termination, contribution scores, the gate with real settings |
| `test_consensus.py` | Agreement, weighted overlap, normalisation, drift, dissent and open-disagreement counts |
| `test_hitl.py` | `hitl` node: approve / override / add_round, status transitions |
| `test_hitl_override.py` | Override feedback reaches the finalize prompt and the decision |
| `test_hitl_async_approve.py` | End-to-end HITL over HTTP with the real graph: 202 approvals, duplicate 409, re-pause, failures |
| `test_round_limit.py` | `add_round` can't push a debate past the 8-round schema limit |
| `test_rate_limits.py` | 429 classification, per-provider slot (re-entrant, never times an agent out), moderator back-off, synthesis fallback |
| `test_usage_and_memory.py` | Token usage across HITL/resume segments; memory saves not garbage-collected; live LLM client |

### API, streaming and background work

| Module | Covers |
|---|---|
| `test_api.py` | Routes: start, async start, status, decision, resume, cancel, history, health, agents, templates, KB, memory, error mapping |
| `test_background_jobs.py` | Resume-async, cancelling paused debates, simulation jobs (start, poll, cancel) |
| `test_sse_ping.py` | Named `ping` keep-alive, Last-Event-ID resume, stream ends after terminal events |
| `test_sse_cleanup.py` | Replay buffers / queues / locks released when a debate ends |
| `test_error_messages.py` | User-facing errors don't leak provider or internal details |
| `test_default_mode.py` | `DEFAULT_DEBATE_MODE`: Quick when unset, read from the environment, invalid values rejected, `GET /debate-modes` |
| `test_provider_config.py` | Only the active provider's key is required; `/health` `llm` block; no secrets in settings errors |
| `test_admin_security.py` | `X-Admin-Token` on admin endpoints; open in development, refused in production without a token |
| `test_client_ip.py` | Per-client rate limits through trusted proxies only; spoofed `X-Forwarded-For` ignored |
| `test_upload_limits.py` | Oversized uploads refused from Content-Length or while streaming; never read whole into memory |
| `test_blocking_work.py` | KB start-up and PDF rendering run off the event loop; startup isn't blocked by the embedding model |

### Persistence, analytics and services

| Module | Covers |
|---|---|
| `test_db_cleanup.py` | TTL cleanup, evaluation cache, state upserts |
| `test_crud_details.py` | Re-saves keep `created_at`; agent-memory index used for case-insensitive lookups |
| `test_history_items.py` | History rows: rounds actually run, real termination reasons, fallbacks to the stored decision |
| `test_history_query.py` | Server-side sort / filter / search before paging; literal `%` and `_` |
| `test_analytics.py` | Analytics endpoints and caching |
| `test_analytics_accuracy.py` | Consensus-only round averages, older rows' reasons, symmetric position-based matrix, Custom mode, template stats, cache invalidation |
| `test_sqlite_concurrency.py` | WAL mode; the event writer survives transient "database is locked" |
| `test_resource_hygiene.py` | Bounded stores, checkpoint deletion and startup pruning, concurrent debates on a fresh checkpoint DB |
| `test_migrations_logging.py` | Startup migrations don't disturb app logging; log rotation naming |
| `test_config_paths.py` | Data paths resolved against `backend/`; sqlite URL forms |
| `test_config_consistency.py` | No unused settings; code defaults mirror Settings |
| `test_retriever.py` | KB chunking, ids, retrieval, LRU cache, unavailable-KB behaviour |
| `test_agent_memory.py` | Memory store; case-insensitive names |
| `test_evaluation_service.py` | LLM-as-judge scores and failure handling |
| `test_simulation_service.py` | `run_simulation`: aggregation, failed runs skipped, ratings |
| `test_simulation_metrics.py` | Calibrated consistency score; recurring risks matched in any wording |
| `test_observability.py` | Request ids, JSON logs, `/metrics`, audit events |
| `test_test_isolation.py` | The isolation guarantees above |

---

## How bug fixes are tested

Each fix comes with tests that **fail on the old code** — verified by temporarily reverting the fix and re-running them. Where a mock could hide the bug (HITL resume, checkpoints, concurrency), the test drives the real LangGraph engine with a fake LLM instead of mocking the graph.

---

## Running Tests

```bash
cd backend
# activate the venv created from requirements-dev.lock (Python 3.11)

pytest -q                               # whole suite
pytest tests/test_consensus.py -v       # one module
pytest -k "veto" -v                     # by keyword
ruff check .                            # lint (as in CI)
mypy app                                # type check (as in CI)
```

The `integration` marker is defined for tests that would call a real provider; none are in the suite today, so `pytest` never needs a network connection or API key.

---

## Pytest Configuration

**File:** `pyproject.toml`

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
markers = [
    "integration: marks tests that call the real GROQ API (deselect with -m 'not integration')",
    "unit: marks tests that use mocked LLM clients only (default; no network)",
]
filterwarnings = [
    "ignore::DeprecationWarning",
    "ignore::PendingDeprecationWarning",
    "ignore::pytest.PytestUnhandledThreadExceptionWarning",
    "ignore::pytest.PytestUnraisableExceptionWarning",
]
```

Coverage settings (`[tool.coverage.*]`) measure `app/` with `fail_under = 60`. Ruff and mypy are configured in the same file (mypy: Python 3.11, `check_untyped_defs`, tests and Alembic excluded).

---

## Test Philosophy

1. **No real LLM calls** — mocked clients or a fake LLM behind the real engine.
2. **Hermetic storage** — temporary databases, checkpoint DB, KB and logs per test.
3. **Regression tests prove the bug** — each fails without its fix.
4. **Contracts are tested** — every schema and SSE payload.
5. **Failure paths are first-class** — timeouts, rate limits, lost connections, locked databases, partial agent failures.
