# Debate Engine & Orchestration

The debate lifecycle is orchestrated by a **LangGraph `StateGraph`** defined in `app/orchestrator/debate_graph.py`. All API traffic flows through `DebateGraph`.

---

## LangGraph Workflow

### Graph Overview

```
  START
    │
    ▼
  proposals ──(skip_critique_phase)──────────────┐
    │                                            │
    ▼                                            ▼
  critiques ──► revisions ──────────────────► convergence
    ▲                                            │
    │   should_continue = True                   │
    └─────────────────────────────────────────────┤
                                                  │ should_continue = False
                          ┌───────────────────────┴───────────────┐
                          │ hitl_mode                              │ (not supervised)
                          ▼                                        │
                        hitl ──(add_round → proposals)             │
                          │ (approve / override)                   │
                          ▼                                        ▼
                                             finalize
                                                 │
                                                 ▼
                                               END
```

When `skip_critique_phase` is true (the `quick` preset), `proposals` routes directly to `convergence`, skipping `critiques` and `revisions`. When `hitl_mode` is true, a stop decision at `convergence` routes through the dedicated `hitl` node (which calls LangGraph `interrupt()`) before `finalize`.

### Debate Modes

Presets live in `_MODE_PRESETS` (`app/schemas/api_models.py`):

| Mode | Max Rounds | Min Rounds | Consensus Threshold | Skip Critiques | Use Case |
|---|---|---|---|---|---|
| `quick` | 2 | 1 | 0.60 | Yes | Fast, low-stakes decisions and testing |
| `standard` | 2 | 2 | 0.75 | No | Full critique for most real decisions |
| `thorough` | 6 | 3 | 0.85 | No | High-stakes, comprehensive analysis |
| `custom` | — | 2 | — | No | Standard's settings with the caller's own rounds/threshold (UI: 2–6 rounds, default 4 rounds and 0.75) |

**Default mode.** A request that doesn't name a mode uses `DEFAULT_DEBATE_MODE` (`app/core/config.py`) — **`quick`** unless configured (`quick`, `standard` or `thorough`). `default_debate_mode()` reads it at request time; `GET /debate-modes` exposes it so the home and Simulate pages pre-select it.

`resolve_debate_config()` merges the preset with explicit overrides (explicit `max_rounds`, `min_rounds`, `consensus_threshold`, `skip_critique_phase` always win) and clamps `min_rounds ≤ max_rounds`. The resolved mode is stored on `DebateState.mode` so analytics can group by it.

> `_MODE_PRESETS` is the single source of API-resolved defaults. `Settings.MAX_DEBATE_ROUNDS` / `MIN_DEBATE_ROUNDS` / `CONSENSUS_THRESHOLD` are separate fallbacks used only when `DebateGraph` is driven directly without `resolve_debate_config` (aligned with the `standard` preset).

The graph state type is `DebateGraphState` (`app/orchestrator/lg_state.py`):

```python
class DebateGraphState(TypedDict):
    debate_state: DebateState                  # Pydantic model – single source of truth
    should_continue: bool                      # Routing flag set by convergence/hitl node
    final_decision: FinalDecision | None       # Populated by finalize node
    skip_critique_phase: bool                  # Quick mode: skip critiques+revisions
    consensus_threshold: float | None          # Per-run threshold override (None = Settings)
    hitl_mode: bool                            # Route through hitl node before finalize
    awaiting_approval: bool                    # True while paused for human approval
    hitl_interrupt_payload: dict | None        # Built by convergence, consumed by hitl
```

### DebateGraph Public API

| Method | Returns | Description |
|---|---|---|
| `run(query, max_rounds?, *, min_rounds?, initial_state?, consensus_threshold?, skip_critique_phase?, hitl_mode?)` | `(DebateState, FinalDecision \| None)` | Run the debate. The decision is `None` when a supervised debate pauses for approval (state status `awaiting_approval`) |
| `resume(thread_id, prior_usage=None)` | `(DebateState, FinalDecision \| None)` | Continue from the checkpoint (`ValueError` if none). `prior_usage` is the token usage already spent, so totals add up |
| `approve(thread_id, action="approve", feedback="", prior_usage=None)` | `(DebateState, FinalDecision \| None)` | Answer a HITL pause; may pause again after `add_round` |
| `delete_checkpoints(thread_id)` | — | Drop a debate's checkpoints once its decision is stored |
| `has_checkpoint(thread_id)` | `bool` | Whether the debate can still be resumed |

