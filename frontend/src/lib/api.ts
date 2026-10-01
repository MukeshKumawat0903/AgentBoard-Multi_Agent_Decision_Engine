/**
 * API client for the AgentBoard backend.
 *
 * All functions throw on non-2xx responses with the ErrorResponse body.
 */

import type {
  ApprovalAcceptedResponse,
  AgentConfigResponse,
  AnalyticsAgents,
  AnalyticsConvergence,
  AnalyticsOverview,
  AnalyticsQuality,
  AsyncDebateStartResponse,
  DebateSSEEvent,
  DebateStartRequest,
  DebateStatusResponse,
  DebateTemplate,
  DebateModesResponse,
  DomainPack,
  EvaluationResult,
  FinalDecision,
  HistoryListResponse,
  KnowledgeDocument,
  LLMSettingsResponse,
  LLMSettingsUpdate,
  SimulationJob,
  SimulationResult,
} from "./types";

// Use the Next.js proxy path by default (/backend → proxied to localhost:8000).
// Set NEXT_PUBLIC_API_URL in .env.local to override (e.g. for direct access).
const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "/backend";

/**
 * Build an absolute URL from a path, handling both absolute and relative API_BASE.
 * `new URL(path)` requires an absolute base, so we prepend window.location.origin
 * when API_BASE is a relative path (e.g. "/backend").
 */
function toAbsoluteURL(path: string): URL {
  if (API_BASE.startsWith("http://") || API_BASE.startsWith("https://")) {
    return new URL(path);
  }
  // Relative base — resolve against the current page origin (browser only)
  return new URL(path, window.location.origin);
}

/* ------------------------------------------------------------------ */
/* Admin token (deployment-wide actions)                               */
/* ------------------------------------------------------------------ */

const ADMIN_TOKEN_KEY = "agentboard_admin_token";

/** Admin token for this browser tab (sessionStorage: gone when the tab closes). */
export function getAdminToken(): string {
  try {
    return sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
    else sessionStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    // sessionStorage unavailable — the token just isn't remembered
  }
}

function adminHeaders(): Record<string, string> {
  const token = getAdminToken();
  return token ? { "X-Admin-Token": token } : {};
}

/* ------------------------------------------------------------------ */
/* Generic fetcher                                                     */
/* ------------------------------------------------------------------ */

/** Messages for the backend's LLM-failure codes (body.error), which come back as
 *  502/503/429 even though the backend itself is up and answered. */
const LLM_ERROR_MESSAGES: Record<string, string> = {
  llm_response_error: "The AI model returned an invalid response. Please try again.",
  llm_connection_error: "Could not reach the AI provider. Please try again shortly.",
  llm_rate_limit: "The AI provider is rate-limiting requests. Please wait a moment and try again.",
};

/**
 * Pull a human-readable message out of the error bodies the backend produces:
 * `{detail: "text"}`, `{detail: {error, detail}}` (ErrorResponse), FastAPI's
 * validation `{detail: [{msg}, …]}`, or `{error: "text"}` (rate limiter).
 */
export function extractErrorMessage(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const { detail, error } = body as Record<string, unknown>;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item ? String((item as Record<string, unknown>).msg) : "",
      )
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  if (detail && typeof detail === "object") {
    const inner = detail as Record<string, unknown>;
    if (typeof inner.detail === "string" && inner.detail) return inner.detail;
    if (typeof inner.error === "string" && inner.error) return inner.error;
  }
  if (typeof error === "string" && error) return error;
  return null;
}

class ApiError extends Error {
  status: number;
  body: unknown;
  /** Machine-readable error code from the body, when the backend sent one. */
  code: string | null;

