# API Reference

Complete reference for all REST endpoints exposed by the AgentBoard backend.

**Base URL:** `http://localhost:8000` (the frontend reaches it through its `/backend/*` proxy).

Interactive docs generated from the code: **Swagger UI** at `/docs`, **ReDoc** at `/redoc`.

---

## Endpoints Summary

| Method | Path | Description | Auth |
|---|---|---|---|
| `POST` | `/debate/start` | Start a debate synchronously | — |
| `POST` | `/debate/start-async` | Start a debate as a background task | — |
| `GET` | `/debate/{thread_id}/stream` | SSE stream of live events | — |
| `GET` | `/debate/{thread_id}` | Debate status & rounds | — |
| `POST` | `/debate/{thread_id}/resume` | Resume from checkpoint (blocking) | — |
| `POST` | `/debate/{thread_id}/resume-async` | Resume from checkpoint in the background | — |
| `POST` | `/debate/{thread_id}/approve` | HITL: approve / override / add round | — |
| `POST` | `/debate/{thread_id}/cancel` | Cancel a running or paused debate | — |
| `POST` | `/debate/simulate` | Run N debates and measure stability (blocking) | — |
| `POST` | `/debate/simulate-async` | Start a simulation job | — |
| `GET` | `/debate/simulate/{job_id}` | Poll a simulation job | — |
| `POST` | `/debate/simulate/{job_id}/cancel` | Cancel a simulation job | — |
| `GET` | `/debate-modes` | Mode presets and the configured default mode | — |
| `GET` | `/decision/{thread_id}` | Retrieve final decision | — |
| `GET` | `/decision/{thread_id}/export` | Export as Markdown, PDF or JSON | — |
| `POST` | `/decision/{thread_id}/evaluate` | LLM-as-judge quality evaluation | — |
| `GET` | `/history` | Paginated history (search, filter, sort) | — |
| `GET` | `/history/{thread_id}` | Stored decision for one debate | — |
| `GET` | `/agents` | List registered agents | — |
| `GET` | `/templates` | Browse debate templates | — |
| `GET` | `/domain-packs` | List domain agent packs | — |
| `POST` | `/knowledge/upload` | Upload a document to the KB | — |
| `GET` | `/knowledge/documents` | List KB documents | — |
| `DELETE` | `/knowledge/documents/{doc_name}` | Delete a KB document | **Admin** |
| `GET` | `/memory/{agent_name}` | Agent memory entries | — |
| `DELETE` | `/memory/{agent_name}` | Clear agent memory | **Admin** |
| `GET` | `/llm-settings` | Active LLM provider & model | — |
| `POST` | `/llm-settings` | Switch LLM provider at runtime | **Admin** |
| `GET` | `/analytics/overview` | KPIs and per-day trend | — |
| `GET` | `/analytics/agents` | Per-agent stats, agreement matrix | — |
| `GET` | `/analytics/convergence` | Agreement-by-round, mode/domain breakdowns | — |
| `GET` | `/analytics/quality` | Quality scores by template/mode/domain | — |
| `GET` | `/health` | Health check | — |
| `GET` | `/metrics` | Application metrics snapshot | — |

### Admin authentication

Endpoints marked **Admin** use the `require_admin` dependency (`app/core/security.py`):

- When `ADMIN_API_TOKEN` is set, the request must send it in the `X-Admin-Token` header (compared in constant time). Missing or wrong → **401** `admin_token_required`.
- When it is not set: allowed in development, refused in production (`APP_ENV=production`) with **403** `admin_disabled`.

### Rate limits

Limits are per **client IP**. `X-Forwarded-For` is only honoured when the request comes from an address in `TRUSTED_PROXY_IPS` (the Next.js proxy), so each browser gets its own quota.

| Endpoint | Limit |
|---|---|
| `POST /debate/start`, `POST /debate/start-async` | `RATE_LIMIT_PER_MINUTE`/minute (default 30) |
| `POST /debate/simulate`, `POST /debate/simulate-async` | the per-minute limit **and** 2/hour (each simulation is 2–5 debates) |
| `POST /knowledge/upload` | 10/minute |

Exceeding a limit returns **429**.

### Errors

