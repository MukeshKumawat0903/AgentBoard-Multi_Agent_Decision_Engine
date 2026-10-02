# API Integration & Type System

The frontend communicates with the FastAPI backend through a typed API client layer. All network calls, TypeScript interfaces, and error handling are centralised in `src/lib/`.

---

## API Client (`src/lib/api.ts`)

### Configuration

```ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/backend";
```

By default, all API calls go to `/backend/*` on the frontend's own origin, where the route handler `src/app/backend/[...path]/route.ts` forwards them at runtime to `BACKEND_URL` (see [06-configuration-and-setup.md](06-configuration-and-setup.md)). No CORS, no hard-coded backend address, and the same image works anywhere. `NEXT_PUBLIC_API_URL` can point the browser straight at the backend instead.

### `toAbsoluteURL` Helper

```ts
function toAbsoluteURL(path: string): URL {
  if (API_BASE.startsWith("http://") || API_BASE.startsWith("https://")) {
    return new URL(path);
  }
  return new URL(path, window.location.origin);
}
```

The `EventSource` API (used for SSE streaming) requires an absolute URL. Since `API_BASE` defaults to the relative path `/backend`, this helper prepends `window.location.origin` when needed. Used exclusively in `connectToStream()`.

### Generic Fetcher

All API calls go through a single `apiFetch<T>()` function:

```ts
async function apiFetch<T>(path: string, init?: RequestInit & { signal?: AbortSignal }): Promise<T | null>
```

Behaviour:
1. Prepends `API_BASE` to the path
2. Sets `Content-Type: application/json` (not for `FormData`, so the browser sets the multipart boundary) and **merges** caller headers on top (e.g. `X-Admin-Token`)
3. Parses the JSON body (if any)
4. Non-2xx → throws `ApiError`
5. `AbortError` → returns `null` (intentional cancellation)

### `requireResult<T>` Helper

```ts
async function requireResult<T>(promise: Promise<T | null>): Promise<T>
```

Wraps `apiFetch` calls that must not return `null`. If the inner promise resolves to `null` (i.e., the request was aborted), throws an `"Request was aborted."` error. Used by most public API functions to ensure they always return a value.

### ApiError Class

```ts
class ApiError extends Error {
  status: number;        // HTTP status
  body: unknown;         // parsed JSON body
  code: string | null;   // machine-readable error code, e.g. "debate_in_progress"
}
```