Module-level helpers: `require_decision(decision)` raises a clear `RuntimeError` when a caller that needs a decision gets `None`; `prune_finished_checkpoints(checkpoint_url, database_url)` runs at startup.

Every segment is wrapped in LangChain's `get_usage_metadata_callback()`. Usage is merged into `DebateState.token_usage_by_model` across segments (start → HITL pause → approve → resume …), so the final `token_usage` and `estimated_cost_usd` cover the whole debate.

### Constructor Parameters

```python
class DebateGraph:
    def __init__(
        self,
        llm_client: LangChainProvider,
        settings: Settings,
        queue_list: list | None = None,          # SSE subscriber queues
        replay_buffer: list | None = None,       # SSE replay for late joiners
        persist_queue: asyncio.Queue | None = None,  # Ordered event-writer queue (id assignment)
        on_state_change: Callable | None = None,  # State persistence callback
        knowledge_base=None,                      # KnowledgeBase (RAG) instance
        memory_store=None,                        # AgentMemoryStore instance
        selected_agents: list[str] | None = None, # Per-debate agent subset / domain pack
    )
```

`_configure_participants()` resolves the active agents: `selected_agents` minus `Moderator`, else the registry's enabled agents. Shared services (knowledge base, memory store, SSE `emit_callback`) are attached to every agent and the moderator.

### Node Functions

All nodes live in `app/orchestrator/nodes.py`. Each is a **factory function** that captures dependencies and returns an async callable.

| Factory | Node | What it does |
|---|---|---|
| `make_proposals_node` | `proposals` | Starts a round; all agents' `run()` in parallel |
| `make_critiques_node` | `critiques` | Every agent critiques every other agent's proposal, in parallel |
| `make_revisions_node` | `revisions` | Each agent revises using the critiques aimed at it; replaces its proposal |
| `make_convergence_node` | `convergence` | Moderator summary, measured agreement, hybrid gate, HITL payload |
| `make_hitl_node` | `hitl` | Calls `interrupt()` once; on resume applies approve / override / add_round |
| `make_finalize_node` | `finalize` | Moderator decision + minority report, disagreements, contribution scores, vetoes |

Each node receives the `DebateGraphState` and returns a **partial update** that LangGraph merges back.

### Conditional Edges — Routing

```python
# proposals → critiques, or skip straight to convergence in quick mode
workflow.add_conditional_edges(
    "proposals",
    lambda s: "convergence" if s.get("skip_critique_phase") else "critiques",
    {"critiques": "critiques", "convergence": "convergence"},
)

# convergence → loop back | HITL pause | finalize
workflow.add_conditional_edges(
    "convergence",
    lambda s: "proposals" if s["should_continue"] else ("hitl" if s.get("hitl_mode") else "finalize"),
    {"proposals": "proposals", "hitl": "hitl", "finalize": "finalize"},
)

# hitl → add a round (loop) or finalize
workflow.add_conditional_edges(
    "hitl",
    lambda s: "proposals" if s["should_continue"] else "finalize",
    {"proposals": "proposals", "finalize": "finalize"},
)
```

`should_continue` becomes `False` when the hybrid consensus gate passes or the round cap is reached (see **Termination Logic**).

### Checkpointing & Resume

`DebateGraph` uses LangGraph's `AsyncSqliteSaver`, opened by `_open_checkpointer()`:

- **Serializer allow-list** — a `JsonPlusSerializer` with an explicit allow-list of the app's checkpointed models (`DebateState`, `DebateRound`, `AgentResponse`, `CritiqueResponse`, `FinalDecision`, `MinorityReportEntry`, `StructuredDisagreement`, `AgentStance`, `VetoEntry`), so newer LangGraph versions that block unregistered types can still load checkpoints.
- **Schema created once** — `_ensure_checkpoint_schema()` creates the checkpoint tables once per database path under a process-wide lock, so concurrent debates on a fresh database don't fail with "database is locked".
- **Thread isolation** — each debate uses `{"configurable": {"thread_id": state.thread_id}}`.
- **Resume** — `resume(thread_id)` continues from the last completed node (server restart, failure). `POST /debate/{id}/resume-async` does this in the background.
- **Cleanup** — after a decision is stored, the debate's checkpoints are deleted; if storing failed they are kept so it can still be resumed. At startup `prune_finished_checkpoints()` removes checkpoints of decided or unknown debates and VACUUMs the file. Simulation runs delete theirs after each run.
- **Checkpoint DB** — `CHECKPOINT_DATABASE_URL` (default `agentboard_checkpoints.db`, resolved relative to `backend/`), separate from the application database.