Most errors use the `ErrorResponse` shape `{ "error": "<code>", "detail": "<message>" }` inside FastAPI's `detail`. LLM failures are mapped globally: `LLMRateLimitError` → **429** `llm_rate_limit`, `LLMResponseError` → **502** `llm_response_error`, `LLMConnectionError` → **503** `llm_connection_error`; anything else → **500** `internal_server_error` (no internal details leak).

---

## POST /debate/start

Start a new multi-agent debate. The call **blocks** until the final decision is produced (typically 30–90 s). Supervised (HITL) debates must use `/debate/start-async`.

### Request Body — `DebateStartRequest`

```json
{
  "query": "Should our company expand into the Asian market in Q3?",
  "mode": "quick",
  "max_rounds": null,
  "min_rounds": null,
  "consensus_threshold": null,
  "skip_critique_phase": null,
  "agents": null,
  "use_knowledge_base": false,
  "enable_agent_memory": false,
  "domain_pack": null,
  "supervised": false,
  "template_id": null
}
```

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `query` | `string` | Yes | 10–5000 chars | The question for the agents to debate |
| `mode` | `string` or `null` | No | `"quick"` / `"standard"` / `"thorough"` / `"custom"` | Preset for rounds, minimum rounds, threshold and critique phase. Omitted → `DEFAULT_DEBATE_MODE` (Quick unless configured). `custom` = Standard's settings with your own rounds/threshold |
| `max_rounds` | `integer` or `null` | No | 2–8 | Maximum rounds (overrides the preset) |
| `min_rounds` | `integer` or `null` | No | 1–8 | Rounds before consensus may be declared; clamped to `max_rounds` (overrides the preset) |
| `consensus_threshold` | `float` or `null` | No | 0.1–0.95 | Agreement needed to stop early (overrides the preset) |
| `skip_critique_phase` | `bool` or `null` | No | — | Skip critique & revision phases (overrides the preset) |
| `agents` | `string[]` or `null` | No | ≥ 2 agents besides `Moderator` | Subset of agents; `null`/`[]` = all enabled agents |
| `use_knowledge_base` | `bool` | No (`false`) | — | Retrieve context from the knowledge base |
| `enable_agent_memory` | `bool` | No (`false`) | — | Inject lessons from past debates |
| `domain_pack` | `string` or `null` | No | `"finance"` / `"engineering"` / `"legal"` / `"healthcare"` | Use a domain pack's agents (replaces `agents`) |
| `supervised` | `bool` | No (`false`) | — | Pause for human approval (async only) |
| `template_id` | `string` or `null` | No | id from `GET /templates` | Template the query started from (analytics only; unknown ids are dropped) |

Mode presets (see also `GET /debate-modes`):

| Mode | max_rounds | min_rounds | consensus_threshold | skip_critique_phase |
|---|---|---|---|---|
| `quick` (default) | 2 | 1 | 0.60 | `true` |
| `standard` | 2 | 2 | 0.75 | `false` |
| `thorough` | 6 | 3 | 0.85 | `false` |
| `custom` | as `standard`, with your overrides | | | |

### Response — `200 OK`

