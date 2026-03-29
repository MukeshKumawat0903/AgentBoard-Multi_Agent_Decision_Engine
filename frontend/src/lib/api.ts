/**
 * API client for the AgentBoard backend.
 *
 * All functions throw on non-2xx responses with the ErrorResponse body.
 */

import type {
  ApprovalStatusResponse,
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
  DomainPack,
  EvaluationResult,
  FinalDecision,
  HistoryListResponse,
  KnowledgeDocument,
  LLMSettingsResponse,
  LLMSettingsUpdate,
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
/* Generic fetcher                                                     */
/* ------------------------------------------------------------------ */

class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(`API error ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T | null> {
  const url = `${API_BASE}${path}`;
  try {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...init,
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
  "error",
] as const;

/**
 * Connect to the SSE stream for a debate thread with automatic reconnection.
 *
 * - Exponential backoff: 1 s → 2 s → 4 s → 8 s → 16 s → 30 s max.
 * - Tracks lastEventId and passes it via query param on reconnect.
 * - Max 10 reconnect attempts, then fires onError and stops.
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
    resetHeartbeat(eventSource);

    for (const eventType of SSE_EVENTS) {
      eventSource.addEventListener(eventType, (e: MessageEvent) => {
        // Reset backoff on a successful message
        attempts = 0;
        resetHeartbeat(eventSource);
        // Track SSE id for reconnection
        if (e.lastEventId) lastEventId = e.lastEventId;
        try {
          const data = JSON.parse(e.data) as DebateSSEEvent;
          handlers.onEvent(data);
          if (eventType === "final_decision") {
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

    controller.signal.addEventListener("abort", () => {
      if (heartbeatTimer !== null) clearTimeout(heartbeatTimer);
      eventSource.close();
      if (retryTimeout !== null) clearTimeout(retryTimeout);
    });
  }

  connect();
  return controller;
}

/* ------------------------------------------------------------------ */
/* History                                                             */
/* ------------------------------------------------------------------ */

export async function getHistory(
  params: { page?: number; limit?: number; q?: string } = {},
): Promise<HistoryListResponse> {
  const search = new URLSearchParams();
  if (params.page) search.set("page", String(params.page));
  if (params.limit) search.set("limit", String(params.limit));
  if (params.q) search.set("q", params.q);
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
  return requireResult(apiFetch(`/knowledge/documents/${encodeURIComponent(docName)}`, { method: "DELETE" }));
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
  return requireResult(apiFetch(`/memory/${encodeURIComponent(agentName)}`, { method: "DELETE" }));
}

/* ------------------------------------------------------------------ */
/* P3.4 – Domain packs                                                */
/* ------------------------------------------------------------------ */

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
): Promise<FinalDecision | ApprovalStatusResponse> {
  const params = new URLSearchParams({ action, feedback });
  return requireResult(apiFetch<FinalDecision | ApprovalStatusResponse>(`/debate/${threadId}/approve?${params}`, { method: "POST" }));
}

/* ------------------------------------------------------------------ */
/* P4.2 – Simulation                                                  */
/* ------------------------------------------------------------------ */

export async function runSimulation(params: {
  query: string;
  runs?: number;
  max_rounds?: number;
  mode?: string;
}): Promise<SimulationResult> {
  const qs = new URLSearchParams({ query: params.query });
  if (params.runs) qs.set("runs", String(params.runs));
  if (params.max_rounds) qs.set("max_rounds", String(params.max_rounds));
  if (params.mode) qs.set("mode", params.mode);
  return requireResult(apiFetch<SimulationResult>(`/debate/simulate?${qs}`, { method: "POST" }));
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

export async function getAnalyticsOverview(): Promise<AnalyticsOverview> {
  return requireResult(apiFetch<AnalyticsOverview>("/analytics/overview"));
}

export async function getAnalyticsAgents(): Promise<AnalyticsAgents> {
  return requireResult(apiFetch<AnalyticsAgents>("/analytics/agents"));
}

export async function getAnalyticsConvergence(): Promise<AnalyticsConvergence> {
  return requireResult(apiFetch<AnalyticsConvergence>("/analytics/convergence"));
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
    }),
  );
}

export async function getAnalyticsQuality(): Promise<AnalyticsQuality> {
  return requireResult(apiFetch<AnalyticsQuality>("/analytics/quality"));
}

/* ------------------------------------------------------------------ */
/* Export                                                              */
/* ------------------------------------------------------------------ */

export async function exportDecision(
  threadId: string,
  format: "markdown" | "pdf",
): Promise<Blob> {
  const url = `${API_BASE}/decision/${encodeURIComponent(threadId)}/export?format=${format}`;
  const res = await fetch(url);
  const json = res.headers.get("content-type")?.includes("application/json")
    ? await res.json().catch(() => null)
    : null;
  if (!res.ok) throw new ApiError(res.status, json);
  return res.blob();
}