  constructor(status: number, body: unknown) {
    const record = body && typeof body === "object" ? (body as Record<string, unknown>) : null;
    const nested =
      record?.detail && typeof record.detail === "object" && !Array.isArray(record.detail)
        ? (record.detail as Record<string, unknown>)
        : null;
    const code =
      (typeof record?.error === "string" ? record.error : null) ??
      (typeof nested?.error === "string" ? nested.error : null);

    let message: string;
    if (status >= 500 && (body === null || body === undefined)) {
      // The Next.js proxy couldn't reach the backend at all (no JSON body).
      message = "Backend unreachable. Is the server running?";
    } else if (code && code in LLM_ERROR_MESSAGES) {
      message = LLM_ERROR_MESSAGES[code];
    } else if (status === 502 || status === 503 || status === 504) {
      message = "Backend unavailable — please try again shortly.";
    } else {
      message = extractErrorMessage(body) ?? `API error ${status}`;
    }
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.code = code;
  }
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T | null> {
  const url = `${API_BASE}${path}`;
  try {
    // NB10: don't force Content-Type when body is FormData — browser sets multipart boundary
    const defaultHeaders: Record<string, string> =
      init?.body instanceof FormData ? {} : { "Content-Type": "application/json" };
    const { headers, ...rest } = init ?? {};
    const res = await fetch(url, {
      ...rest,
      // Merge (not replace) so callers can add headers such as X-Admin-Token.
      headers: { ...defaultHeaders, ...(headers as Record<string, string> | undefined) },
    });

    const json = await res.json().catch(() => null);

    if (!res.ok) {
      throw new ApiError(res.status, json);
    }

    return json as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return null; // intentional cancellation — not an error
    }
    throw err;
  }
}

async function requireResult<T>(promise: Promise<T | null>): Promise<T> {
  const result = await promise;
  if (result === null) {
    throw new Error("Request was aborted.");
  }
  return result;
}

/* ------------------------------------------------------------------ */
/* Debate – synchronous (V1)                                          */
/* ------------------------------------------------------------------ */

/**
 * Start a new multi-agent debate (synchronous V1).
 * Blocks until the debate completes and returns the FinalDecision.
 */
export async function startDebate(
  request: DebateStartRequest,
  signal?: AbortSignal,
): Promise<FinalDecision | null> {
  return apiFetch<FinalDecision>("/debate/start", {
    method: "POST",
    body: JSON.stringify(request),
    signal,
  });
}

/**
 * Get the current status and round history of a debate session.
 */
export async function getDebateStatus(
  threadId: string,
  signal?: AbortSignal,
): Promise<DebateStatusResponse | null> {
  return apiFetch<DebateStatusResponse>(`/debate/${threadId}`, { signal });
}

/**
 * Get the final decision of a completed debate session.
 */
export async function getDecision(
  threadId: string,
  signal?: AbortSignal,
): Promise<FinalDecision | null> {
  return apiFetch<FinalDecision>(`/decision/${threadId}`, { signal });
}

/* ------------------------------------------------------------------ */
/* Debate – async / streaming (V2)                                    */
/* ------------------------------------------------------------------ */

/**
 * Start a debate in the background.
 * Returns immediately with a thread_id and stream_url.
 */
export async function startDebateAsync(
  request: DebateStartRequest,
  signal?: AbortSignal,
): Promise<AsyncDebateStartResponse | null> {
  return apiFetch<AsyncDebateStartResponse>("/debate/start-async", {
    method: "POST",
    body: JSON.stringify(request),
    signal,
  });
}

export interface StreamHandlers {
  onEvent: (event: DebateSSEEvent) => void;
  onError?: (error: Event) => void;
  onDone?: () => void;
  onStatusChange?: (status: "connected" | "reconnecting" | "disconnected") => void;
}

/**
 * Cancel an in-flight async debate so the backend stops making LLM calls.
 * Returns null if the request was aborted. Throws ApiError on 404/409.
 */
/**
 * Resume a failed or interrupted debate from its last checkpoint. Returns at
 * once (202); the continuation streams over the debate's SSE stream.
 */
export async function resumeDebateAsync(
  threadId: string,
): Promise<{ thread_id: string; status: "resuming" }> {
  return requireResult(
    apiFetch(`/debate/${encodeURIComponent(threadId)}/resume-async`, { method: "POST" }),
  );
}

export async function cancelDebate(
  threadId: string,
): Promise<{ thread_id: string; status: string } | null> {
  return apiFetch(`/debate/${encodeURIComponent(threadId)}/cancel`, { method: "POST" });
}

const SSE_EVENTS = [
  "debate_started",
  "round_started",
  "phase_started",
  "agent_output",
  "critique_completed",
  "synthesis",
  "debate_completed",
  "final_decision",
  "approval_required",
  "tool_called",
  "agent_timeout",  // B6: backend emits this when an agent call times out
  "cancelled",      // terminal event when a debate is cancelled
  "debate_resumed", // a failed/interrupted debate continues from its checkpoint
  "error",
] as const;

