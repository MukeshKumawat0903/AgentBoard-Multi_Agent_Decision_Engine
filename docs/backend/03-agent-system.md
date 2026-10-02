# Agent System

AgentBoard uses **nine AI agents (five core + four domain)**, each with a distinct role in the debate. Four core debate agents (Analyst, Risk, Strategy, Ethics) take part in every round; a fifth — the **Moderator** — summarises each round and writes the final decision. Four domain agents specialise the core agents' prompts and are used through domain packs.

A debate needs **at least two agents besides the Moderator** (validated on `DebateStartRequest` and `SimulateRequest`, and enforced by the home page roster).

---

## Agent Overview

| Agent | Role | Icon | Perspective |
|---|---|---|---|
| **Analyst** | Objective data analyst | 📊 | Facts, data, cause-and-effect (no recommendations) |
| **Risk** | Adversarial risk assessor | ⚠️ | Risks, failures, hidden assumptions (no solutions) |
| **Strategy** | Actionable strategy proposer | 🎯 | Concrete plans with alternatives and implementation steps |
| **Ethics** | Ethics & compliance guardian | 🤝 | Fairness, bias, regulation, societal impact — can **veto** |
| **Moderator** | Neutral synthesizer | 🏛️ | Per-round summary and the final decision |
| **FinancialEthics** | Fiduciary & ESG ethics | 💰 | Financial regulation, investor protection, ESG — can **veto** |
| **Security** | Cybersecurity & attack surface | 🔒 | Attack surface, supply-chain risks, OWASP, infrastructure SPOF |
| **Compliance** | Regulatory & legal compliance | 📋 | Regulatory compliance, legal exposure, cross-jurisdiction analysis |
| **PatientSafety** | Clinical risk & patient welfare | 🏥 | Clinical risk, patient welfare, medical ethics — can **veto** |

---

## BaseAgent — Abstract Foundation

All agents inherit from `BaseAgent` (`app/agents/base_agent.py`).

### Lifecycle Methods

```
BaseAgent
  ├── run(state)               → AgentResponse     # Fresh proposal
  ├── critique(state, target)  → CritiqueResponse  # Cross-examine another agent
  └── revise(state, critiques) → AgentResponse     # Revise after critiques
```

Each method:
1. Calls the subclass's **prompt builder** for the user-turn text.
2. Calls `_call_structured(schema, action, round_number, user_prompt)` — which logs the call (agent, round, action, prompt size, provider, model, elapsed time) and invokes the LLM with this agent's `temperature` and `max_retries`.
3. LangChain's `with_structured_output()` validates the response against the schema.
4. Wraps the result in `AgentResponse` (via `_to_response()`) or `CritiqueResponse`.

### LLM Output Schemas

```python
class AgentLLMOutput(BaseModel):          # proposals and revisions
    position: str
    reasoning: str
    assumptions: list[str]
    confidence_score: float                # 0.0 – 1.0

class CritiqueLLMOutput(BaseModel):       # critiques
    critique_points: list[str]
    severity: Literal["low", "medium", "high", "critical"]
    suggested_revision: str | None
    confidence_score: float
```

The proposal/revision schema is a class attribute, `output_schema: ClassVar[type[AgentLLMOutput]] = AgentLLMOutput`. Ethics-class agents replace it with `EthicsLLMOutput`, which adds the veto fields (see below); everyone else keeps the plain schema.

### Abstract Methods (subclasses MUST implement)

| Method | Purpose |
|---|---|
| `_build_proposal_prompt(state)` | User prompt for a fresh proposal |
| `_build_critique_prompt(state, target)` | User prompt when critiquing another agent |
| `_build_revision_prompt(state, critiques)` | User prompt when revising after critiques |

### Built-in Features

- **Structured output** — validated Pydantic models straight from the LLM. Per-agent `temperature` (default 0.3) and `max_retries` (default 2) come from `AgentConfig`.
- **Auto-injection** — `agent_name`, `round_number`, `critic_agent` and `target_agent` are filled in after generation, so agents don't echo them.
- **Knowledge-base RAG** — with `state.use_knowledge_base` and a `KnowledgeBase` attached, `run()` and `revise()` append the top-k retrieved chunks (with source names) to the prompt.
- **Agent memory** — with `state.enable_agent_memory` and a memory store, the system prompt for that call gets up to 5 lessons from past debates.
- **Tool use** — `_run_tools()` runs each allowed tool (at most `MAX_TOOL_CALLS_PER_ROUND`, default 3), caches results by `(tool, input)` across proposal and revision, records calls on the round and emits `tool_called`.
- **Timeouts and concurrency** — the orchestrator wraps each call in `asyncio.wait_for()` (`AGENT_PROPOSAL/CRITIQUE/REVISION_TIMEOUT`, default 45 s; × `AGENT_TOOL_TIMEOUT_MULTIPLIER` 1.5 for tool users). Calls first take a per-provider slot (`LLM_MAX_CONCURRENCY`, default 4) — before the timeout starts, so waiting for a slot never times an agent out.