Returns a [`FinalDecision`](#finaldecision-schema):

```json
{
  "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "query": "Should our company expand into the Asian market in Q3?",
  "decision": "Proceed with a phased expansion into Southeast Asia starting Q3...",
  "rationale_summary": "The agents converged on a phased entry...",
  "confidence_score": 0.85,
  "agreement_score": 0.87,
  "risk_flags": ["Regulatory complexity varies across ASEAN markets"],
  "alternatives": ["Full 5-country rollout", "Delay to Q1 next year"],
  "dissenting_opinions": [],
  "minority_report": [],
  "key_disagreements": ["..."],
  "structured_disagreements": [
    {
      "topic": "Timing of entry",
      "positions": [
        { "agent": "Strategy", "stance": "Enter in Q3 to pre-empt competitors." },
        { "agent": "Risk", "stance": "Delay to Q4 until currency volatility settles." }
      ]
    }
  ],
  "agent_contribution_scores": { "Analyst": 0.31, "Strategy": 0.42, "Risk": 0.18, "Ethics": 0.09 },
  "degraded": false,
  "missing_agents": [],
  "token_usage": { "input_tokens": 18450, "output_tokens": 5210, "total_tokens": 23660, "by_model": { "llama-3.3-70b-versatile": { "input_tokens": 18450, "output_tokens": 5210 } } },
  "estimated_cost_usd": 0.015,
  "human_feedback": null,
  "vetoes": [],
  "debate_trace": [ ],
  "total_rounds": 2,
  "termination_reason": "consensus_reached",
  "created_at": "2026-02-28T12:00:00Z"
}
```

### Error Responses

| Status | Error Code | Cause |
|---|---|---|
| `400` | `supervised_requires_async` | `supervised: true` sent to the blocking endpoint |
| `422` | Validation error | Query length, ranges, fewer than 2 debating agents |
| `422` | `unknown_domain_pack` / `unknown_agents` | Unknown pack id or agent name |
| `429` | `llm_rate_limit` or rate limit | Provider 429 or app rate limit |
| `502` | `llm_response_error` | LLM returned unusable output |
| `503` | `llm_connection_error` | Cannot reach the LLM API |

```bash
curl -X POST http://localhost:8000/debate/start \
  -H "Content-Type: application/json" \
  -d '{"query": "Should our company expand into the Asian market in Q3?", "mode": "standard"}'
```

---

## POST /debate/start-async

Start a debate in a background task and return at once. Same request body as `/debate/start` (supervised debates are allowed here).

### Response — `200 OK` — `AsyncDebateStartResponse`

```json
{
  "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "initialized",
  "stream_url": "/debate/3fa85f64-5717-4562-b3fc-2c963f66afa6/stream"
}
```

Flow: start → open `GET /debate/{thread_id}/stream` → receive live events → the stream ends after `final_decision` (or `cancelled` / `error`). A supervised debate pauses with `approval_required` and continues after `POST /debate/{id}/approve`.

---

## GET /debate/{thread_id}/stream

**Server-Sent Events** (`text/event-stream`) for live debate progress.

### Reconnecting

Every event carries an SSE `id`. On reconnect, send the last id in the `Last-Event-ID` header or the `last_event_id` query parameter; only later events are replayed. Events are persisted by a single writer per debate in emission order, so a live frame has the same id a replay would give it.

### Event Types

| Event | Emitted by | Payload |
|---|---|---|
| `debate_started` | graph start | `{ thread_id, user_query, max_rounds, agents }` |
| `round_started` | proposals node | `{ round_number, max_rounds }` |
| `phase_started` | each node | `{ round_number, phase }` — `proposal`, `critique`, `revision`, `convergence` |
| `agent_output` | proposals & revisions | `{ round_number, phase, agent_name, position, reasoning, confidence_score, assumptions, veto, veto_reason }` |
| `critique_completed` | critiques node | `{ round_number, critic_agent, target_agent, severity, critique_points, confidence_score }` |
| `synthesis` | convergence node | `{ round_number, agreement_score, confidence_agreement_score, position_agreement_score, semantic_agreement_score, summary, agreement_areas, disagreement_areas }` |
| `tool_called` | agent tool use | `{ agent_name, tool_name, input, output_snippet }` |
| `agent_timeout` | timeout handler | `{ round_number, phase, agent_name }` |
| `approval_required` | hitl node (supervised) | `{ round_number, agreement_score, termination_reason, synthesis_summary, options }` — options are the allowed actions (`add_round` only below the round limit) |
| `debate_approved` | `/approve` | `{ thread_id, action }` |
| `debate_resumed` | `/resume-async`, `/approve` | `{ thread_id }` |
| `debate_completed` | finalize node | `{ thread_id, termination_reason, total_rounds, agreement_score }` |
| `final_decision` | background task | Full `FinalDecision` |
| `cancelled` | `/cancel` | `{ thread_id, detail }` — terminal |
| `error` | on failure | `{ error, error_type, detail }` — terminal; e.g. `decision_unavailable` when a finished debate's decision can't be loaded |
| `ping` | every 20 s while idle | `{}` — named keep-alive event (comments are invisible to `EventSource`) |

The `synthesis` event carries the **measured** agreement. The moderator's own continue/stop recommendation is not sent; the convergence gate alone decides whether another round runs.

### Behaviour

- Late joiners get a replay of the stored events, then live events.
- The stream ends after a terminal event (`final_decision`, `cancelled`, `error`).
- If the debate already finished, the stored decision is sent and the stream ends.
- Unknown `thread_id` → **404** `debate_not_found`.

---

## GET /debate/{thread_id}

Current status and round history. Looks in the in-memory store, then SQLite.

### Response — `200 OK` — `DebateStatusResponse`

```json
{
  "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "in_progress",
  "current_round": 2,
  "total_rounds": 4,
  "agreement_score": 0.61,
  "rounds": [ ]
}
```

`total_rounds` is the configured maximum. **404** `debate_not_found` if unknown.

---

## GET /decision/{thread_id}

The final decision of a completed debate (memory, then SQLite).

| Status | Error Code | Cause |
|---|---|---|
| `404` | `debate_not_found` | Unknown `thread_id` |
| `409` | `debate_in_progress` | The debate hasn't finished |

---

## POST /debate/{thread_id}/resume

Resume an interrupted or failed debate from its LangGraph checkpoint and **wait** for the result.

### Responses

- **200** — `FinalDecision` (also returned at once if the debate had already completed).
- **202** — the resumed run reached a supervised pause again: `{ thread_id, status: "awaiting_approval", current_round, total_rounds }`.

| Status | Error Code | Cause |
|---|---|---|
| `400` | `no_checkpoint_available` | No checkpoint to resume from |
| `404` | `debate_not_found` | Unknown `thread_id` |
| `409` | `debate_in_progress` | A run for this debate is still active |
| `409` | `debate_awaiting_approval` | Paused for approval — use `/approve` |
| `500` | `resume_failed` | The resumed run failed (message is sanitised) |

---

## POST /debate/{thread_id}/resume-async

Resume from the checkpoint as a background task; progress streams on the debate's SSE stream (`debate_resumed`, then the remaining events). The UI's **Resume debate** button uses this.

### Response — `202 Accepted`

```json
{ "thread_id": "3fa85f64-...", "status": "resuming" }
```

| Status | Error Code | Cause |
|---|---|---|
| `400` | `no_checkpoint_available` | Nothing to resume |
| `404` | `debate_not_found` | Unknown `thread_id` |
| `409` | `debate_already_completed` | The debate already has a decision |
| `409` | `debate_in_progress` | Already running |
| `409` | `debate_awaiting_approval` | Paused for approval — use `/approve` |

---

## POST /debate/{thread_id}/approve

Answer a supervised debate's `approval_required` pause. Validation happens synchronously; the continuation runs in the background on the same SSE stream.

### Request Body — `ApproveRequest`

```json
{ "action": "override", "feedback": "Weight the regulatory risk more heavily." }
```

| Field | Type | Default | Description |
|---|---|---|---|
| `action` | `"approve"` / `"override"` / `"add_round"` | `"approve"` | Accept, redirect, or run one more round |
| `feedback` | `string` (≤ 5000) | `""` | **Required** (non-blank) for `override` |

| Action | Behaviour |
|---|---|
| `approve` | Finalize with the converged result |
| `override` | Finalize following the reviewer's direction (`termination_reason: "human_override"`); the decision carries it in `human_feedback` |
| `add_round` | Run one more round (up to the 8-round limit); the debate may pause again |

### Response — `202 Accepted`

```json
{ "thread_id": "3fa85f64-...", "status": "resuming", "action": "override" }
```

| Status | Error Code | Cause |
|---|---|---|
| `404` | `debate_not_found` | Unknown `thread_id` |
| `409` | `debate_in_progress` | A continuation is already running (e.g. a double click) |
| `409` | `debate_not_awaiting_approval` | The debate isn't paused for approval |
| `409` | `round_limit_reached` | `add_round` when the debate is already at the round limit |
| `422` | Validation error | `override` without feedback |

---

## POST /debate/{thread_id}/cancel

Stop a running debate (no further LLM calls) or end a paused one.

### Response — `200 OK`

- Running: `{ "thread_id": "...", "status": "cancelling" }` — the background task stops at its next await, persists status `cancelled` and emits a terminal `cancelled` event.
- Paused for approval: `{ "thread_id": "...", "status": "cancelled" }` — ended immediately.

| Status | Error Code | Cause |
|---|---|---|
| `404` | `debate_not_found` | Unknown `thread_id` |
| `409` | `debate_not_running` | Already finished or cancelled |

---

## POST /debate/simulate

Run N independent debates on the same query and measure how stable the decision is. **Blocks** until all runs finish — the UI uses the job API below instead.

### Request Body — `SimulateRequest`

| Field | Type | Default | Constraints | Description |
|---|---|---|---|---|
| `query` | `string` | — | 10–5000 chars | The question to simulate |
| `runs` | `integer` | `3` | 2–5 | Number of debates |
| `max_rounds` | `integer` or `null` | `null` | 2–6 | Omitted → the mode's preset |
| `mode` | `string` | `DEFAULT_DEBATE_MODE` | `"quick"` / `"standard"` / `"thorough"` / `"custom"` | Mode for every run |
| `agents` | `string[]` or `null` | `null` | ≥ 2 besides `Moderator` | Agent subset |
| `domain_pack` | `string` or `null` | `null` | — | Replaces `agents` |
| `use_knowledge_base` | `bool` | `false` | — | KB context in each run |
| `enable_agent_memory` | `bool` | `false` | — | Past-debate lessons in each run |

### Response — `200 OK` — `SimulationResult`

```json
{
  "query": "Should we acquire competitor X?",
  "runs": 3,
  "runs_completed": 3,
  "decisions": [ ],
  "consistency_score": 0.74,
  "confidence_variance": 0.041,
  "avg_agreement_score": 0.81,
  "stable_risk_flags": ["Integration complexity"],
  "stability_rating": "Medium"
}
```

| Field | Description |
|---|---|
| `runs_completed` | Runs that finished (failed runs are skipped) |
| `consistency_score` | How alike the decisions are: mean pairwise word overlap, rescaled with the consensus gate's anchors (0 = as different as decisions to unrelated questions, 1 = the same decision reworded) |
| `confidence_variance` | Standard deviation of `agreement_score` across runs |
| `stable_risk_flags` | Risks raised — in any wording — in ≥ 70 % of runs, each listed once |
| `stability_rating` | `"High"` (> 0.80), `"Medium"` (> 0.55) or `"Low"`, from `consistency_score` |

Simulation runs are not saved to history; their checkpoints are deleted after each run.

---

## Simulation jobs

### POST /debate/simulate-async — `202 Accepted`

Same body as `/debate/simulate`. Returns:

```json
{ "job_id": "a1b2…", "status": "running", "result": null, "error": null, "status_url": "/debate/simulate/a1b2…" }
```

### GET /debate/simulate/{job_id}

```json
{ "job_id": "a1b2…", "status": "completed", "result": { "…SimulationResult…" }, "error": null }
```

`status` is `running`, `completed`, `failed` (see `error`) or `cancelled`. The UI polls every 2 s.

### POST /debate/simulate/{job_id}/cancel

Cancels a running job (also sent by the UI when you leave the page). Returns the job view. Unknown job → **404** `simulation_not_found`.

---

## GET /debate-modes

The mode presets and the configured default (`DEFAULT_DEBATE_MODE`, Quick when not set). The home and Simulate pages pre-select `default_mode`.

```json
{
  "default_mode": "quick",
  "presets": {
    "quick":    { "max_rounds": 2, "consensus_threshold": 0.6,  "skip_critique_phase": true,  "min_rounds": 1 },
    "standard": { "max_rounds": 2, "consensus_threshold": 0.75, "skip_critique_phase": false, "min_rounds": 2 },
    "thorough": { "max_rounds": 6, "consensus_threshold": 0.85, "skip_critique_phase": false, "min_rounds": 3 },
    "custom":   { "max_rounds": 2, "consensus_threshold": 0.75, "skip_critique_phase": false, "min_rounds": 2 }
  }
}
```

---

## POST /decision/{thread_id}/evaluate

LLM-as-judge quality evaluation of a decision. Cached in the database after the first call; storing it refreshes the analytics cache.

### Response — `200 OK` — `EvaluationResult`

```json
{
  "thread_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "completeness": 0.85,
  "consistency": 0.9,
  "actionability": 0.78,
  "risk_awareness": 0.75,
  "overall": 0.82,
  "reasoning": "The decision is well supported but could elaborate on...",
  "evaluated_at": "2026-02-28T12:05:00Z"
}
```

`overall` is the mean of the four dimension scores (each 0–1). **404** `decision_not_found` if there is no decision.

---

## GET /decision/{thread_id}/export

Download a decision.

| Parameter | Default | Values |
|---|---|---|
| `format` | `markdown` | `markdown`, `pdf`, `json` |

Markdown and PDF (rendered from the HTML version with WeasyPrint, off the event loop) include the human reviewer direction and standing vetoes when present.

| Status | Cause |
|---|---|
| `400` | Unsupported format |
| `404` | Decision not found |
| `501` | PDF requested but WeasyPrint isn't available |

---

## GET /history

Paginated history of completed debates. Searching, filtering and sorting run in SQL over the whole history, before paging.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | `integer` | `1` | ≥ 1 |
| `limit` | `integer` | `20` | 1–100 |
| `q` | `string` | — | Search in the query and decision text (`%`, `_` match literally) |
| `sort` | `string` | `newest` | `newest`, `oldest`, `highest_agreement` |
| `termination_reason` | `string` | — | `consensus_reached`, `human_override` or `max_rounds_reached` |

Invalid `sort` / `termination_reason` values → **422**.

### Response — `200 OK` — `HistoryListResponse`

```json
{
  "items": [
    {
      "thread_id": "3fa85f64-...",
      "user_query": "Should our company expand into the Asian market?",
      "created_at": "2026-02-28T12:00:00Z",
      "status": "converged",
      "total_rounds": 2,
      "agreement_score": 0.87,
      "termination_reason": "consensus_reached",
      "use_knowledge_base": false,
      "enable_agent_memory": false
    }
  ],
  "total": 42,
  "page": 1,
  "limit": 20
}
```

`total_rounds` is the number of rounds actually run. For older rows without stored values, rounds, termination reason and agreement fall back to the saved decision.

---

## GET /history/{thread_id}

The stored `FinalDecision` for one debate. **404** `decision_not_found`.

---

## GET /health

```json
{
  "status": "ok",
  "version": "2.0.0",
  "llm": { "provider": "groq", "model": "llama-3.3-70b-versatile", "configured": true },
  "groq_configured": true
}
```

`llm` describes the provider debates use right now (it follows runtime switches via `/llm-settings`) and whether it has an API key; it is computed without creating the client. `groq_configured` is kept for older clients.

---

## GET /metrics

In-process counters since startup:

```json
{
  "started_at": "2026-02-28T11:00:00+00:00",
  "uptime_seconds": 3600.0,
  "requests_total": 1200,
  "avg_request_duration_ms": 12.4,
  "responses_by_status": { "200": 1180, "404": 20 },
  "events": { "debate.started_async": 45, "debate.completed": 42 },
  "routes": { "GET /health": { "count": 800, "avg_duration_ms": 1.2, "last_status": 200, "last_seen_at": "..." } }
}
```

---

## GET /agents

```json
[
  {
    "name": "Analyst",
    "role": "Objective data analyst",
    "icon": "📊",
    "enabled": true,
    "model_provider": null,
    "model_name": null,
    "temperature": 0.3
  }
]
```

`model_provider` / `model_name` are `null` unless the agent has a per-agent override. Domain agents are listed with `enabled: false`; they take part through a domain pack.

---

## GET /templates

Built-in templates (17). Query parameters: `category`, `q` (searches title, query and tags). Each template has `id`, `title`, `category`, `icon`, `query`, `mode` (its recommended mode) and `tags`.

## GET /domain-packs

The four domain packs (`finance`, `engineering`, `legal`, `healthcare`), each with `id`, `name`, `description`, `icon`, `agents`, `paired_template_categories` and `domain_focus` (a display description; it is not added to agent prompts).

---

## POST /knowledge/upload

Multipart upload of one file (`.pdf`, `.txt` or `.md`), chunked and indexed in ChromaDB. The file is streamed to disk in chunks, never held whole in memory; ingestion runs off the event loop.

```json
{ "filename": "market-report-2026.pdf", "chunks_indexed": 47 }
```

| Status | Cause |
|---|---|
| `413` | Larger than `KB_MAX_FILE_MB` (refused by middleware from Content-Length before parsing, or while copying) |
| `422` | Unsupported file type, or nothing could be extracted |
| `501` | Knowledge base not available (dependencies missing or the embedding model failed to load) |

## GET /knowledge/documents

```json
[ { "name": "market-report-2026.pdf", "chunks": 47 } ]
```

Returns `[]` when the knowledge base isn't available.

## DELETE /knowledge/documents/{doc_name} — Admin

```json
{ "doc_name": "market-report-2026.pdf", "chunks_deleted": 47 }
```

**501** if the knowledge base isn't available.

---

## GET /memory/{agent_name}

Lessons stored for an agent (name matching is case-insensitive). Query: `limit` (default 20, 1–100). Each entry: `memory_id`, `agent_name`, `debate_id`, `summary`, `lesson_learned`, `created_at`.

## DELETE /memory/{agent_name} — Admin

```json
{ "agent_name": "Analyst", "deleted": 12 }
```

`deleted` is the number of entries removed.

---

## GET /llm-settings

```json
{
  "provider": "groq",
  "model": "llama-3.3-70b-versatile",
  "available_models": {
    "groq": ["llama-3.3-70b-versatile", "..."],
    "openai": ["gpt-5.5", "..."],
    "anthropic": ["claude-opus-4-8", "..."],
    "gemini": ["gemini-3.5-flash", "..."]
  },
  "using_custom_key": false,
  "server_keys": { "groq": true, "openai": false, "anthropic": false, "gemini": false },
  "admin_token_required": true
}
```

| Field | Description |
|---|---|
| `available_models` | `PROVIDER_MODELS` from `app/schemas/api_models.py` (first entry = UI default) |
| `using_custom_key` | `true` when the active client uses a caller-supplied key |
| `server_keys` | Which providers have a key configured on the server |
| `admin_token_required` | Whether `POST /llm-settings` needs `X-Admin-Token` |

API key values are never returned.

## POST /llm-settings — Admin

Switches the provider and model for **all** users until restart.

```json
{ "provider": "openai", "model": "gpt-5.5", "api_key": null }
```

| Field | Description |
|---|---|
| `provider` | `groq`, `openai`, `anthropic` or `gemini` |
| `model` | Must be in the provider's list (**422** otherwise) |
| `api_key` | Optional: used instead of the server's key; held in memory only, never persisted |

If neither the request nor the server has a key for the provider → **400** `api_key_required`. Response: same shape as `GET /llm-settings`.

---

## Analytics

Served by `app/api/analytics.py`. Every endpoint accepts `days` (`0` = all time, max 365) and is cached in-process for 5 minutes; the cache is cleared whenever a debate is stored or a decision is evaluated.

### GET /analytics/overview

```json
{
  "total_debates": 142,
  "avg_rounds": 1.9,
  "avg_rounds_to_consensus": 1.6,
  "avg_agreement_score": 0.78,
  "debates_by_termination": { "consensus_reached": 110, "max_rounds_reached": 28, "human_override": 4 },
  "debates_per_day": [ { "date": "2026-03-20", "count": 5 } ],
  "trend_days": 30
}
```

`avg_rounds` covers all completed debates; `avg_rounds_to_consensus` only those that reached consensus (`null` if none). Termination reasons of older rows fall back to the stored decision. `debates_per_day` counts completed debates over `trend_days` (the selected range, or 30 days for all time).

### GET /analytics/agents

```json
{
  "agents": {
    "Analyst": { "avg_confidence": 0.82, "avg_critique_severity_given": { "medium": 4, "high": 1 }, "avg_contribution_score": 0.31 }
  },
  "agreement_matrix": {
    "Analyst":  { "Analyst": 1.0, "Strategy": 0.62, "Finance": null },
    "Strategy": { "Analyst": 0.62, "Strategy": 1.0, "Finance": null }
  }
}
```

`agreement_matrix` is symmetric: how alike two agents' **final-round positions** were (0–1, the consensus gate's scale), averaged over the debates both took part in; `null` for pairs that never debated together.

