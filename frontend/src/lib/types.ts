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

export interface ToolCallRecord {
  agent_name: string;
  tool_name: string;
  input: string;
  output_snippet: string;
}

export interface DebateRound {
  round_number: number;
  phase: DebatePhase;
  agent_outputs: AgentResponse[];
  critiques: CritiqueResponse[];
  toolCalls?: ToolCallRecord[];  // accumulated during streaming (NB3)
  tool_calls?: ToolCallRecord[];  // persisted on the round (from the saved trace)
}

export type DebateStatus =
  | "initialized"
  | "in_progress"
  | "converged"
  | "max_rounds_reached"
  | "awaiting_approval"
  | "cancelled"
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

export interface MinorityReportEntry {
  agent_name: string;
  final_position: string;
  dissent_reason: string;
  confidence_score: number;
}

export interface AgentStance {
  agent: string;
  stance: string;
}

export interface StructuredDisagreement {
  topic: string;
  positions: AgentStance[];
}

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
  // P1.5 richer output fields
  minority_report?: MinorityReportEntry[];
  key_disagreements?: string[];
  structured_disagreements?: StructuredDisagreement[];
  agent_contribution_scores?: Record<string, number>;
  // Degraded-run indicators: agents absent from the final round
  degraded?: boolean;
  missing_agents?: string[];
  // Token usage + estimated cost
  token_usage?: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    by_model?: Record<string, { input_tokens?: number; output_tokens?: number; total_tokens?: number }>;
  };
  estimated_cost_usd?: number | null;
}

/* ------------------------------------------------------------------ */
/* API request / error                                                 */
/* ------------------------------------------------------------------ */

export type DebateMode = "quick" | "standard" | "thorough";

export interface DebateStartRequest {
  query: string;
  mode?: DebateMode;
  max_rounds?: number;
  consensus_threshold?: number;
  skip_critique_phase?: boolean;
  agents?: string[];
  // P3 extensions
  use_knowledge_base?: boolean;
  enable_agent_memory?: boolean;
  domain_pack?: string | null;
  supervised?: boolean;
}

export interface AgentConfigResponse {
  name: string;
  role: string;
  icon: string;
  enabled: boolean;
  model_provider: string | null;
  model_name: string | null;
}

export interface AsyncDebateStartResponse {
  thread_id: string;
  status: string;
  stream_url: string;
}

export interface ApprovalStatusResponse {
  thread_id: string;
  status: DebateStatus;
  current_round: number;
  total_rounds: number;
}

export interface ErrorResponse {
  error: string;
  detail?: string;
}

/* ------------------------------------------------------------------ */
/* Templates                                                           */
/* ------------------------------------------------------------------ */

export type TemplateCategory = "Business" | "Technology" | "Strategy" | "Personal" | "Finance";