---

## Analyst Agent

**File:** `app/agents/analyst_agent.py`

- Extract facts, data points and cause-and-effect; quantify when possible; state assumptions.
- **Never** recommends a strategy or assesses risk.
- Context: summaries of prior rounds (each position truncated to 200 characters).
- Critiques: are claims evidence-based? factual errors, unsupported claims, missing data.

---

## Risk Agent

**File:** `app/agents/risk_agent.py`

- Identify risks, uncertainties and failure modes (operational, financial, reputational, technical, regulatory), rated low → critical.
- Adversarial but constructive; **never** proposes solutions.
- Context: the latest Analyst findings.
- Critiques: overlooked or underestimated risks, over-optimistic confidence, hidden assumptions.

---

## Strategy Agent

**File:** `app/agents/strategy_agent.py`

- Concrete, actionable strategies with implementation steps and at least 2 alternatives.
- Grounded in Analyst findings, acknowledging Risk concerns.
- Context: the latest Analyst and Risk outputs.
- Critiques: actionability, implementation steps, risk-reward of alternatives.

---

## Ethics Agent

**File:** `app/agents/ethics_agent.py`

- Validate proposals against ethical guidelines and compliance rules: fairness, bias, integrity, regulation, societal impact.
- Context: the latest Strategy proposal.
- Critiques: ethical blind spots, stakeholder impact, compliance objections.

### Structured veto

`EthicsAgent.output_schema = EthicsLLMOutput`:

```python
class EthicsLLMOutput(AgentLLMOutput):
    veto: bool = False               # true only if a proposal is fundamentally unethical
    veto_reason: str | None = None   # the principle violated and what would lift the veto
```

The values land on `AgentResponse.veto` / `veto_reason` (a reason is kept only while `veto` is true) and are sent with the `agent_output` SSE event.

- **The gate**: a standing veto in the current round blocks consensus (`ConsensusSignals.active_vetoes`). The debate keeps going; if rounds run out it ends with `max_rounds_reached`, not consensus.
- **Withdrawing**: in a revision the agent sets `veto=false` once its concerns are addressed.
- **The decision**: the moderator's finalize prompt lists standing vetoes ("do not adopt the vetoed course as proposed"), and `FinalDecision.vetoes` records them (`agent_name`, `reason`, `round_number`). The UI shows a Veto badge on the agent card and a "Standing veto" block on the decision; exports include them.

---

## Domain Agents

**File:** `app/agents/domain_agents.py`

Four domain agents subclass a core agent and replace its system prompt; all debate mechanics are inherited. They are registered disabled and join a debate only through a domain pack (`app/data/domain_packs.py`).

| Agent | Extends | Domain pack | Focus | Can veto |
|---|---|---|---|---|
| `FinancialEthics` 💰 | `EthicsAgent` | Finance | Securities law, insider trading, disclosure, conflicts of interest, ESG, fiduciary duty | Yes |
| `Security` 🔒 | `RiskAgent` | Engineering | OWASP Top 10, CVSS-critical issues, supply chain, infrastructure SPOF | No |
| `Compliance` 📋 | `RiskAgent` | Legal | Regulatory compliance, legal exposure, cross-jurisdiction issues | No |
| `PatientSafety` 🏥 | `EthicsAgent` | Healthcare | Clinical risk, patient welfare, medical ethics | Yes |

Each pack's agent list: Finance = Analyst, Risk, Strategy, FinancialEthics, Moderator; Engineering = Analyst, Risk, Strategy, Security, Moderator; Legal = Analyst, Risk, Ethics, Compliance, Moderator; Healthcare = Analyst, Risk, Ethics, PatientSafety, Moderator. A pack's `domain_focus` text is for display only.

---

## Moderator Agent

**File:** `app/agents/moderator_agent.py`

The Moderator does not argue a position. Each round it summarises the debate; at the end it writes the decision.

### Synthesis schema

```python
class ModeratorSynthesis(BaseModel):
    summary: str
    agreement_areas: list[str]
    disagreement_areas: list[str]
    agreement_score: float        # the moderator's own estimate — logged only
    should_continue: bool         # the moderator's recommendation — advisory
    next_round_focus: str | None
```

Whether a debate continues is decided by the **convergence gate** from measured signals, not by the moderator: its `should_continue` is logged (`moderator_recommends_continue`) and not sent to the UI, so the stream never shows a call that contradicts the routing.

### Methods

| Method | Returns | Purpose |
|---|---|---|
| `synthesize(state)` | `ModeratorSynthesis` | Per-round summary (system prompt: `SYNTHESIS_SYSTEM_PROMPT`) |
| `finalize(state)` | `FinalDecision` | The decision (system prompt: `FINAL_DECISION_SYSTEM_PROMPT`) |

Both go through `_call_structured()` (logging, configured temperature and retries). On a provider rate limit (`LLMRateLimitError`) they wait 10 s, then 20 s, and retry before giving up.