---

## Phase Details

### Phase 1 — Proposals (`proposals` node)

- Increments `current_round`, appends a fresh `DebateRound`; emits `round_started` and `phase_started`.
- All agents call `run()` **in parallel**. Each call first takes the provider's concurrency slot, then runs under `AGENT_PROPOSAL_TIMEOUT` (45 s; 1.5× for tool users).
- Failed or timed-out agents are skipped (`agent_timeout` event); the debate continues.
- `agent_output` per proposal (including `veto` / `veto_reason`); tool calls are recorded on the round.
- State is persisted via `on_state_change`.

### Phase 2 — Cross-Examination (`critiques` node)

- Every agent critiques every **other** agent's proposal — with 4 agents, up to **12 critiques** (4 × 3).
- Parallel, each under `AGENT_CRITIQUE_TIMEOUT`; `critique_completed` per critique.

### Phase 3 — Revisions (`revisions` node)

- Critiques are grouped by `target_agent`; each agent revises using only those aimed at it.
- Revised outputs **replace** the originals in `agent_outputs`; `agent_output` per revision.

### Phase 4 — Convergence (`convergence` node)

- The **Moderator** summarises the round (`ModeratorSynthesis`). If that call fails but the round has agent output, a placeholder summary is used and the debate continues.
- The Moderator's one-sentence `leading_proposal` is stored on the round (`DebateRound.leading_proposal`). Next round's proposal and revision prompts end with "Proposal on the table: …" so every agent sets its `stance` toward it; round 1 (or a missing proposal) anchors on the question itself.
- Every candidate agreement score is computed:
  - `confidence_agreement` = mean self-confidence (`compute_agreement_score`)
  - `position_agreement` = confidence-weighted word overlap of positions (`compute_confidence_weighted_score`), **rescaled** with `normalize_position_overlap(raw, POSITION_OVERLAP_FLOOR=0.08, POSITION_OVERLAP_CEILING=0.19)` — raw overlap between agents with different roles is low even when they agree, so 0.08 (unrelated positions) maps to 0 and 0.19 (the same stance reworded) to 1
  - `lexical_agreement = (1 − w)·confidence_agreement + w·position_agreement`, `w = CONSENSUS_POSITION_WEIGHT` (0.3)
  - `stance_agreement` = confidence-weighted vote share of the largest stance group (`compute_stance_agreement`); `None` with fewer than two non-abstaining voters
  - `semantic_agreement` = mean pairwise embedding cosine, only with `SEMANTIC_CONSENSUS_ENABLED`; encoded via `asyncio.to_thread`, `None` on failure
- The **agreement score** comes from `resolve_agreement_method(ds.agreement_method, AGREEMENT_METHOD)`: `stance` → `stance_agreement`; `semantic` → `(1 − sw)·confidence_agreement + sw·semantic_agreement` (`sw = SEMANTIC_CONSENSUS_WEIGHT`); `lexical` → `lexical_agreement`. If the chosen score is `None`, the lexical blend is used and `agreement_fallback_to_lexical` is logged. The method actually used is stored as `DebateRound.agreement_method_used`.
- `confidence_scores` is rebuilt from the **current round only**, so agents that dropped out don't leave stale values.
- The hybrid gate runs (below); `should_continue` is written to graph state.
- With `hitl_mode` and a stop decision, the `hitl_interrupt_payload` is built here.
- Emits `synthesis` with the chosen `agreement_score`, `agreement_method_used`, every component (`confidence_agreement_score`, `position_agreement_score`, `semantic_agreement_score`, `stance_agreement_score`, `stance_tally`), `leading_proposal`, the summary and agreement/disagreement areas. The moderator's own `should_continue` recommendation is only logged (`moderator_recommends_continue`) — the gate decides.