### GET /analytics/convergence

```json
{
  "avg_agreement_by_round": [0.45, 0.68],
  "mode_breakdown": { "quick": 18, "standard": 96, "thorough": 28, "custom": 5 },
  "domain_pack_breakdown": { "default": 120, "finance": 12 }
}
```

### GET /analytics/quality

```json
{
  "evaluated_count": 24,
  "avg_quality_score": 0.79,
  "scores_by_template": { "Market Expansion": 0.82 },
  "scores_by_mode": { "quick": 0.65, "standard": 0.78 },
  "scores_by_domain_pack": { "default": 0.77, "finance": 0.8 },
  "best_performing_templates": ["Market Expansion"],
  "worst_performing_templates": ["Market Expansion"]
}
```

Template scores only include debates started from a built-in template (`template_id`), keyed by template title. Returns `evaluated_count: 0` and `avg_quality_score: null` when nothing has been evaluated.

---

## Data Schemas

### FinalDecision Schema

| Field | Type | Description |
|---|---|---|
| `thread_id` | `string` | Debate id |
| `query` | `string` | Original question |
| `decision` | `string` | Actionable decision |
| `rationale_summary` | `string` | Why it was chosen |
| `confidence_score` | `float [0,1]` | Moderator's confidence |
| `agreement_score` | `float [0,1]` | Consensus level |
| `risk_flags` | `string[]` | Key risks |
| `alternatives` | `string[]` | Options considered but not chosen |
| `dissenting_opinions` | `string[]` | Positions that diverged |
| `minority_report` | `MinorityReportEntry[]` | `{ agent_name, final_position, dissent_reason, confidence_score }` for agents whose final confidence is more than `MINORITY_REPORT_BAND` below the mean |
| `key_disagreements` | `string[]` | Top unresolved final-round critique points, most severe first |
| `structured_disagreements` | `StructuredDisagreement[]` | `{ topic, positions: [{ agent, stance }] }` |
| `agent_contribution_scores` | `dict[str, float]` | Alignment × confidence per agent, normalised to sum to 1 |
| `degraded` | `bool` | `true` when expected agents were missing from the final round |
| `missing_agents` | `string[]` | Agents absent from the final round |
| `token_usage` | `dict` | `input_tokens`, `output_tokens`, `total_tokens`, `by_model` — summed over all segments (HITL pauses, resumes) |
| `estimated_cost_usd` | `float \| null` | Best-effort cost (null if the price is unknown) |
| `human_feedback` | `string \| null` | Reviewer direction from a HITL override, which the decision followed |
| `vetoes` | `VetoEntry[]` | Ethics vetoes still standing at the end: `{ agent_name, reason, round_number }` |
| `debate_trace` | `DebateRound[]` | Full round history |
| `total_rounds` | `integer` | Rounds run |
| `termination_reason` | `string` | `consensus_reached`, `human_override` or `max_rounds_reached` |
| `created_at` | `datetime` | UTC timestamp |