The message is chosen for users:
- 5xx with no body (the proxy couldn't reach the backend) → "Backend unreachable. Is the server running?"
- Known LLM error codes (`llm_rate_limit`, `llm_response_error`, `llm_connection_error`) → a friendly explanation
- 502 / 503 / 504 → "Backend unavailable — please try again shortly."
- Otherwise `extractErrorMessage(body)` (exported): FastAPI `detail` strings, validation-error lists (`msg`s joined), nested `{ error, detail }` objects, or `error`; fallback `API error {status}`

Pages use `status` / `code` for specific handling (e.g. 409 on approve).

### Public API Functions

| Function | Method | Endpoint | Body / params | Returns |
|---|---|---|---|---|
| `startDebate(request)` | `POST` | `/debate/start` | `DebateStartRequest` | `FinalDecision` |
| `startDebateAsync(request)` | `POST` | `/debate/start-async` | `DebateStartRequest` | `AsyncDebateStartResponse` |
| `connectToStream(threadId, handlers)` | SSE | `/debate/{id}/stream` | — | `AbortController` |
| `getDebateStatus(threadId)` | `GET` | `/debate/{id}` | — | `DebateStatusResponse` |
| `getDecision(threadId)` | `GET` | `/decision/{id}` | — | `FinalDecision` |
| `resumeDebateAsync(threadId)` | `POST` | `/debate/{id}/resume-async` | — | `{ thread_id, status: "resuming" }` |
| `approveDebate(threadId, action, feedback?)` | `POST` | `/debate/{id}/approve` | `{ action, feedback }` | `ApprovalAcceptedResponse` (202) |
| `cancelDebate(threadId)` | `POST` | `/debate/{id}/cancel` | — | `{ thread_id, status }` |
| `getDebateModes()` | `GET` | `/debate-modes` | — | `DebateModesResponse` |
| `startSimulation(params)` | `POST` | `/debate/simulate-async` | simulation params | `SimulationJob` |
| `getSimulationJob(jobId)` | `GET` | `/debate/simulate/{job}` | — | `SimulationJob` |
| `cancelSimulationJob(jobId)` | `POST` | `/debate/simulate/{job}/cancel` | — | `SimulationJob` |
| `runSimulation(params)` | `POST` | `/debate/simulate` | simulation params | `SimulationResult` (blocking; not used by the UI) |
| `getHistory(params)` | `GET` | `/history` | `page, limit, q, sort, termination_reason` | `HistoryListResponse` |
| `getHistoryItem(threadId)` | `GET` | `/history/{id}` | — | `FinalDecision` |
| `evaluateDecision(threadId)` | `POST` | `/decision/{id}/evaluate` | — | `EvaluationResult` |
| `exportDecision(threadId, format)` | `GET` | `/decision/{id}/export?format=` | — | `Blob` (markdown / pdf / json) |
| `healthCheck()` | `GET` | `/health` | — | `{ status, version, llm, groq_configured }` |
| `getAgents()` | `GET` | `/agents` | — | `AgentConfigResponse[]` |
| `getTemplates(params?)` | `GET` | `/templates` | `category, q` | `DebateTemplate[]` |
| `getDomainPacks()` | `GET` | `/domain-packs` | — | `DomainPack[]` |
| `uploadKnowledgeDocument(file)` | `POST` | `/knowledge/upload` | `FormData` | `{ filename, chunks_indexed }` |
| `listKnowledgeDocuments()` | `GET` | `/knowledge/documents` | — | `KnowledgeDocument[]` |
| `deleteKnowledgeDocument(name)` | `DELETE` | `/knowledge/documents/{name}` | — (admin header) | `{ doc_name, chunks_deleted }` |
| `getAgentMemory(agentName, limit?)` | `GET` | `/memory/{agent}` | `limit` | `MemoryEntry[]` |
| `clearAgentMemory(agentName)` | `DELETE` | `/memory/{agent}` | — (admin header) | `{ agent_name, deleted }` |
| `getAnalyticsOverview / Agents / Convergence / Quality(days?)` | `GET` | `/analytics/*` | `days` | analytics types |
| `getLLMSettings()` | `GET` | `/llm-settings` | — | `LLMSettingsResponse` |
| `setLLMSettings(update)` | `POST` | `/llm-settings` | `LLMSettingsUpdate` (admin header) | `LLMSettingsResponse` |
| `getAdminToken()` / `setAdminToken(token)` | — | — | — | Admin token in `sessionStorage` |
| `extractErrorMessage(body)` | — | — | — | Readable message from an error body |

**Admin header:** `deleteKnowledgeDocument`, `clearAgentMemory` and `setLLMSettings` add `X-Admin-Token` (from `getAdminToken()`) when a token was saved; the token lives in `sessionStorage` (this tab only).

#### `startDebate(request, signal?)` — V1 Synchronous

Initiates a new multi-agent debate. This is the **synchronous V1 endpoint** — the backend processes the full debate before returning the complete `FinalDecision`. Returns `null` if aborted. Retained for backward compatibility.

#### `startDebateAsync(request, signal?)` — V2 Async

Starts a debate in the background. Returns immediately with `{ thread_id, status, stream_url }`. Returns `null` if aborted. This is the endpoint used by the home page — after receiving the response, the client navigates to the debate page which connects to the SSE stream.

#### `connectToStream(threadId, handlers)`

Follows a debate's Server-Sent Events with the browser's `EventSource`, reconnecting automatically:

```ts
interface StreamHandlers {
  onEvent: (event: DebateSSEEvent) => void;
  onError?: (error: Event) => void;   // reconnects exhausted
  onDone?: () => void;                // terminal event received
  onStatusChange?: (status: "connected" | "reconnecting" | "disconnected") => void;
}
```

**Status:** `connected` when a connection opens (also after a successful reconnect), `reconnecting` after a drop, `disconnected` when finished or given up.

**Reconnection:** exponential backoff 1 s → 2 s → 4 s → 8 s → 16 s → 30 s max; the last event id is sent as `last_event_id` so only newer events are replayed; at most 10 reconnects, then `onError`. Only real server messages (events with data) reset the backoff — the browser's own connection-failure event is also called `error`, and it reaching the `error` listener used to reset the counter and retry every second forever.

**Keep-alive:** the server sends a named `ping` event every 20 s; pings reset the 60 s stale-connection timer and the backoff but are not passed to `onEvent`. Silence for 60 s counts as a dropped connection.

**Events:** listeners for 14 types — `debate_started`, `round_started`, `phase_started`, `agent_output`, `critique_completed`, `synthesis`, `debate_completed`, `final_decision`, `approval_required`, `tool_called`, `agent_timeout`, `cancelled`, `debate_resumed`, `error` (+ `ping`). `final_decision`, `cancelled` and `error` are terminal: `onDone`, status `disconnected`, the source is closed.

Returns an `AbortController`; `abort()` closes the current source and clears all timers.

#### `cancelDebate(threadId)`

`POST /debate/{id}/cancel` — `{ thread_id, status: "cancelling" }` for a running debate (a terminal `cancelled` event follows), `{ status: "cancelled" }` for one paused for approval. `ApiError` 404 / 409 otherwise.

#### `resumeDebateAsync(threadId)` / `approveDebate(...)`

Both return **202** at once; progress continues on the debate's SSE stream (`debate_resumed`, …). `approveDebate` rejects `override` without feedback (422) and returns 409 when the debate is already continuing, isn't paused, or is at the round limit.

#### Simulation jobs

`startSimulation(params)` → `SimulationJob { job_id, status: "running" }`; poll `getSimulationJob(job_id)` until `completed` (`result`), `failed` (`error`) or `cancelled`; `cancelSimulationJob(job_id)` stops it. Params: `query`, `runs`, `mode`, optional `max_rounds` (omitted = the mode's preset), `agents`, `domain_pack`, `use_knowledge_base`, `enable_agent_memory`.

#### `getHistory(params)`

`{ page, limit, q, sort, termination_reason }` — `sort`: `newest` / `oldest` / `highest_agreement`; `termination_reason`: `consensus_reached` / `human_override` / `max_rounds_reached`. Searching, filtering and sorting happen on the server.

#### `getHistoryItem(threadId)`

Fetches the stored `FinalDecision` of a finished debate. Used by the compare page, and by the debate viewer on load — a finished debate is shown from this without needing a live stream (404 means it's still running, so the stream takes over).

#### `getDebateStatus(threadId)`

Fetches the current status and round history. Useful for polling-based progress tracking.

#### `getDecision(threadId)`

Fetches the final decision for a completed debate. Returns 404 if the thread doesn't exist, or 409 if the debate is still in progress.

#### `healthCheck()`

Health probe: status, version, `llm` (`{ provider, model, configured }` for the provider debates use right now) and the legacy `groq_configured`. The NavBar polls it for the backend status dot.

#### `getTemplates(params?)`

Fetches debate templates. Accepts optional `{ category?, q? }` query parameters for server-side filtering by category or search text.

#### `MemoryEntry` (defined in `api.ts`)

```ts
interface MemoryEntry {
  memory_id: number;
  agent_name: string;
  debate_id: string;
  summary: string;
  lesson_learned: string;
  created_at: string;
}
```

This interface is defined directly in `api.ts` (not `types.ts`) alongside the memory API functions.

---

## TypeScript Interfaces (`src/lib/types.ts`)

All TypeScript interfaces mirror the backend Pydantic schemas exactly, ensuring type safety across the API boundary.

### Agent & Critique Responses

```ts
interface AgentResponse {
  agent_name: string;
  round_number: number;
  position: string;
  reasoning: string;
  assumptions: string[];
  confidence_score: number;      // 0–1
  veto?: boolean;                // Ethics-class agents: vetoes the proposal
  veto_reason?: string | null;
  stance?: Stance | null;       // null/absent for debates stored before stance existed
  timestamp: string;
}

interface VetoEntry { agent_name: string; reason: string; round_number: number; }

interface CritiqueResponse {
  critic_agent: string;
  target_agent: string;
  round_number: number;
  critique_points: string[];
  severity: "low" | "medium" | "high" | "critical";
  suggested_revision: string | null;
  confidence_score: number;
}
```

### Debate State

```ts
type DebatePhase = "proposal" | "critique" | "revision" | "convergence";

type DebateStatus = "initialized" | "in_progress" | "converged"
                  | "max_rounds_reached" | "awaiting_approval"
                  | "cancelled" | "error";

interface ToolCallRecord {
  agent_name: string;
  tool_name: string;
  input: string;
  output_snippet: string;
}

interface DebateRound {
  round_number: number;
  phase: DebatePhase;
  agent_outputs: AgentResponse[];
  critiques: CritiqueResponse[];
  toolCalls?: ToolCallRecord[];   // accumulated during streaming
  tool_calls?: ToolCallRecord[];  // persisted on the round (saved trace)
}

interface DebateStatusResponse {
  thread_id: string;
  status: DebateStatus;
  current_round: number;
  total_rounds: number;
  agreement_score: number;
  rounds: DebateRound[];
}
```

### Final Decision

```ts
interface MinorityReportEntry {
  agent_name: string;
  final_position: string;
  dissent_reason: string;
  confidence_score: number;
}

interface AgentStance { agent: string; stance: string; }
interface StructuredDisagreement { topic: string; positions: AgentStance[]; }

interface FinalDecision {
  thread_id: string;
  query?: string;                  // Optional — echoed original query
  decision: string;
  rationale_summary: string;
  confidence_score: number;        // 0–1
  agreement_score: number;         // 0–1
  risk_flags: string[];
  alternatives: string[];
  dissenting_opinions: string[];
  debate_trace: DebateRound[];
  total_rounds: number;
  termination_reason: string;
  created_at: string;              // ISO 8601 timestamp
  // P1.5 richer output fields
  minority_report?: MinorityReportEntry[];
  key_disagreements?: string[];
  structured_disagreements?: StructuredDisagreement[];   // agent-vs-agent contested topics
  agent_contribution_scores?: Record<string, number>;
  // Degraded-run indicators
  degraded?: boolean;
  missing_agents?: string[];
  // Token usage + estimated cost
  token_usage?: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    by_model?: Record<string, { input_tokens?: number; output_tokens?: number }>;
  };
  estimated_cost_usd?: number | null;
  // Direction from a HITL override that the decision was told to follow
  human_feedback?: string | null;
  // Ethics vetoes still standing when the debate ended
  vetoes?: VetoEntry[];
}
```

### API Models

```ts
type DebateMode = "quick" | "standard" | "thorough" | "custom";

interface DebateStartRequest {
  query: string;                // 10–5000 characters
  mode?: DebateMode;            // omitted → server default (DEFAULT_DEBATE_MODE, Quick)
  template_id?: string;         // built-in template the query started from
  max_rounds?: number;          // 2–8
  consensus_threshold?: number;
  skip_critique_phase?: boolean;
  agents?: string[];            // ≥ 2 besides the Moderator
  use_knowledge_base?: boolean;
  enable_agent_memory?: boolean;
  domain_pack?: string | null;
  supervised?: boolean;         // HITL (async only)
  agreement_method?: AgreementMethod;  // omitted → server AGREEMENT_METHOD
}

type AgreementMethod = "stance" | "lexical" | "semantic";   // UI labels: Vote / Text / Semantic
type Stance = "support" | "oppose" | "conditional" | "abstain";

interface ApprovalAcceptedResponse {
  thread_id: string;
  status: "resuming";
  action: "approve" | "override" | "add_round";
}

interface DebateModesResponse {
  default_mode: "quick" | "standard" | "thorough";
  presets: Record<string, { max_rounds: number; consensus_threshold: number; skip_critique_phase: boolean; min_rounds: number }>;
  default_agreement_method?: AgreementMethod;  // pre-selected in the Agreement selector
  semantic_available?: boolean;                // false → the Semantic option is greyed out
}

interface AsyncDebateStartResponse {
  thread_id: string;
  status: string;
  stream_url: string;
}

interface ErrorResponse {
  error: string;
  detail?: string;
}
```

### History

```ts
interface HistoryItem {
  thread_id: string;
  user_query: string;
  created_at: string;        // ISO 8601
  status: string;
  total_rounds: number;
  agreement_score: number;
  termination_reason: string;
  use_knowledge_base?: boolean;
  enable_agent_memory?: boolean;
}

interface HistoryListResponse {
  items: HistoryItem[];
  total: number;
  page: number;
  limit: number;
}
```

### Extended Type Definitions

The following interfaces support the platform's extended features — templates, domain packs, knowledge management, agent memory, simulation, evaluation, analytics, and LLM settings.

```ts
// LLM provider switching
type LLMProvider = "groq" | "openai" | "anthropic" | "gemini";

interface LLMSettingsResponse {
  provider: LLMProvider;
  model: string;
  available_models: Record<LLMProvider, string[]>;
  using_custom_key: boolean;
  server_keys: Record<LLMProvider, boolean>;   // providers with a key on the server
  admin_token_required: boolean;               // POST /llm-settings needs X-Admin-Token
}

interface LLMSettingsUpdate {
  provider: LLMProvider;
  model: string;
  api_key?: string;   // Optional when the server has a key for the provider
}

// Canonical model list per provider (mirrors backend PROVIDER_MODELS, June 2026)
const PROVIDER_MODELS: Record<LLMProvider, string[]> = {
  groq: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "moonshotai/kimi-k2-instruct-0905", "qwen/qwen3-32b"],
  openai: ["gpt-5.5", "gpt-5.5-pro", "gpt-5.4-mini"],
  anthropic: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5", "claude-fable-5"],
  gemini: ["gemini-3.5-flash", "gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
};

// Debate template
type TemplateCategory = "Business" | "Technology" | "Strategy" | "Personal" | "Finance";

interface DebateTemplate {
  id: string;
  title: string;
  category: TemplateCategory;
  icon: string;
  query: string;
  mode: DebateMode;
  tags: string[];
}

// Domain pack
interface DomainPack {
  id: string;
  name: string;
  description: string;
  icon: string;
  agents: string[];
  paired_template_categories: string[];
  domain_focus: string;
}

// Knowledge document
interface KnowledgeDocument {
  name: string;
  chunks: number;
}

// Agent configuration response
interface AgentConfigResponse {
  name: string;
  role: string;
  icon: string;
  enabled: boolean;
  model_provider: string | null;
  model_name: string | null;
}

// Simulation job (background)
interface SimulationJob {
  job_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  result: SimulationResult | null;
  error: string | null;
}

// Paused-again status from the blocking /resume (HITL)
interface ApprovalStatusResponse {
  thread_id: string;
  status: DebateStatus;
  current_round: number;
  total_rounds: number;
}

// Simulation result
interface SimulationResult {
  query: string;
  runs: number;
  runs_completed: number;          // successful runs (≤ runs)
  decisions: FinalDecision[];
  consistency_score: number;
  confidence_variance: number;
  avg_agreement_score: number;
  stable_risk_flags: string[];
  stability_rating: "High" | "Medium" | "Low";
}

// Evaluation result (P4)
interface EvaluationResult {
  thread_id: string;
  completeness: number;
  consistency: number;
  actionability: number;
  risk_awareness: number;
  overall: number;
  reasoning: string;
  evaluated_at: string;
}

// Analytics
interface AnalyticsOverview {
  total_debates: number;
  avg_rounds: number;
  avg_rounds_to_consensus: number | null;   // consensus debates only
  avg_agreement_score: number;
  debates_by_termination: Record<string, number>;
  debates_per_day: { date: string; count: number }[];
  trend_days: number;                        // days covered by debates_per_day
}

interface AgentStats {
  avg_confidence: number;
  avg_critique_severity_given: Record<string, number>;
  avg_contribution_score: number;
}

interface AnalyticsAgents {
  agents: Record<string, AgentStats>;
  // How alike two agents' final positions were (0–1); null if they never debated together
  agreement_matrix: Record<string, Record<string, number | null>>;
}

interface AnalyticsConvergence {
  avg_agreement_by_round: number[];
  mode_breakdown: Record<string, number>;
  domain_pack_breakdown: Record<string, number>;
}

interface AnalyticsQuality {
  evaluated_count: number;
  avg_quality_score: number | null;
  scores_by_template: Record<string, number>;
  scores_by_mode: Record<string, number>;
  scores_by_domain_pack: Record<string, number>;
  best_performing_templates: string[];
  worst_performing_templates: string[];
}
```

### SSE Event Types

**14** event interfaces mirror the backend's events:

```ts
interface DebateStartedEvent    { type: "debate_started"; thread_id: string; user_query: string; max_rounds: number; agents?: string[]; }
interface RoundStartedEvent     { type: "round_started"; round_number: number; max_rounds: number; }
interface PhaseStartedEvent     { type: "phase_started"; round_number: number; phase: DebatePhase; }
interface AgentOutputEvent      { type: "agent_output"; round_number: number; phase: DebatePhase; agent_name: string; position: string; reasoning: string; confidence_score: number; assumptions: string[]; veto?: boolean; veto_reason?: string | null; stance?: Stance | null; }
interface CritiqueCompletedEvent { type: "critique_completed"; round_number: number; critic_agent: string; target_agent: string; severity: "low"|"medium"|"high"|"critical"; critique_points: string[]; confidence_score: number; }
interface SynthesisEvent        { type: "synthesis"; round_number: number; agreement_score: number; summary: string; agreement_areas: string[]; disagreement_areas: string[]; confidence_agreement_score?: number; position_agreement_score?: number; semantic_agreement_score?: number | null; stance_agreement_score?: number | null; stance_tally?: Record<string, number>; agreement_method_used?: AgreementMethod; leading_proposal?: string | null; }
interface DebateCompletedEvent  { type: "debate_completed"; thread_id: string; termination_reason: string; total_rounds: number; agreement_score: number; }
interface FinalDecisionEvent    extends FinalDecision { type: "final_decision"; }
interface ApprovalRequiredEvent { type: "approval_required"; round_number: number; agreement_score: number; termination_reason: string; synthesis_summary: string; options: string[]; }
interface ToolCalledEvent       { type: "tool_called"; agent_name: string; tool_name: string; input: string; output_snippet: string; }
interface AgentTimeoutEvent     { type: "agent_timeout"; round_number: number; phase: DebatePhase; agent_name: string; }
interface CancelledEvent        { type: "cancelled"; thread_id: string; detail?: string; }
interface DebateResumedEvent    { type: "debate_resumed"; thread_id: string; }
interface ErrorEvent            { type: "error"; error?: string; error_type?: string; detail?: string; }
```

`DebateSSEEvent` is their union. `synthesis` carries the measured agreement only — the moderator's continue/stop opinion is not sent (the convergence gate decides). `ping` keep-alives are consumed inside `connectToStream()`.

---

## Agent Metadata (UI-Only)

Display metadata lives in two constants. The five core agents are in `AGENT_META` (keyed by the `AgentName` union); the four domain agents are in a separate `DOMAIN_AGENT_META` (keyed by their registry names, no spaces) so the status strip and agent cards can render them when a domain pack is active.

```ts
type AgentName = "Analyst" | "Risk" | "Strategy" | "Ethics" | "Moderator";

interface AgentMeta {
  name: AgentName;
  color: string;        // Primary colour hex
  lightColor: string;   // Light background colour hex
  icon: string;         // Emoji icon
  role: string;         // Short role description
}
```

**Core Agents (`AGENT_META`)**

| Agent | Colour | Icon | Role |
|---|---|---|---|
| Analyst | `#3B82F6` (Blue) | 📊 | Objective data analyst |
| Risk | `#EF4444` (Red) | ⚠️ | Adversarial risk assessor |
| Strategy | `#22C55E` (Green) | 🎯 | Actionable strategy proposer |
| Ethics | `#A855F7` (Purple) | ⚖️ | Ethics and compliance guardian |
| Moderator | `#EAB308` (Yellow) | 🏛️ | Neutral synthesizer |

**Domain Agents (`DOMAIN_AGENT_META`, keyed without spaces)**

| Key | Colour | Icon | Role |
|---|---|---|---|
| `FinancialEthics` | `#F59E0B` (Amber) | 💰 | Financial ethics & ESG |
| `Security` | `#6366F1` (Indigo) | 🔒 | Cybersecurity & ops risk |
| `Compliance` | `#0891B2` (Cyan) | 📋 | Regulatory compliance |
| `PatientSafety` | `#EC4899` (Pink) | 🏥 | Patient safety & clinical risk |

This metadata is consumed by `AgentCard`, `AgentAvatar`, and `CritiqueView` to colour-code agent outputs and critiques by agent identity.

---

## Error Handling Pattern

Errors follow a consistent pattern across pages:

```
API call
  ├─ Success → update state with response data
  └─ Failure
      ├─ ApiError with status 404 → user-friendly "not found" message
      ├─ ApiError with status 409 → conflict message from the body (e.g. still running, not paused)
      ├─ ApiError with status 401/403 → admin token missing/wrong or admin actions disabled
      ├─ ApiError with other status → generic message from error body
      └─ Non-ApiError (network failure) → "An unexpected error occurred" / Error.message
```

Error messages are displayed in styled red banners with contextual recovery actions (e.g., "Back to Home" button).

---

## Backend Schema Sync

The comment header in `types.ts` lists the corresponding backend files:

```
backend/app/schemas/agent_response.py
backend/app/schemas/state.py
backend/app/schemas/final_decision.py
backend/app/schemas/api_models.py
```

The SSE event types are defined by the backend's orchestrator event emission (in `nodes.py` and `debate_graph.py`). The `HistoryItem` and `HistoryListResponse` types correspond to the backend's history API response models. When backend schemas change, the frontend types must be updated manually to maintain type parity.