---

## Termination Logic — Hybrid Consensus Gate

A debate is **converged only when every signal holds** (`is_consensus_reached` in `consensus.py`):

| Signal | Source | Passes when |
|---|---|---|
| `active_vetoes` | Ethics-class outputs with `veto=true` this round | `== 0` |
| `position_agreement` | agreement score from the chosen method (above) | `≥ effective_threshold` (per-run override or `CONSENSUS_THRESHOLD`) |
| `rounds_completed` | `current_round` | `≥ min(min_rounds, max_rounds)` — one round can't end a multi-round debate |
| `dissenting_agents` | `select_dissenting_agents()` — voting agents whose stance differs from the majority stance (largest summed confidence; abstainers never dissent). Fewer than two voters: confidence > `MINORITY_REPORT_BAND` below the mean | `≤ MAX_DISSENTERS_FOR_CONSENSUS` (1) |
| `open_disagreements` | `select_open_disagreements(critiques, build_reply_index(outputs))` — distinct critic→target pairs of high/critical critiques the target's revision left `unaddressed` (or didn't answer), plus `critical` ones only `rebutted` | `≤ MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS` (2) |
| `confidence_converged` | drift / spread | drift < `DRIFT_EARLY_STOP_THRESHOLD` (only measured over agents present in both rounds; `None` = not measurable, never "converged") **or** spread ≤ `CONFIDENCE_CONVERGENCE_SPREAD`. The "every agent ≥ `ALL_CONFIDENT_THRESHOLD`" branch only applies with `CONVERGENCE_ALLOW_ALL_CONFIDENT` (off by default) |

Resulting `termination_reason`:

| Outcome | `termination_reason` | `status` |
|---|---|---|
| All signals hold | `"consensus_reached"` | `converged` |
| `current_round ≥ max_rounds`, gate not satisfied (incl. a standing veto) | `"max_rounds_reached"` | `max_rounds_reached` |
| Human chose `override` in HITL | `"human_override"` | `converged` |

`finalize_node` reuses `select_dissenting_agents()` and `build_reply_index()`, so the live gate and the final report agree on who dissented and which critiques were addressed. The `synthesis` event and the `convergence_gate` log carry `dissenting_agents` (names) and `open_disagreements` (`[{critic, target, severity, status}]`). Rule-by-rule write-up: [`docs/consensus_engine.md`](../consensus_engine.md).

---

## Human-in-the-Loop (HITL)

With `supervised=true` (and `HITL_ENABLED`), the graph routes through the **`hitl` node** when convergence decides to stop. Keeping `interrupt()` out of `convergence_node` means the moderator's synthesis never re-runs on resume.

### Flow

1. The debate runs normally.
2. At convergence, with `should_continue=False` and `hitl_mode`, the node builds `hitl_interrupt_payload` and routes to `hitl`.
3. `hitl` sets `status = "awaiting_approval"`, persists, and calls `interrupt(payload)`. `DebateGraph.run()` sees `__interrupt__`, emits `approval_required`, and returns `(paused_state, None)`.
4. The frontend shows the approval panel.
5. `POST /debate/{thread_id}/approve` validates synchronously (404 / 409 already running / 409 not paused / 409 round limit) and returns **202**; the continuation runs as a background task on the same SSE stream (`debate_approved`, `debate_resumed`, …).
6. `DebateGraph.approve()` resumes with `Command(resume={...})`; `interrupt()` returns the action and `hitl` applies it.

### Approval Actions

| Action | Behaviour |
|---|---|
| `approve` | Finalize as-is |
| `override` | Requires non-blank `feedback`. Stores it as `human_feedback`, sets `termination_reason="human_override"`; the finalize prompt tells the moderator the decision **must follow** this direction, and the decision carries it in `human_feedback` |
| `add_round` | `max_rounds + 1` and loop back to `proposals` — only offered and accepted below `MAX_DEBATE_ROUNDS_LIMIT` (8); may pause again |

### Requirements

- Supervised debates need `/debate/start-async`; `/debate/start` rejects `supervised=true` with 400.
- `HITL_ENABLED` must be true (default).
- A paused debate can be cancelled (`POST /debate/{id}/cancel` ends it immediately).

