/**
 * API client for the AgentBoard backend.
 *
 * All functions throw on non-2xx responses with the ErrorResponse body.
 */

import type {
  AsyncDebateStartResponse,
  DebateSSEEvent,
  DebateStartRequest,
  DebateStatusResponse,
  FinalDecision,
  HistoryListResponse,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  init?: RequestInit,
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  const json = await res.json().catch(() => null);

  if (!res.ok) {
    throw new ApiError(res.status, json);
  }

  return json as T;
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
): Promise<FinalDecision> {
  return apiFetch<FinalDecision>("/debate/start", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/**
 * Get the current status and round history of a debate session.
 */
export async function getDebateStatus(
  threadId: string,
): Promise<DebateStatusResponse> {
  return apiFetch<DebateStatusResponse>(`/debate/${threadId}`);
}

/**
 * Get the final decision of a completed debate session.
 */
export async function getDecision(
  threadId: string,
): Promise<FinalDecision> {
  return apiFetch<FinalDecision>(`/decision/${threadId}`);
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
): Promise<AsyncDebateStartResponse> {
  return apiFetch<AsyncDebateStartResponse>("/debate/start-async", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export interface StreamHandlers {
  onEvent: (event: DebateSSEEvent) => void;
  onError?: (error: Event) => void;
  onDone?: () => void;
}

/**
 * Connect to the SSE stream for a debate thread.
 * Returns a cleanup function to close the EventSource.
 */
export function connectToStream(
  threadId: string,
  handlers: StreamHandlers,
): () => void {
  const url = `${API_BASE}/debate/${threadId}/stream`;
  const eventSource = new EventSource(url);

  const SSE_EVENTS = [
    "debate_started",
    "round_started",
    "phase_started",
    "agent_output",
    "critique_completed",
    "synthesis",
    "debate_completed",
    "final_decision",
    "error",
  ] as const;

  for (const eventType of SSE_EVENTS) {
    eventSource.addEventListener(eventType, (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as DebateSSEEvent;
        handlers.onEvent(data);
        if (eventType === "final_decision") {
          handlers.onDone?.();
          eventSource.close();
        }
      } catch {
        // ignore parse errors
      }
    });
  }

  eventSource.onerror = (e) => {
    handlers.onError?.(e);
    eventSource.close();
  };

  return () => eventSource.close();
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
  return apiFetch<HistoryListResponse>(`/history${qs ? `?${qs}` : ""}`);
}

export async function getHistoryItem(
  threadId: string,
): Promise<FinalDecision> {
  return apiFetch<FinalDecision>(`/history/${threadId}`);
}

/* ------------------------------------------------------------------ */
/* Health                                                              */
/* ------------------------------------------------------------------ */

export async function healthCheck(): Promise<{
  status: string;
  version: string;
  groq_configured: boolean;
}> {
  return apiFetch("/health");
}

export { ApiError };
