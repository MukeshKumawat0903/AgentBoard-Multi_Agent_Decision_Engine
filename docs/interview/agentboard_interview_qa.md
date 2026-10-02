# AgentBoard — Interview Question Bank (Detailed Answers)

> **Purpose:** A focused Q&A companion to `agent_board_storyline.md`. The storyline is the *narrative*; this file is the *drill set* — the specific questions an interviewer is likely to fire, each with a structured, ready-to-speak answer.
>
> **How to use:** Read the storyline first for the flow, then rehearse these answers out loud. Most answers follow a repeatable shape — **claim → mechanism → tradeoff/limitation** — so you sound deliberate, not memorised.
>
> **Interview-safe rule:** Quote exact numbers (~520 backend tests, 384-dim embeddings, 4 dimensions) only when you can explain how you got them. Otherwise present them as directional.

---

## TABLE OF CONTENTS

- [A. Project & Motivation](#a-project--motivation)
- [B. Architecture & System Design](#b-architecture--system-design)
- [C. Agents & the Debate Loop](#c-agents--the-debate-loop)
- [D. Consensus & Evaluation](#d-consensus--evaluation)
- [E. Streaming, HITL & Real-Time UX](#e-streaming-hitl--real-time-ux)
- [F. RAG, Memory & LLM Strategy](#f-rag-memory--llm-strategy)
- [G. Testing & Reliability](#g-testing--reliability)
- [H. Failure Modes & Recovery Playbook](#h-failure-modes--recovery-playbook)
- [I. Tradeoffs, Scaling & Reflection](#i-tradeoffs-scaling--reflection)
- [J. Behavioural & Rapid-Fire](#j-behavioural--rapid-fire)

---

## A. PROJECT & MOTIVATION

### A1. "Tell me about AgentBoard in 60 seconds."

**Claim:** "AgentBoard is a full-stack, multi-agent AI decision engine. Instead of one LLM giving a confident monologue to a hard question, five constrained agents — Analyst, Risk, Strategy, Ethics, and a Moderator — debate it in structured rounds: propose, critique, revise, converge."

**Mechanism:** "It's orchestrated as a LangGraph state machine, streams live to a Next.js frontend over SSE, and the Moderator only stops when *measurable* consensus is reached — quantified with confidence scores and sentence-embedding similarity, not vibes. It also has RAG grounding, human-in-the-loop approval, and an LLM-as-judge that scores the final decision."

**Why it matters:** "The thesis is that decision quality comes from *structure* — constrained perspectives forced to challenge each other — not from a bigger model. The same LLM produces a dramatically more defensible, auditable answer when you wrap it in adversarial process."

### A2. "Why did you build it? What problem does it solve?"

> "I noticed that if you ask an LLM a complex question and then re-ask it with slightly different framing, you get an equally confident but contradictory answer. There's no internal pushback — no one saying 'what about the regulatory risk?' Real boardrooms get quality from *adversarial process*: finance proposes, risk challenges, legal flags compliance, a chair synthesises. I wanted to simulate that. Each agent is locked to one lens — the Analyst can't propose strategy, the Risk agent can't offer solutions — and they must engage with each other's criticism before a final answer is produced."

### A3. "How is this different from AutoGen / CrewAI?"

| | AutoGen / CrewAI | AgentBoard |
|---|---|---|
| Interaction | Agents **collaborate** (pass messages, help each other) | Agents **argue** under a formal protocol |
| Protocol | Loose conversation | propose → cross-examine → revise → measure |
| Consensus | Implicit / "it stopped" | **Quantified** (confidence-weighted stance vote, behind a six-signal gate) |
| Scope | Mostly a Python orchestration layer | Full product: streaming, persistence, analytics, HITL |

> "The one-liner: AutoGen agents help each other; AgentBoard agents cross-examine each other, and the agreement is a *measured score*, not a feeling."

---

## B. ARCHITECTURE & SYSTEM DESIGN

### B1. "Walk me through the architecture end to end."

> "Five layers. I'll trace a single request top to bottom:"

1. **Frontend (Next.js 15 / React 18):** User submits a question → `POST /debate/start-async`.
2. **API layer (FastAPI):** Validates via Pydantic, creates a `DebateState`, launches a background task, and immediately returns a `thread_id`. The frontend then subscribes to `GET /debate/{thread_id}/stream` (SSE).
3. **Orchestration (LangGraph StateGraph):** `proposals → critiques → revisions → convergence → finalize`, with a conditional edge that loops back to `proposals` or routes to `finalize`.
4. **Agents & services:** `BaseAgent` subclasses, plus `ConsensusEngine`, `KnowledgeBase` (RAG), `AgentMemory`, `Evaluator`, `Simulator`.
5. **Data layer:** Async SQLite for persistence, ChromaDB for vectors, LangGraph checkpointer for resumable state.

> "Every node emits SSE events that stream live to the client; when the Moderator declares consensus, the `FinalDecision` is persisted and streamed."

### B2. "Why FastAPI, and why SSE instead of WebSockets?"

- **FastAPI:** "Native async (critical — agent calls are I/O-bound), first-class Pydantic for validation and structured output, SSE via `StreamingResponse`, and auto-generated OpenAPI docs."
- **SSE over WebSockets:** "The traffic is unidirectional — the server pushes debate events, the client just renders. WebSockets add bidirectional complexity I don't need. SSE gives me event IDs and simple replay semantics, and the browser's `EventSource` auto-reconnects. **The tradeoff** I accepted: I can't push client→server mid-debate over the same channel — but HITL approvals go over a normal REST endpoint, so that's fine."

### B3. "What design patterns did you actually use, and where?"

| Pattern | Where | Payoff |
|---|---|---|
| **Template Method** | `BaseAgent` defines the skeleton (build prompt → call LLM → parse); subclasses override 3 prompt methods | Adding an agent = write 3 prompts, register it |
| **Adapter** | `LangChainProvider` wraps Groq/OpenAI/Anthropic behind one interface | Switch providers via one env var or API call |
| **Factory (closures)** | `make_proposal_node(agents, llm_client)` returns the LangGraph node | Dependency injection without globals |
| **State Machine** | LangGraph `StateGraph` over `DebateState` | Checkpointing, conditional routing, HITL |
| **Graceful Degradation** | timeouts, parse retries, missing-KB fallback | A failure weakens the answer, never crashes it |

> "The one I'm proudest of is Template Method on `BaseAgent` — it turned 'add a new domain agent' from a refactor into a 20-minute task."

---

## C. AGENTS & THE DEBATE LOOP

### C1. "Name the five core agents — what is each one constrained to?"

> "Five lenses, and the constraints *are* the design — each agent is forbidden from straying into another's territory, which is what forces genuine diversity instead of five paraphrases."

| Agent | Lens | Hard constraint |
|---|---|---|
| **Analyst** | Facts, causality, evidence | Cannot propose strategy or assess risk |
| **Risk** | Failure modes, worst cases | Cannot offer solutions |
| **Strategy** | Positioning, alternatives | Must acknowledge risks and weigh alternatives |
| **Ethics** | Fairness, regulation, stakeholders | Holds **VETO** power on ethical violations |
| **Moderator** | All positions holistically | Cannot take sides — neutral synthesiser |

> "The first four debate; the Moderator never advocates — it measures agreement and writes the final synthesis. On top of these, **four domain agents** extend the base roles for vertical packs — `FinancialEthics` (ESG, fiduciary, securities law), `Security` (OWASP, attack surface), `Compliance` (cross-jurisdiction regulation), and `PatientSafety` (clinical risk) — so a finance or healthcare debate gets specialised lenses without touching the core engine."

### C2. "Why constrained agents instead of generic ones?"

> "This was the breakthrough. My first version was generic — 'You are Agent 1, analyze this.' I got five polished paraphrases of the *same* answer, because every agent tried to be comprehensive. The fix was **hard constraints**: I tell the Risk agent 'You MUST NOT propose solutions.' Now it's genuinely adversarial — it surfaces failure modes the Strategy agent missed because the Strategist was busy building a plan. **Constraint creates diversity, and diversity is what makes the ensemble work.** That's not a metaphor — it's ensemble theory: independent, diverse estimators have lower aggregate error, but five copies of the same model aren't independent, so I had to *engineer* the independence."

### C3. "Walk through one full debate round."

> "Take 'Should we pivot from B2C to B2B SaaS?'"

- **Proposals (parallel):** All four agents answer simultaneously, each producing a structured output — position, reasoning, assumptions, and a confidence score in `[0,1]`.
- **Critiques (cross-examination):** Each agent reads the other three proposals and writes critiques, rated low/medium/high/critical. That's up to 12 critiques. E.g., Risk → Strategy: "Your phased pivot assumes you keep B2C revenue during transition, but your own data shows 30% churn — critical."
- **Revisions (under pressure):** Each agent revises against the critiques aimed at it. Confidence scores move — up when validated, down when conceding.
- **Convergence check:** The consensus engine scores the round (confidence-weighted vote over each agent's structured stance) and a deterministic six-signal gate decides continue or stop. The Moderator writes an advisory summary and names the leading proposal that agents vote on next round. In Standard mode `min_rounds` is 2, so round 1 always loops.
- **Finalize:** Once all six gate signals hold (`consensus_reached`) or max rounds are hit (`max_rounds_reached`), the Moderator emits a `FinalDecision`: recommendation, confidence, risks, alternatives, **minority dissent**, and the full trace.

### C4. "How do you add a new domain — say, healthcare?"

> "The core panel is 4 debaters + 1 moderator, but it's built for extensibility. Domain agents *extend* base roles: `PatientSafetyAgent` extends `RiskAgent` with clinical-risk and patient-welfare lenses; `FinancialEthicsAgent` extends `EthicsAgent` with ESG, fiduciary duty, and securities law. Because of the Template Method base, a new domain agent is just three prompt overrides plus registration. Activating a 'domain pack' is a single config change."

### C5. "Your resume says 'explainable, auditable decisions' — what actually makes them auditable?"

> "Auditability is built into the data model, not bolted on afterwards. Four things make any decision reconstructable after the fact:"

- **Full debate trace is persisted.** Every proposal, every critique (with its severity), and every revision for every round is stored — plus the `FinalDecision` with recommendation, confidence, risks, alternatives, and minority dissent. You can replay exactly how the system arrived at the answer.
- **Per-step reasoning is structured, not prose.** Each agent output carries `position`, `reasoning`, and `assumptions` as *typed fields*, and the LLM-as-judge attaches a `reasoning` paragraph citing evidence. So the "why" behind any step is queryable, not buried in free text.
- **Event log + correlation ID.** Every event is persisted to the `debate_events` table, and an `X-Request-ID` threads a single request through API → graph → agents → DB — so one decision is traceable across the whole stack.
- **Preserved dissent over false certainty.** The agreement score is surfaced to the user, and unresolved minority views stay in the final decision instead of being smoothed away — so a reader sees *how contested* the conclusion was.

> "That combination — full trace, structured reasoning, correlation IDs, and explicit dissent — is what lets a human stand behind the recommendation in a compliance-sensitive setting. 'Explainable' isn't a marketing word here; it maps to specific persisted fields."

---

## D. CONSENSUS & EVALUATION

### D1. "What was the hardest technical problem you solved?" *(flagship answer)*

> "Measuring when AI agents *actually* agree. It sounds trivial — check if they said the same thing — but it isn't. I iterated through three text-based scores, wrapped them in a multi-signal gate, and finally stopped comparing text at all:"

- **V1 — Mean confidence.** "Average everyone's confidence. **The bug:** Analyst 0.9 confident we should expand, Risk 0.85 confident we should NOT — mean 0.875, above threshold. The system declared consensus on a flat-out disagreement. **High confidence ≠ agreement.**"
- **V1.5 — Jaccard word overlap × confidence.** "Better, but Jaccard is bag-of-words. 'We should expand into Europe' and 'We should NOT expand into Europe' have huge word overlap and opposite meaning."
- **V2 — Semantic similarity + confidence hybrid (opt-in).** "I embedded each position with `all-MiniLM-L6-v2` (384-dim), computed pairwise cosine similarity, and blended: `hybrid = 0.5·mean_confidence + 0.5·semantic_similarity`. That catches positions that are about different things. But embeddings are negation-blind too: 'should expand' and 'should NOT expand' still land close together. Words and embeddings both measure *topic*, not *verdict*."
- **The gate.** "The score (`0.7·mean_confidence + 0.3·overlap`, overlap rescaled so 0.08 → 0 and 0.19 → 1) became only one of six conditions. The others are a minimum number of rounds, at most one dissenter, at most two high-severity critiques that round, agents settled, and no standing Ethics veto. But the score itself was still broken: agents debating one question share its vocabulary, so the overlap saturated at 1.0 and a confident 2-vs-2 split scored 0.86, enough for Thorough."
- **V3 — Stance vote (what ships).** "Each agent now fills a structured `stance` — support, oppose, conditional or abstain — toward a concrete proposal: the question in round 1, the Moderator's one-sentence `leading_proposal` after that. Agreement is the confidence-weighted vote share of the largest stance group. The Analyst abstains, `conditional` is its own group, and a veto forces `oppose`. That 2-vs-2 split now scores ~0.50 and fails every mode. The lexical blend stays as the fallback when fewer than two agents vote, and `SEMANTIC_CONSENSUS_ENABLED` now only reports cosine as a diagnostic instead of silently replacing the score."
- **The limit.** "I'm upfront that this *reduces* false consensus rather than solving it. The stance is self-reported, so the next step would be an NLI check that each position actually matches its stance, plus calibrating the thresholds on labeled debates."

> "I also track **position drift**. If positions barely move between rounds (drift < 0.05), that's one of two ways agents count as 'settled'. It's not an early stop: every other gate signal must still hold, and a stall below the threshold runs to `max_rounds`. The story shows iterative problem-solving, finding bugs through testing, ML fundamentals, and knowing a method's limits."

### D2. "Isn't a single agreement number gameable?"

> "Yes — which is why convergence isn't one number, it's a **multi-signal quorum gate**. Six conditions must all hold: a clear stance majority, a minimum number of rounds, few dissenters, few high-severity critiques raised that round, converged confidence (stopped moving, tight spread or all highly confident), and no standing Ethics veto. The principle is the same instinct as a database quorum: any single vote is gameable — confidence especially, because an LLM's confidence is *not* a probability of being correct — so don't let one signal decide."

### D3. "How do you know the final decision is any *good* (not just agreed)?"

> "Consensus measures *agreement*; quality is a separate question, so I built an **LLM-as-judge Evaluator**. A separate LLM that never debated reads the final decision and scores four dimensions, each 0.0–1.0:"

| Dimension | Checks |
|---|---|
| completeness | Addresses all aspects of the query? |
| consistency | Internally coherent, no contradictions? |
| actionability | Concrete next steps, not platitudes? |
| risk_awareness | Relevant risks identified and addressed? |

> "`overall` is the mean; the judge must also return a `reasoning` paragraph citing evidence, so the score is auditable. It uses the same `with_structured_output()` Pydantic pattern as the agents (validated floats), and results are cached in `decisions.evaluation_json` so I never re-judge the same decision. **The honest limitation:** LLM judges have self-preference and positional biases, so I treat the score as a directional signal, and I'd harden it with human-labelled calibration and a *different* model family as judge than the one that debated."

---

## E. STREAMING, HITL & REAL-TIME UX

### E1. "How does the live streaming work, and what happens on a dropped connection?"

> "Each agent node, on completing work, builds an event payload, appends it to an in-memory **replay buffer** (for late joiners), pushes it to a per-client `asyncio.Queue`, persists it to a `debate_events` table (cross-restart replay), and the `StreamingResponse` yields it to the browser's `EventSource`."

> "On a drop — proxies, idle timeouts, network blips — the client reconnects with exponential backoff (1→2→4…30s), resumes from the last seen event ID, and the server replays everything after that ID from the buffer/DB. So the user misses nothing. After 10 failed attempts it shows a **'Connection lost'** view with an in-place Reconnect — the debate keeps running on the server — and a finished debate always loads from the REST API, stream or not."

### E2. "Explain the human-in-the-loop flow technically."

1. User starts with `supervised: true`.
2. Debate runs normally through rounds.
3. At convergence, the `finalize` node calls LangGraph's `interrupt()`.
4. Graph state is **checkpointed to SQLite** at the exact mid-execution point.
5. An `approval_required` SSE event hits the frontend → dialog with **Approve / Override / Add Round**.
6. The human chooses → `POST /debate/{thread_id}/approve`.
7. Backend calls `graph.resume()` — LangGraph loads the exact checkpoint and continues. "Add Round" loops back; "Approve/Override" finalizes.

> "This is 'trust but verify' — the AI does the cognitive heavy lifting, the human keeps final authority. And HITL was *almost free* architecturally because the state machine already checkpoints; I just route through a node that interrupts."

### E3. "Explain LangGraph checkpointing — what is it, what does it buy you, and where does the state live?"

**What it is:** "After *every* node executes, LangGraph serialises the entire graph state — my `DebateState` TypedDict: the question, current round, all proposals/critiques/revisions, the agreement score, config — and persists it through a **checkpointer**, keyed by `thread_id`. So at any point there's a durable snapshot of 'exactly where this debate is.'"

**What it buys me — four things:**

| Capability | Without checkpointing | With it |
|---|---|---|
| **Crash recovery** | Lose all state, restart from round 1 | Resume from the last saved node |
| **Human-in-the-loop** | Block a thread forever waiting on input | `interrupt()` persists exact state, `resume()` reloads it |
| **Concurrency isolation** | Debates risk clobbering each other | State is scoped per `thread_id` |
| **Debuggability** | Print statements | Time-travel replay of any node in LangGraph Studio |

**Where the state lives:** "The checkpointer is backed by the same async **SQLite** store, so each `thread_id` has its own checkpoint lineage on disk. Worth separating two things that sound similar: **LangGraph checkpoints** are *control-plane* state — the graph's position and accumulated `DebateState`, used to resume — whereas my `debate_events` table is *data-plane* — the stream of UI events, used for SSE replay. Different jobs, different stores."

**The honest limitation:** "Today it's a single-node SQLite checkpointer, so only this process can resume a thread. At scale I'd swap in a Postgres- or Redis-backed checkpointer (LangGraph supports both) so any worker in a pool can pick up any debate — and that's a backend swap, not an engine rewrite, because the graph never knows which checkpointer it's talking to."

---

## F. RAG, MEMORY & LLM STRATEGY

### F1. "Walk me through your RAG pipeline and the choices in it."

> "Ingest: extract text → sliding-window chunk at **1000 chars / 200 overlap** → embed with `all-MiniLM-L6-v2` (384-dim) → store in ChromaDB. At debate time: embed the question with the same model → cosine search → take the **top-5 chunks at or above 0.30 similarity** → inject as numbered context blocks into each agent's system prompt."

| Choice | Why |
|---|---|
| `all-MiniLM-L6-v2` (local) | Free, no API latency, 384-dim is enough to find the right paragraph |
| 1000/200 chunking | Balances context length vs. semantic coherence |
| top-5 @ 0.30 threshold | MiniLM cosine runs low even for relevant chunks, so the floor is permissive; top-5 keeps the token budget ~500–1000 |
| ChromaDB local | Zero infra, ~5ms queries, offline |

> "Crucially it's **additive** — if no docs are uploaded or ChromaDB is down, `_enrich_with_kb()` returns the prompt unchanged. RAG is an enhancement, never a dependency."

### F2. "Agent memory — how do agents learn across debates?"

> "After each debate, each agent's final position is **LLM-summarised into a one-sentence lesson** and stored in SQLite. On a new debate (if enabled), each agent gets its 5 most recent lessons injected into its system prompt (retrieval is by recency today; ranking by similarity to the new question is the obvious next step). **Why summarise?** A raw position is ~2000 tokens; injecting five of them blows 10k tokens of context. A distilled lesson is ~30 tokens — same insight, ~98% fewer tokens. It gives agents institutional memory instead of starting from zero every time."

### F3. "How do you manage cost across LLM providers?"

> "Adapter pattern over Groq (LLaMA 3.3 70B — default, cheap, fast), OpenAI (GPT-4o — premium synthesis), and Anthropic (Claude — safety-sensitive). Switching is one env var or a runtime `POST /llm-settings`; user-supplied keys are held in memory only, never persisted. The real lever is **per-agent model routing** — the Moderator's synthesis benefits most from a premium model, the Analyst's fact-finding doesn't, so I can put the best model only where it has leverage and keep cheap models on routine reasoning. That can cut cost several-fold while protecting quality where it matters."

---

## G. TESTING & RELIABILITY

### G1. "How do you test a non-deterministic AI system?"

> "You can't `assert output == expected_string`. So I test **structure and contracts**, not content. About 520 backend tests in 48 modules (plus ~114 frontend unit tests and 71 Playwright end-to-end tests), all with mocked LLMs and throw-away databases, run in CI before any image is built. They cover: schema validation (`confidence_score: 1.5` → `ValidationError`), agent contracts (`isinstance(result, AgentLLMOutput)` regardless of LLM content), **deterministic consensus math** (`V1_score([...]) == 0.75` exactly), state-machine routing (`agreement ≥ threshold → finalize`), API contracts, and graceful-degradation paths. Every LLM call is mocked with `AsyncMock` returning a valid `AgentLLMOutput`, so tests run in milliseconds, not dollars."

> "On top of unit tests, the **Simulator** runs N identical debates and computes the mean pairwise word overlap (Jaccard) of the final decisions, rescaled like the consensus score — a *consistency score*. Above ~0.80 the question type is stable; below ~0.55 it's unreliable. That's effectively a statistical stability test for the whole system."

### G2. "What happens when the LLM times out or returns garbage?"

> "My failure philosophy is **isolate, degrade, recover.**"

| Failure | How it copes today |
|---|---|
| Agent call times out | `asyncio.wait_for` (45s; tool agents 1.5×) → emit `agent_timeout`, drop that agent, Moderator notes the round is degraded |
| Malformed structured output | `with_structured_output()` + retry `stop_after_attempt(2)` → on double failure return `None`, skip that agent (logged with payload) |
| Provider rejects sampling params | `_sampling_kwargs()` omits `temperature` for models that reject it, so the call never 400s |
| Rate limit / 429 | Raised as `LLMRateLimitError` with a dedicated handler; frontend backs off |

> "A 3-agent debate is better than a failed one. Every external call is timeout-bounded and has a fallback."

### G3. "How do you debug a production issue in something this opaque?"

> "Three tools. (1) **Structured JSON logs** with context — `thread_id`, `agent_name`, `round`, `latency_ms` — parseable by ELK/Datadog without regex. (2) A correlation **`X-Request-ID`** on every response that propagates through API → graph → every agent call → DB, so I can trace one user request end to end. (3) Optional **LangSmith** tracing — set `LANGSMITH_TRACING=true` and I get every prompt, token count, and latency visualised on the debate graph, which is how I optimise prompts."

---

## H. FAILURE MODES & RECOVERY PLAYBOOK

> *This is the section that separates juniors from seniors. Anyone can demo the happy path; the signal is what you say when asked "what happens when the LLM times out / returns garbage / the stream drops?" Every answer below follows the same four beats: **what breaks → why → how it copes today → how I'd harden it.** G2 introduced the LLM layer conversationally; this is the full four-layer playbook to study.*

### H1. "What's your overall failure philosophy? (say this first)"

> "**Isolate, degrade, recover.** Every external call is timeout-bounded, so a failure is contained to one agent or one request. The system degrades gracefully — a missing agent, empty knowledge base, or dropped stream gives a *weaker* result, not a crash. And it recovers — structured-output retries, SSE replay plus a REST fallback, cold-start backoff, and LangGraph checkpoints. The honest limitation is that it's single-node, and I can walk you through the durable-queue-plus-Postgres version. If you remember one sentence: *every external dependency is timeout-bounded and has a fallback.*"

### H2. "LLM-layer failures — the model times out, 400s, or returns garbage."

| What breaks | How it copes today | How I'd harden it |
|---|---|---|
| **Agent call times out** | `asyncio.wait_for` (45 s; tool agents 1.5×) → emit `agent_timeout`, drop that agent, Moderator notes a degraded round | Adaptive per-provider timeouts; speculative re-issue to a faster fallback model |
| **Malformed structured output** | `with_structured_output()` + retry `stop_after_attempt(2)` → on double failure return `None`, skip that agent (logged with payload) | A third "repair" attempt feeding the bad output back with the schema |
| **Provider 400s on sampling params** | `_sampling_kwargs()` omits `temperature` for models that reject it, so the call never 400s | Central per-model capability registry that strips unsupported params |
| **Rate limit / 429** | Raised as `LLMRateLimitError` with a dedicated handler → clean 429; frontend backs off | Token-bucket limiter + request queue + multi-key rotation |
| **Every agent fails in a phase** | No outputs → surfaced as an error rather than fabricating a decision | Circuit breaker: after K consecutive provider failures, fail fast with a clear message |

### H3. "Orchestration-layer failures — the debate logic itself misbehaves."

| What breaks | How it copes today | How I'd harden it |
|---|---|---|
| **False consensus** (agreement reported for opposed views) | Stance vote inside a six-signal quorum gate — confidence alone can't converge, a split vote can't pass; stances are self-reported | NLI check of position vs. stance; calibrated agreement model trained on labelled debates |
| **Never converges** | Hard `max_rounds` ceiling → honest `max_rounds_reached`, decision still produced with low agreement | Adaptive round budget by question difficulty; escalate to HITL |
| **Stagnation** (positions stop moving, threshold unmet) | No standalone early stop: drift < 0.05 only passes the "converged" signal; a stall below threshold runs to `max_rounds` | Early-stop a true stall; distinguish it from oscillation |
| **Concurrent debates interfere** | Unique `thread_id` scopes graph state, event buffer, and DB rows; per-thread `asyncio.Lock` | Move shared state to Redis/Postgres keyed by `thread_id` for multi-worker scale |
| **Prompt exceeds context window** | Hard caps at every injection point (KB ≤ 5 chunks, tools ≤ 2 KB, memory ≤ 5 lessons) | Pre-flight token counting; summarise-then-inject when over budget |

### H4. "Streaming & frontend failures — the connection drops."

| What breaks | How it copes today | How I'd harden it |
|---|---|---|
| **SSE connection dropped** | Heartbeats + `EventSource` auto-reconnect with backoff + **replay buffer** so no events are lost | Resume-from-cursor via `Last-Event-ID` |
| **SSE keeps failing** | Backoff 1 → 30 s, then after 10 failures a **"Connection lost"** view with an in-place Reconnect (the debate keeps running server-side); finished debates load from REST regardless | Switch transport (polling / WebSocket) based on a connection-health score |
| **Backend cold start** (free-tier, heavy imports) | `withRetry` exponential backoff; health dot recovers on success | Warm-up ping / keep-alive; lazy-load heavy deps |
| **Zombie SSE generators** | `request.is_disconnected()` checked at least every 20 s (the `ping` interval); the Next.js proxy forwards the browser's abort; replay buffers freed when a debate ends | Central connection registry with TTL eviction |

### H5. "Data & infrastructure failures — storage or the embedding model dies."

| What breaks | How it copes today | How I'd harden it |
|---|---|---|
| **SQLite write fails / slow** | WAL mode (readers don't block writers); event writes retry when the DB is busy; state snapshots are best-effort; the decision is stored **before** checkpoints are deleted, so a failed save stays resumable | Outbox pattern + retry queue; Postgres with pooling |
| **Process crash mid-debate** | LangGraph checkpointer persists graph state → resumable; completed rounds already in SQLite | Durable task queue (Celery/Temporal) so the runner itself recovers |
| **Embedding model unavailable** (offline / OOM) | `KnowledgeBase.is_available = False` → agents run without RAG (degraded, not broken) | Pin/pre-pull the model in the image; health-gate KB features |
| **Missing / invalid API key** | Fails fast at startup if the **active** provider's key is missing (errors never echo secrets); user-supplied keys held in memory only; switching providers needs the admin token | Secret manager + key validation on `/llm-settings` save |

### H6. "RAG / knowledge-base failures — retrieval returns nothing, or ChromaDB is down."

| What breaks | How it copes today | How I'd harden it |
|---|---|---|
| **ChromaDB unavailable** | `_enrich_with_kb()` returns the prompt unchanged → agents reason without context (RAG is additive, never required) | Health-check the vector store at startup; circuit-break KB calls |
| **No documents uploaded / empty KB** | Retrieval is skipped — the debate proceeds on the agents' own reasoning, no error | Surface a UI hint that grounding is off for this debate |
| **Nothing clears the 0.30 similarity threshold** | Low-relevance chunks are filtered out rather than injected, so irrelevant text never pollutes the prompt | Best-effort lower-confidence retrieval with a visible caveat |
| **Document extraction fails** (corrupt / scanned PDF) | That upload is rejected and logged; the rest of the KB stays usable | Per-file status + retry; OCR fallback for scanned PDFs |
| **Embedding model down** | *(also affects consensus + memory — see H5)* → `KnowledgeBase.is_available = False`, agents run without RAG | Pin/pre-pull the model in the image; health-gate KB features |

> "The throughline for RAG is **additive, never required** — every failure path degrades to 'reason without grounding,' never to a crash. It's the same `_enrich_with_kb()` graceful-degradation guarantee from the RAG pipeline answer (F1), and it's why an empty or broken knowledge base produces a weaker answer instead of a 500."

> **The closing line that lands:** "Graceful degradation is the theme — use the orchestra analogy: *if one musician drops out, the orchestra keeps playing; it doesn't stop the concert.* Every row above is a chance to show I think in blast radius, fallbacks, and a concrete upgrade path."

---

## I. TRADEOFFS, SCALING & REFLECTION

### I1. "Tell me about a design tradeoff you made and accepted."

> "SQLite over PostgreSQL. **Context:** it's a portfolio project — I wanted zero infrastructure. **Decision:** async SQLite via `aiosqlite`. **Tradeoff accepted:** single-process write bottleneck, no horizontal scaling. **Mitigation:** every storage dependency sits behind an abstraction boundary, so swapping to Postgres is a driver + query change the API layer never sees. I can articulate exactly what breaks at scale and exactly how I'd migrate — which is the point of the decision, not pretending SQLite is production-grade."

### I2. "How would you scale this to thousands of concurrent debates?"

| Area | Today | At scale | Migration |
|---|---|---|---|
| DB | SQLite (single-writer) | PostgreSQL | `aiosqlite` → `asyncpg` |
| State | In-memory dicts | Redis (shared) | Serialize + Redis pub/sub for SSE fan-out |
| Vectors | ChromaDB local | Pinecone / pgvector | Swap two methods in `KnowledgeBase` |
| Tasks | `BackgroundTasks` | Celery + Redis broker | Durable execution with retry/DLQ |
| Auth | None | JWT/OAuth2 + RBAC | Auth middleware |

> "The shape becomes ALB → stateless FastAPI workers → Redis (state, pub/sub, rate limiting, SSE fan-out) → Celery debate workers → Postgres/Pinecone. The architecture was *designed* for this — replaceable storage behind boundaries — so it's a migration, not a rewrite."

### I3. "What would you do differently if you started over?"

> - "Start on PostgreSQL — SQLite's single-writer limit was fine for dev but caps scaling, and retrofitting is annoying."
> - "Add auth from day one — it's harder to bolt on later."
> - "Build a real prompt-management system — prompts are in-code strings today; they should be versioned and A/B testable."
> - "Keep SSE for the stream but add WebSockets for genuinely bidirectional features like mid-debate human injection."

---

## J. BEHAVIOURAL & RAPID-FIRE

### J1. "What are you most proud of in this project?"

> "That the hardest engineering wasn't in the code — it was in the *constraints*. The false-consensus bug taught me that the obvious metric (mean confidence) was actively wrong, and fixing it properly meant reaching for embeddings and a multi-signal gate. The system is honest: it preserves dissent, it tells you *how* strongly agents agreed, and it scores its own output. I'd rather ship transparency over false certainty."

### J2. "How does the system handle disagreement between agents?"

> "Disagreement is a **feature**. If agents don't converge by max rounds, the Moderator preserves the dissent as 'minority views' in the final decision. The Ethics agent even has VETO power on ethical violations. The agreement score is surfaced to the user — 0.6 is flagged 'low confidence, significant dissent'; 0.9 is 'strong consensus.' I never fake agreement to look clean."

### J3. Rapid-fire one-liners

| Q | A |
|---|---|
| Why LangGraph not a `while` loop? | Checkpointing, HITL `interrupt()`, declarative conditional routing, time-travel debugging. |
| Why `with_structured_output()`? | Type-safe LLM boundary, kills ~40 lines of regex/JSON parsing per call, auto-retry. |
| Why embeddings for consensus? | They catch positions about different things that share few words. They can't tell "expand" from "do NOT expand" either, so they're opt-in and the six-signal gate does the real work. |
| Why a separate judge LLM? | Separates *who decides* from *who grades* — reduces self-preference bias. |
| Biggest limitation? | Single-node (SQLite + in-memory state); I know the exact Redis/Postgres/Celery upgrade path. |

---

*Companion to `agent_board_storyline.md`. Last updated: June 2026.*