The finalize prompt includes, when present:
- the **human reviewer direction** from a HITL override, which the decision must follow (it is also stored as `FinalDecision.human_feedback`);
- the **standing ethics vetoes**.

If `synthesize()` fails but the round has agent output, the convergence node uses a placeholder summary and carries on; with no agent output at all the error is raised (e.g. a bad API key stops the debate early).

---

## Agent Registry

**File:** `app/agents/registry.py`

Central catalog: agents are registered at startup with a class and an `AgentConfig`; `get()` instantiates them with any per-agent LLM override.

### AgentConfig

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | — | Canonical name (e.g. "Analyst") |
| `role` | `str` | — | Role description |
| `icon` | `str` | `"🤖"` | Emoji |
| `system_prompt` | `str` | — | System prompt (domain agents keep theirs internally) |
| `enabled` | `bool` | `True` | Takes part by default |
| `model_provider` | `str \| None` | `None` | Per-agent provider override (`groq`, `openai`, `anthropic`, `gemini`) |
| `model_name` | `str \| None` | `None` | Per-agent model override |
| `temperature` | `float` | `0.3` | Sampling temperature (0.0–2.0) |
| `max_retries` | `int` | `2` | Retries on unusable output |
| `allowed_tools` | `list[str]` | `[]` | Tools the agent may use |

### Per-Agent LLM Routing

With `model_provider` or `model_name` set, the registry builds a dedicated `LangChainProvider` for that agent, using the server key for that provider from `server_api_key()` — the same map the global client uses, so Gemini overrides work too. No key configured → a clear `ValueError` naming the provider.

### Runtime Configuration

- `ENABLED_AGENTS` (comma-separated) decides which core agents are enabled.
- `GET /agents` lists the registry.

### Key Methods

| Method | Description |
|---|---|
| `register(agent_class, config)` | Register an agent; validates `allowed_tools` against `TOOL_REGISTRY` |
| `get(name, llm_client)` | Instantiate with per-agent overrides |
| `list_agents()` | All configs |
| `enabled_agents()` | Names of enabled agents |

---

## Tool System

**File:** `app/agents/tools.py`

Tools are LangChain `BaseTool` subclasses in `TOOL_REGISTRY`; an agent can only use tools in its `allowed_tools`.

| Tool | Name | Description |
|---|---|---|
| `WebSearchTool` | `web_search` | DuckDuckGo search, results capped at 2 KB |
| `CalculatorTool` | `calculator` | Arithmetic via `numexpr` (not `eval()`) |
| `GetCurrentDateTool` | `get_current_date` | Current UTC date and weekday |

Default assignments: **Analyst** → `web_search`, `get_current_date`; **Strategy** → `get_current_date`; others → none. The calculator isn't enabled for any agent by default.

### Safety Design

- **Calculator**: only numbers, operators, the math functions `sin cos tan arcsin arccos arctan arctan2 sinh cosh tanh arcsinh arccosh arctanh log log10 log1p exp expm1 sqrt abs` and the constants `pi`, `e`; any other name is refused up front. `numexpr` is given explicit namespaces (`local_dict` with just the constants, `global_dict={}`), so it can never read variables from the calling code. Input is capped at 200 characters.
- No shell execution, no file writes; all tools are read-only.
- Tool names are validated at registration; at most `MAX_TOOL_CALLS_PER_ROUND` calls per `run()`/`revise()`; results cached per `(tool, input)`; every call emits `tool_called`.

---

## Agent Interaction Diagram

```
Round N:
┌──────────────────────────────────────────────────────────────┐
│  Phase 1: PROPOSALS (parallel)                               │
│  Each debating agent produces an AgentResponse               │
├──────────────────────────────────────────────────────────────┤
│  Phase 2: CROSS-EXAMINATION (parallel)                       │
│  Every agent critiques every other agent's proposal          │
│  (4 agents × 3 targets = 12 CritiqueResponses)               │
├──────────────────────────────────────────────────────────────┤
│  Phase 3: REVISIONS (parallel)                               │
│  Each agent revises using the critiques aimed at it          │
│  (Quick mode skips phases 2 and 3)                           │
├──────────────────────────────────────────────────────────────┤
│  Phase 4: CONVERGENCE                                        │
│  Moderator summarises → measured agreement → hybrid gate     │
│  Gate passes or out of rounds → FINALIZE, else next round    │
│  Supervised: pause for human approval before finalizing      │
└──────────────────────────────────────────────────────────────┘
```

---

## Error Handling

- **Agent failures** are caught in the nodes; the debate continues with the remaining agents. Agents missing from the final round are listed in `missing_agents` and the decision is flagged `degraded`.
- **Unusable LLM output** raises `LLMResponseError` after the provider's retries (`max_retries`).
- **Rate limits** are classified as `LLMRateLimitError` (status code, class name or wrapped cause); the moderator retries with back-off, and the per-provider slot keeps bursts below the provider's limit.
- **Timeouts** — per phase, enforced by the node factories in `orchestrator/nodes.py`; an `agent_timeout` event is emitted.