---

## Finalization (`finalize` node)

1. `moderator.finalize(state)` produces the LLM part of the `FinalDecision` (decision, rationale, risks, alternatives, dissent, `structured_disagreements` framed agent-vs-agent). Its prompt includes the human reviewer direction and standing ethics vetoes when present.
2. `debate_trace` is set from `state.rounds`, and `agreement_score` is overwritten with the **engine-measured** value so the decision matches the live stream.
3. `status` becomes `converged` (`consensus_reached` / `human_override`) or `max_rounds_reached`.
4. `final_decision` is written; the graph ends.

From the **final round** the node also derives:

- `minority_report` — the gate's dissenters ("Voted oppose while the majority voted support."); without stances, agents more than `MINORITY_REPORT_BAND` (0.20) below the mean confidence
- `key_disagreements` — top 5 critique points, most severe first, leaving out critiques the target `addressed` in its revision (rebutted ones stay)
- `agent_contribution_scores` — `word_overlap(position, decision) × confidence`, normalised to sum to 1
- `degraded` / `missing_agents` — expected agents absent from the final round
- `vetoes` — standing Ethics-class vetoes (`agent_name`, `reason`, `round_number`)
- `human_feedback` — the HITL override direction, if any
- `token_usage` / `estimated_cost_usd` — attached by `DebateGraph` after the graph returns (whole-debate totals)

With a memory store and `enable_agent_memory`, one memory entry per agent is saved from the last round in the background (the task is held in a module-level set until it finishes, and uses the LLM client active at that moment).

---

## DebateState — Single Source of Truth

**File:** `app/schemas/state.py`

```python
class DebateState(BaseModel):
    thread_id: str                    # UUID, auto-generated
    user_query: str                   # Original question (10–5000 chars)
    current_round: int                # 0 = not started
    max_rounds: int                   # 2–8 (MAX_DEBATE_ROUNDS_LIMIT); default 2
    min_rounds: int                   # 1–8, capped at max_rounds; default 1
    mode: str | None                  # quick / standard / thorough / custom (None for legacy rows)
    template_id: str | None           # Built-in template the query started from
    rounds: list[DebateRound]         # Full round history
    agreement_score: float            # Latest measured agreement (0–1)
    confidence_scores: dict           # Current round's per-agent confidence
    termination_reason: str | None    # Why the debate ended
    status: DebateStatus              # Lifecycle status
    use_knowledge_base: bool
    enable_agent_memory: bool
    selected_agents: list[str] | None # Per-debate agent subset (None = enabled set)
    domain_pack: str | None           # Active domain pack id
    token_usage_by_model: dict        # Usage accumulated across all segments
    human_feedback: str | None        # Direction from a HITL override
    created_at: datetime              # UTC
    updated_at: datetime              # UTC, updated by touch()
```

### DebateStatus Values

| Status | Meaning |
|---|---|
| `initialized` | Created, not started |
| `in_progress` | Running |
| `converged` | Consensus reached (or human override) |
| `max_rounds_reached` | Round limit without consensus |
| `awaiting_approval` | HITL: waiting for a human |
| `cancelled` | Cancelled by the user |
| `error` | Failed (may still be resumable from its checkpoint) |

### DebateRound

```python
class DebateRound(BaseModel):
    round_number: int                     # 1-based
    phase: DebatePhase                    # "proposal" | "critique" | "revision" | "convergence"
    agent_outputs: list[AgentResponse]    # Proposals (later replaced by revisions)
    critiques: list[CritiqueResponse]     # Cross-examination results
    tool_calls: list[dict]                # Tool invocations this round
```

### Convenience Methods

| Method | Description |
|---|---|
| `current_round_data()` | The active round |
| `latest_outputs()` | Agent outputs from the latest round |
| `latest_critiques()` | Critiques from the latest round |
| `touch()` | Update `updated_at` |

---

## Parallel Execution Model

**Sequential phases, parallel agents:**

```
Round N:
  proposals   ──► [Analyst] [Risk] [Strategy] [Ethics]  ← asyncio.gather
  critiques   ──► [12 critique pairs]                    ← asyncio.gather
  revisions   ──► [Analyst] [Risk] [Strategy] [Ethics]  ← asyncio.gather
  convergence ──► [Moderator]                           ← single LLM call
```