/**
 * Connect to the SSE stream for a debate thread with automatic reconnection.
 *
 * - Exponential backoff: 1 s → 2 s → 4 s → 8 s → 16 s → 30 s max.
 * - Tracks lastEventId and passes it via query param on reconnect.
 * - Max 10 reconnect attempts, then fires onError and stops.
 * - The server sends a `ping` event every 20 s on a live connection; pings keep
 *   the stale-connection timer from firing (e.g. while paused for HITL review)
 *   and are not forwarded to `onEvent`.
 * - Returns an AbortController so callers can stop reconnection.
 */
export function connectToStream(
  threadId: string,
  handlers: StreamHandlers,
): AbortController {
  const controller = new AbortController();
  let attempts = 0;
  let lastEventId: string | null = null;
  let retryTimeout: ReturnType<typeof setTimeout> | null = null;
  // Heartbeat: if no SSE event arrives within 60 s we treat the connection as stale
  // and force a reconnect so the UI doesn't hang silently.
  const HEARTBEAT_MS = 60_000;
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  let currentSource: EventSource | null = null;

  // Registered once (not per reconnect) so listeners don't pile up.
  controller.signal.addEventListener("abort", () => {
    if (heartbeatTimer !== null) clearTimeout(heartbeatTimer);
    currentSource?.close();
    if (retryTimeout !== null) clearTimeout(retryTimeout);
  });

  function resetHeartbeat(es: EventSource) {
    if (heartbeatTimer !== null) clearTimeout(heartbeatTimer);
    heartbeatTimer = setTimeout(() => {
      es.close();
      // Trigger the onerror reconnect path by synthesising a close
      if (!controller.signal.aborted) {
        attempts += 1;
        if (attempts > 10) {
          handlers.onStatusChange?.("disconnected");
          handlers.onError?.(new Event("max_reconnects"));
          return;
        }
        const delay = Math.min(1000 * Math.pow(2, attempts - 1), 30_000);
        handlers.onStatusChange?.("reconnecting");
        retryTimeout = setTimeout(() => {
          if (!controller.signal.aborted) connect();
        }, delay);
      }
    }, HEARTBEAT_MS);
  }

  function connect() {
    if (controller.signal.aborted) return;

    const url = toAbsoluteURL(`${API_BASE}/debate/${threadId}/stream`);
    if (lastEventId !== null) {
      url.searchParams.set("last_event_id", lastEventId);
    }

    handlers.onStatusChange?.(attempts === 0 ? "connected" : "reconnecting");
    const eventSource = new EventSource(url.toString());
    currentSource = eventSource;
    resetHeartbeat(eventSource);
    // A reconnect that succeeds must clear the "reconnecting" status.
    eventSource.onopen = () => handlers.onStatusChange?.("connected");

    // Server keep-alive: proves the connection is alive, carries no data.
    eventSource.addEventListener("ping", () => {
      attempts = 0;
      resetHeartbeat(eventSource);
    });

    for (const eventType of SSE_EVENTS) {
      eventSource.addEventListener(eventType, (e: MessageEvent) => {
        // The browser's own connection-failure event is also named "error" but
        // carries no data; only real server messages may reset the backoff.
        if (typeof e.data !== "string") return;
        // Reset backoff on a successful message
        attempts = 0;
        resetHeartbeat(eventSource);
        // Track SSE id for reconnection
        if (e.lastEventId) lastEventId = e.lastEventId;
        try {
          const data = JSON.parse(e.data) as DebateSSEEvent;
          handlers.onEvent(data);
          // "cancelled"/"error" are terminal like "final_decision" — close so
          // the reconnect loop is not triggered by the backend closing the
          // stream (an unhandled "error" event would otherwise reconnect and
          // re-replay the entire history forever).
          if (eventType === "final_decision" || eventType === "cancelled" || eventType === "error") {
            if (heartbeatTimer !== null) clearTimeout(heartbeatTimer);
            handlers.onStatusChange?.("disconnected");
            handlers.onDone?.();
            eventSource.close();
          }
        } catch {
          // ignore parse errors — malformed events should not crash the viewer
        }
      });
    }

    eventSource.onerror = () => {
      if (heartbeatTimer !== null) clearTimeout(heartbeatTimer);
      eventSource.close();
      if (controller.signal.aborted) return;

      attempts += 1;
      if (attempts > 10) {
        handlers.onStatusChange?.("disconnected");
        handlers.onError?.(new Event("max_reconnects"));
        return;
      }

      const delay = Math.min(1000 * Math.pow(2, attempts - 1), 30_000);
      handlers.onStatusChange?.("reconnecting");
      retryTimeout = setTimeout(() => {
        if (!controller.signal.aborted) connect();
      }, delay);
    };
  }

  connect();
  return controller;
}

