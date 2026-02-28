/**
 * API client for the AgentBoard backend.
 *
 * All functions throw on non-2xx responses with the ErrorResponse body.
 */

import type {
  DebateStartRequest,
  DebateStatusResponse,
  FinalDecision,
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
/* Public API functions                                                */
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

/**
 * Check backend health.
 */
export async function healthCheck(): Promise<{
  status: string;
  version: string;
  groq_configured: boolean;
}> {
  return apiFetch("/health");
}

export { ApiError };