Every call takes a slot from `llm_call_slot(provider)` (at most `LLM_MAX_CONCURRENCY` calls in flight per provider, default 4; `0` disables the cap) before its `asyncio.wait_for()` timeout starts. The slot is re-entrant through a context variable, so nested calls never deadlock. Failed agents are skipped.

---

## SSE Event Streaming

`DebateGraph` accepts optional `queue_list`, `replay_buffer` and `persist_queue` (injected by the async API route). `_emit(event_type, data)` publishes typed payloads:

| Event type | Emitted by |
|---|---|
| `debate_started` | `run()` (includes participating `agents`) |
| `round_started`, `phase_started` | `proposals` node (and each phase) |
| `agent_output` | `proposals` and `revisions` nodes |
| `agent_timeout` | any phase node on a timeout |
| `tool_called` | agent tool use (`emit_callback`) |
| `critique_completed` | `critiques` node |
| `synthesis` | `convergence` node |
| `approval_required` | `run()/resume()/approve()` on `__interrupt__` |
| `debate_resumed` / `debate_approved` | `resume()` / `approve()` |
| `debate_completed` | `finalize` node |
| `final_decision`, `cancelled`, `error` | API background runner |

With a `persist_queue`, a per-debate writer task stores each payload on one connection in emission order (retrying when the database is busy), assigns the `event_id`, then broadcasts — so a live frame has the same id a replay would. Without a writer (synchronous `/debate/start`), `_emit` broadcasts directly. The stream endpoint adds a named `ping` every 20 s.

---

## Dual Storage Layer

### In-Memory (Fast Path)

`app/api/dependencies.py`:

```python
_debate_store = BoundedStore(200, is_evictable=finished)  # live + recent debates
_decision_store = BoundedStore(200, any)                  # recent decisions
_thread_locks: dict[str, asyncio.Lock]                    # per-debate locks
_event_queues: dict[str, list]                            # SSE subscriber queues
_event_replays: dict[str, list]                           # SSE replay buffers
_background_tasks: dict[str, asyncio.Task]                # running debate tasks
_active_runs: set[str]                                    # blocking runs in progress
_simulation_jobs: dict[str, dict]                         # simulation jobs
```

`BoundedStore` is an `OrderedDict` capped at 200 entries. The debate store only evicts **finished** debates (running and paused ones are never dropped); anything evicted is still served from SQLite. Replay queues of finished debates are released once their stream ends.

### SQLite Persistence (Durable Path)

The schema is managed by **Alembic migrations** (`backend/alembic/versions/`: initial schema → phase 3/4 tables → agent-memory NOCASE index), applied on startup by `run_migrations()`, which also switches the database to WAL mode. Database paths are resolved relative to `backend/`, so the server finds the same database whatever directory it is started from.

**Tables:**
- `debates` — thread_id, user_query, status, current_round, max_rounds, agreement_score, termination_reason, state_json, created_at, updated_at
- `decisions` — thread_id, user_query, decision_text, decision_json, `evaluation_json`, created_at (kept on re-save)
- `debate_events` — event_id, thread_id, event_type, payload_json, created_at (ordered, replayable)
- `agent_memory` — memory_id, agent_name, debate_id, summary, lesson_learned, created_at; indexed on `(agent_name COLLATE NOCASE, created_at)` for the case-insensitive lookups

**CRUD** (`app/db/crud.py`):
- `upsert_debate` / `save_decision` / `save_debate_event`
- `get_history(db, page, limit, q, sort, termination_reason)` — search, filter and sort in SQL before paging; `%` and `_` in the search match literally
- `get_decision_json` / `get_debate_state_json` — recovery and status fallbacks
- `get_evaluation_json` / `save_evaluation`
- `get_analytics_overview / _agents / _convergence / _quality` — the `/analytics/*` endpoints
- `cleanup_old_debates(db, ttl_days)` — startup purge (`DEBATE_TTL_DAYS`, default 90)

State snapshots are written after each node; when a debate finishes, the decision is stored first and only then are its checkpoints deleted (and the analytics cache cleared).

> The LangGraph **checkpoint** database (`CHECKPOINT_DATABASE_URL`) is separate and stores per-debate graph snapshots for HITL and resume.