/* ------------------------------------------------------------------ */
/* History                                                             */
/* ------------------------------------------------------------------ */

export type HistorySort = "newest" | "oldest" | "highest_agreement";
export type HistoryTerminationReason = "consensus_reached" | "human_override" | "max_rounds_reached";

export async function getHistory(
  params: {
    page?: number;
    limit?: number;
    q?: string;
    sort?: HistorySort;
    termination_reason?: HistoryTerminationReason;
  } = {},
): Promise<HistoryListResponse> {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));
  if (params.q) search.set("q", params.q);
  if (params.sort) search.set("sort", params.sort);
  if (params.termination_reason) search.set("termination_reason", params.termination_reason);
  const qs = search.toString();
  return requireResult(apiFetch<HistoryListResponse>(`/history${qs ? `?${qs}` : ""}`));
}

export async function getHistoryItem(
  threadId: string,
): Promise<FinalDecision> {
  return requireResult(apiFetch<FinalDecision>(`/history/${threadId}`));
}

/* ------------------------------------------------------------------ */
/* Health                                                              */
/* ------------------------------------------------------------------ */

export async function healthCheck(): Promise<{
  status: string;
  version: string;
  // Provider debates currently use, and whether it has an API key
  llm: { provider: string; model: string; configured: boolean };
  groq_configured: boolean;
}> {
  return requireResult(apiFetch("/health"));
}

/* ------------------------------------------------------------------ */
/* Templates                                                           */
/* ------------------------------------------------------------------ */

export async function getAgents(): Promise<AgentConfigResponse[]> {
  return requireResult(apiFetch<AgentConfigResponse[]>("/agents"));
}

export async function getTemplates(params: { category?: string; q?: string } = {}): Promise<DebateTemplate[]> {
  const search = new URLSearchParams();
  if (params.category) search.set("category", params.category);
  if (params.q) search.set("q", params.q);
  const qs = search.toString();
  return requireResult(apiFetch<DebateTemplate[]>(`/templates${qs ? `?${qs}` : ""}`));
}

export { ApiError };

/* ------------------------------------------------------------------ */
/* P3.1 – Knowledge base                                              */
/* ------------------------------------------------------------------ */

export async function uploadKnowledgeDocument(file: File): Promise<{ filename: string; chunks_indexed: number }> {
  const form = new FormData();
  form.append("file", file);
  const url = `${API_BASE}/knowledge/upload`;
  const res = await fetch(url, { method: "POST", body: form });
  const json = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, json);
  return json;
}

export async function listKnowledgeDocuments(): Promise<KnowledgeDocument[]> {
  return requireResult(apiFetch<KnowledgeDocument[]>("/knowledge/documents"));
}

export async function deleteKnowledgeDocument(docName: string): Promise<{ doc_name: string; chunks_deleted: number }> {
  return requireResult(
    apiFetch(`/knowledge/documents/${encodeURIComponent(docName)}`, { method: "DELETE", headers: adminHeaders() }),
  );
}

/* ------------------------------------------------------------------ */
/* P3.3 – Agent memory                                                */
/* ------------------------------------------------------------------ */

export interface MemoryEntry {
  memory_id: number;
  agent_name: string;
  debate_id: string;
  summary: string;
  lesson_learned: string;
  created_at: string;
}

export async function getAgentMemory(agentName: string, limit = 20): Promise<MemoryEntry[]> {
  return requireResult(apiFetch<MemoryEntry[]>(`/memory/${encodeURIComponent(agentName)}?limit=${limit}`));
}

export async function clearAgentMemory(agentName: string): Promise<{ agent_name: string; deleted: number }> {
  return requireResult(
    apiFetch(`/memory/${encodeURIComponent(agentName)}`, { method: "DELETE", headers: adminHeaders() }),
  );
}

/* ------------------------------------------------------------------ */
/* P3.4 – Domain packs                                                */
/* ------------------------------------------------------------------ */

export async function getDebateModes(): Promise<DebateModesResponse> {
  return requireResult(apiFetch<DebateModesResponse>("/debate-modes"));
}

export async function getDomainPacks(): Promise<DomainPack[]> {
  return requireResult(apiFetch<DomainPack[]>("/domain-packs"));
}

/* ------------------------------------------------------------------ */
/* P4.1 – HITL approval                                               */
/* ------------------------------------------------------------------ */

