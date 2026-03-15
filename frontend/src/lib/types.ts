/**
 * TypeScript types mirroring the backend Pydantic schemas.
 *
 * Keep in sync with:
 *   backend/app/schemas/agent_response.py
 *   backend/app/schemas/state.py
 *   backend/app/schemas/final_decision.py
 *   backend/app/schemas/api_models.py
 */

/* ------------------------------------------------------------------ */
/* Agent & Critique responses                                          */
/* ------------------------------------------------------------------ */

export interface AgentResponse {
  agent_name: string;
  round_number: number;
  position: string;
  reasoning: string;
  assumptions: string[];
  confidence_score: number;
  timestamp: string;
}

export interface CritiqueResponse {
  critic_agent: string;
  target_agent: string;
  round_number: number;
  critique_points: string[];
  severity: "low" | "medium" | "high" | "critical";
  suggested_revision: string | null;
  confidence_score: number;
}

/* ------------------------------------------------------------------ */
/* Debate round & state                                                */
/* ------------------------------------------------------------------ */

export type DebatePhase = "proposal" | "critique" | "revision" | "convergence";

export interface DebateRound {
  round_number: number;
  phase: DebatePhase;
  agent_outputs: AgentResponse[];
  critiques: CritiqueResponse[];
}

export type DebateStatus =
  | "initialized"
  | "in_progress"
  | "converged"
  | "max_rounds_reached"
  | "error";

export interface DebateStatusResponse {
  thread_id: string;
  status: DebateStatus;
  current_round: number;
  total_rounds: number;
  agreement_score: number;
  rounds: DebateRound[];
}

/* ------------------------------------------------------------------ */
/* Final decision                                                      */
/* ------------------------------------------------------------------ */

export interface FinalDecision {
  thread_id: string;
  query?: string;
  decision: string;
  rationale_summary: string;
  confidence_score: number;
  agreement_score: number;
  risk_flags: string[];
  alternatives: string[];
  dissenting_opinions: string[];
  debate_trace: DebateRound[];
  total_rounds: number;
  termination_reason: string;
  created_at: string;
}

/* ------------------------------------------------------------------ */
/* API request / error                                                 */
/* ------------------------------------------------------------------ */

export interface DebateStartRequest {
  query: string;
  max_rounds?: number;
}

export interface AsyncDebateStartResponse {
  thread_id: string;
  status: string;
  stream_url: string;
}

export interface ErrorResponse {
  error: string;
  detail?: string;
}

/* ------------------------------------------------------------------ */
/* History                                                             */
/* ------------------------------------------------------------------ */

export interface HistoryItem {
  thread_id: string;
  user_query: string;
  created_at: string;
  status: string;
  total_rounds: number;
  agreement_score: number;
  termination_reason: string;
}

export interface HistoryListResponse {
  items: HistoryItem[];
  total: number;
  page: number;
  limit: number;
}

/* ------------------------------------------------------------------ */
/* SSE events                                                          */
/* ------------------------------------------------------------------ */

export interface DebateStartedEvent {
  type: "debate_started";
  thread_id: string;
  user_query: string;
  max_rounds: number;
}

export interface RoundStartedEvent {
  type: "round_started";
  round_number: number;
  max_rounds: number;
}

export interface PhaseStartedEvent {
  type: "phase_started";
  round_number: number;
  phase: DebatePhase;
}

export interface AgentOutputEvent {
  type: "agent_output";
  round_number: number;
  phase: DebatePhase;
  agent_name: string;
  position: string;
  reasoning: string;
  confidence_score: number;
  assumptions: string[];
}

export interface CritiqueCompletedEvent {
  type: "critique_completed";
  round_number: number;
  critic_agent: string;
  target_agent: string;
  severity: "low" | "medium" | "high" | "critical";
  critique_points: string[];
  confidence_score: number;
}

export interface SynthesisEvent {
  type: "synthesis";
  round_number: number;
  agreement_score: number;
  should_continue: boolean;
  summary: string;
  agreement_areas: string[];
  disagreement_areas: string[];
}

export interface DebateCompletedEvent {
  type: "debate_completed";
  thread_id: string;
  termination_reason: string;
  total_rounds: number;
  agreement_score: number;
}

export interface FinalDecisionEvent extends FinalDecision {
  type: "final_decision";
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type DebateSSEEvent =
  | DebateStartedEvent
  | RoundStartedEvent
  | PhaseStartedEvent
  | AgentOutputEvent
  | CritiqueCompletedEvent
  | SynthesisEvent
  | DebateCompletedEvent
  | FinalDecisionEvent
  | ErrorEvent;

/* ------------------------------------------------------------------ */
/* Agent colour / role metadata (UI-only)                              */
/* ------------------------------------------------------------------ */

export type AgentName = "Analyst" | "Risk" | "Strategy" | "Ethics" | "Moderator";

export interface AgentMeta {
  name: AgentName;
  color: string;
  lightColor: string;
  icon: string; // emoji
  role: string;
}

export const AGENT_META: Record<AgentName, AgentMeta> = {
  Analyst: {
    name: "Analyst",
    color: "#3B82F6",
    lightColor: "#DBEAFE",
    icon: "📊",
    role: "Objective data analyst",
  },
  Risk: {
    name: "Risk",
    color: "#EF4444",
    lightColor: "#FEE2E2",
    icon: "⚠️",
    role: "Adversarial risk assessor",
  },
  Strategy: {
    name: "Strategy",
    color: "#22C55E",
    lightColor: "#DCFCE7",
    icon: "🎯",
    role: "Actionable strategy proposer",
  },
  Ethics: {
    name: "Ethics",
    color: "#A855F7",
    lightColor: "#F3E8FF",
    icon: "⚖️",
    role: "Ethics and compliance guardian",
  },
  Moderator: {
    name: "Moderator",
    color: "#EAB308",
    lightColor: "#FEF9C3",
    icon: "🏛️",
    role: "Neutral synthesizer",
  },
};