export interface DebateTemplate {
  id: string;
  title: string;
  category: TemplateCategory;
  icon: string;
  query: string;
  mode: DebateMode;
  tags: string[];
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
  use_knowledge_base?: boolean;    // FI3: feature badge
  enable_agent_memory?: boolean;   // FI3: feature badge
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
  agents?: string[];  // participating agent names for round-1 status seeding
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

// B10 Fix: backend sends error/error_type/detail, not message
export interface ErrorEvent {
  type: "error";
  error?: string;
  error_type?: string;
  detail?: string;
}

// B6 Fix: backend emits agent_timeout when an agent call times out
export interface AgentTimeoutEvent {
  type: "agent_timeout";
  round_number: number;
  phase: DebatePhase;
  agent_name: string;
}

// P4.1 – HITL approval_required SSE event
export interface ApprovalRequiredEvent {
  type: "approval_required";
  round_number: number;
  agreement_score: number;
  termination_reason: string;
  synthesis_summary: string;
  options: string[];
}

// P3.2 – Tool called SSE event
export interface ToolCalledEvent {
  type: "tool_called";
  agent_name: string;
  tool_name: string;
  input: string;
  output_snippet: string;
}

// Terminal event emitted when a user cancels an in-flight debate
export interface CancelledEvent {
  type: "cancelled";
  thread_id: string;
  detail?: string;
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
  | ApprovalRequiredEvent
  | ToolCalledEvent
  | AgentTimeoutEvent  // B6
  | CancelledEvent
  | ErrorEvent;

/* ------------------------------------------------------------------ */
/* P3.1 – Knowledge base                                              */
/* ------------------------------------------------------------------ */

export interface KnowledgeDocument {
  name: string;
  chunks: number;
}

/* ------------------------------------------------------------------ */
/* P3.4 – Domain packs                                                */
/* ------------------------------------------------------------------ */

export interface DomainPack {
  id: string;
  name: string;
  description: string;
  icon: string;
  agents: string[];
  paired_template_categories: string[];
  domain_focus: string;
}

/* ------------------------------------------------------------------ */
/* P4.2 – Simulation                                                  */
/* ------------------------------------------------------------------ */

export interface SimulationResult {
  query: string;
  runs: number;
  runs_completed: number;  // NB4: actual successes (≤ runs)
  decisions: FinalDecision[];
  consistency_score: number;
  confidence_variance: number;
  avg_agreement_score: number;
  stable_risk_flags: string[];
  stability_rating: "High" | "Medium" | "Low";
}

/* ------------------------------------------------------------------ */
/* P4.3 – Evaluation                                                  */
/* ------------------------------------------------------------------ */

export interface EvaluationResult {
  thread_id: string;
  completeness: number;
  consistency: number;
  actionability: number;
  risk_awareness: number;
  overall: number;
  reasoning: string;
  evaluated_at: string;
}

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

// B4 Fix: metadata for domain-pack agents (FinancialEthics, Security, Compliance, PatientSafety)
// These are displayed in the status strip and agent cards when a domain pack is active.
export const DOMAIN_AGENT_META: Record<string, Omit<AgentMeta, "name"> & { name: string }> = {
  FinancialEthics: { name: "FinancialEthics", color: "#F59E0B", lightColor: "#FEF3C7", icon: "💰", role: "Financial ethics & ESG" },
  Security:        { name: "Security",        color: "#6366F1", lightColor: "#EEF2FF", icon: "🔒", role: "Cybersecurity & ops risk" },
  Compliance:      { name: "Compliance",      color: "#0891B2", lightColor: "#CFFAFE", icon: "📋", role: "Regulatory compliance" },
  PatientSafety:   { name: "PatientSafety",   color: "#EC4899", lightColor: "#FCE7F3", icon: "🏥", role: "Patient safety & clinical risk" },
};

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

/* ------------------------------------------------------------------ */
/* Phase 5 — Analytics & Evaluation                                   */
/* ------------------------------------------------------------------ */

export interface AnalyticsOverview {
  total_debates: number;
  avg_rounds_to_consensus: number;
  avg_agreement_score: number;
  debates_by_termination: Record<string, number>;
  debates_per_day: { date: string; count: number }[];
}

export interface AgentStats {
  avg_confidence: number;
  avg_critique_severity_given: Record<string, number>;
  avg_contribution_score: number;
}

export interface AnalyticsAgents {
  agents: Record<string, AgentStats>;
  agreement_matrix: Record<string, Record<string, number>>;
}

export interface AnalyticsConvergence {
  avg_agreement_by_round: number[];
  mode_breakdown: Record<string, number>;
  domain_pack_breakdown: Record<string, number>;
}

export interface AnalyticsQuality {
  evaluated_count: number;
  avg_quality_score: number | null;
  scores_by_template: Record<string, number>;
  scores_by_mode: Record<string, number>;
  scores_by_domain_pack: Record<string, number>;
  best_performing_templates: string[];
  worst_performing_templates: string[];
}

/* ------------------------------------------------------------------ */
/* LLM provider settings                                               */
/* ------------------------------------------------------------------ */

export type LLMProvider = "groq" | "openai" | "anthropic" | "gemini";

export interface LLMSettingsResponse {
  provider: LLMProvider;
  model: string;
  available_models: Record<LLMProvider, string[]>;
  using_custom_key: boolean;
}

export interface LLMSettingsUpdate {
  provider: LLMProvider;
  model: string;
  api_key?: string;
}

/** Client-side canonical model lists — kept in sync with PROVIDER_MODELS in backend.
 *  Verified against each provider's model docs (June 2026); first entry is the default. */
export const PROVIDER_MODELS: Record<LLMProvider, string[]> = {
  groq: [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "moonshotai/kimi-k2-instruct-0905",
    "qwen/qwen3-32b",
  ],
  openai: ["gpt-5.5", "gpt-5.5-pro", "gpt-5.4-mini"],
  anthropic: [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-fable-5",
  ],
  gemini: [
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
  ],
};