export async function approveDebate(
  threadId: string,
  action: "approve" | "override" | "add_round",
  feedback = "",
): Promise<ApprovalAcceptedResponse> {
  return requireResult(
    apiFetch<ApprovalAcceptedResponse>(
      `/debate/${encodeURIComponent(threadId)}/approve`,
      { method: "POST", body: JSON.stringify({ action, feedback }) },
    ),
  );
}

/* ------------------------------------------------------------------ */
/* P4.2 – Simulation                                                  */
/* ------------------------------------------------------------------ */

type SimulationParams = Parameters<typeof runSimulation>[0];

/** Start a simulation as a background job; poll it with getSimulationJob(). */
export async function startSimulation(params: SimulationParams): Promise<SimulationJob> {
  return requireResult(
    apiFetch<SimulationJob>("/debate/simulate-async", {
      method: "POST",
      body: JSON.stringify(params),
    }),
  );
}

export async function getSimulationJob(jobId: string): Promise<SimulationJob> {
  return requireResult(apiFetch<SimulationJob>(`/debate/simulate/${encodeURIComponent(jobId)}`));
}

export async function cancelSimulationJob(jobId: string): Promise<SimulationJob> {
  return requireResult(
    apiFetch<SimulationJob>(`/debate/simulate/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  );
}

/** Synchronous variant: holds the request open for every run (prefer startSimulation). */
export async function runSimulation(params: {
  query: string;
  runs?: number;
  max_rounds?: number;
  mode?: string;
  agents?: string[];
  domain_pack?: string | null;
  use_knowledge_base?: boolean;
  enable_agent_memory?: boolean;
}): Promise<SimulationResult> {
  return requireResult(
    apiFetch<SimulationResult>("/debate/simulate", {
      method: "POST",
      body: JSON.stringify(params),
    }),
  );
}

/* ------------------------------------------------------------------ */
/* P4.3 – Decision evaluation                                         */
/* ------------------------------------------------------------------ */

export async function evaluateDecision(threadId: string): Promise<EvaluationResult> {
  return requireResult(apiFetch<EvaluationResult>(`/decision/${threadId}/evaluate`, { method: "POST" }));
}

/* ------------------------------------------------------------------ */
/* Phase 5 — Analytics & Evaluation                                   */
/* ------------------------------------------------------------------ */

function daysQuery(days?: number): string {
  return days && days > 0 ? `?days=${days}` : "";
}

export async function getAnalyticsOverview(days?: number): Promise<AnalyticsOverview> {
  return requireResult(apiFetch<AnalyticsOverview>(`/analytics/overview${daysQuery(days)}`));
}

export async function getAnalyticsAgents(days?: number): Promise<AnalyticsAgents> {
  return requireResult(apiFetch<AnalyticsAgents>(`/analytics/agents${daysQuery(days)}`));
}

export async function getAnalyticsConvergence(days?: number): Promise<AnalyticsConvergence> {
  return requireResult(apiFetch<AnalyticsConvergence>(`/analytics/convergence${daysQuery(days)}`));
}

/* ------------------------------------------------------------------ */
/* LLM provider settings                                              */
/* ------------------------------------------------------------------ */

export async function getLLMSettings(): Promise<LLMSettingsResponse> {
  return requireResult(apiFetch<LLMSettingsResponse>("/llm-settings"));
}

export async function setLLMSettings(
  update: LLMSettingsUpdate,
): Promise<LLMSettingsResponse> {
  return requireResult(
    apiFetch<LLMSettingsResponse>("/llm-settings", {
      method: "POST",
      body: JSON.stringify(update),
      headers: adminHeaders(),
    }),
  );
}

export async function getAnalyticsQuality(days?: number): Promise<AnalyticsQuality> {
  return requireResult(apiFetch<AnalyticsQuality>(`/analytics/quality${daysQuery(days)}`));
}

/* ------------------------------------------------------------------ */
/* Export                                                              */
/* ------------------------------------------------------------------ */

export async function exportDecision(
  threadId: string,
  format: "markdown" | "pdf" | "json",  // FI4: added json
): Promise<Blob> {
  const url = `${API_BASE}/decision/${encodeURIComponent(threadId)}/export?format=${format}`;
  const res = await fetch(url);
  const jsonBody = res.headers.get("content-type")?.includes("application/json")
    ? await res.json().catch(() => null)
    : null;
  if (!res.ok) throw new ApiError(res.status, jsonBody);
  return res.blob();
}