### AgentResponse Schema

| Field | Type | Description |
|---|---|---|
| `agent_name` | `string` | `"Analyst"`, `"Risk"`, … |
| `round_number` | `integer` | ≥ 1 |
| `position` | `string` | The agent's stance |
| `reasoning` | `string` | Supporting reasoning |
| `assumptions` | `string[]` | Explicit assumptions |
| `confidence_score` | `float [0,1]` | Self-assessed confidence |
| `veto` | `bool` | Ethics-class agents only: the position vetoes the proposal (blocks consensus) |
| `veto_reason` | `string \| null` | Why, and what would lift it |
| `timestamp` | `datetime` | UTC |

### CritiqueResponse Schema

| Field | Type | Description |
|---|---|---|
| `critic_agent` | `string` | Critic |
| `target_agent` | `string` | Agent critiqued |
| `round_number` | `integer` | Round |
| `critique_points` | `string[]` | Issues found |
| `severity` | `string` | `low`, `medium`, `high`, `critical` |
| `suggested_revision` | `string?` | Optional suggestion |
| `confidence_score` | `float [0,1]` | Critic's confidence |
| `timestamp` | `datetime` | UTC |

### DebateStatusResponse Schema

| Field | Type | Description |
|---|---|---|
| `thread_id` | `string` | Debate id |
| `status` | `string` | `initialized`, `in_progress`, `converged`, `max_rounds_reached`, `awaiting_approval`, `cancelled` or `error` |
| `current_round` | `integer` | Current round (0 = not started) |
| `total_rounds` | `integer` | Maximum rounds |
| `agreement_score` | `float [0,1]` | Latest agreement |
| `rounds` | `DebateRound[]` | Rounds so far |

### HistoryItem Schema

| Field | Type | Description |
|---|---|---|
| `thread_id` | `string` | Debate id |
| `user_query` | `string` | Question |
| `created_at` | `string` | ISO 8601 |
| `status` | `string` | Debate status |
| `total_rounds` | `integer` | Rounds actually run |
| `agreement_score` | `float` | Final agreement |
| `termination_reason` | `string` | How it ended |
| `use_knowledge_base` | `bool` | KB was used |
| `enable_agent_memory` | `bool` | Memory was used |

### ErrorResponse Schema

| Field | Type | Description |
|---|---|---|
| `error` | `string` | Short error code |
| `detail` | `string?` | Human-readable message |
