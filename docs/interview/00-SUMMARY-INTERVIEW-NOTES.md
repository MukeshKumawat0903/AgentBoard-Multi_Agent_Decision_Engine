# AgentBoard — Detailed Interview Notes

> **Quick Reference:** Multi-agent AI debate system. Specialised LLM agents (Analyst, Risk, Strategy, Ethics) argue, critique, revise, and converge on well-defended decisions through structured adversarial debate — streamed live via SSE to a Next.js frontend.

---

## 📋 TABLE OF CONTENTS

1. [Elevator Pitch](#1-elevator-pitch)
2. [Problem &amp; Motivation](#2-problem--motivation)
3. [Architecture at a Glance](#3-architecture-at-a-glance)
4. [Key Components](#4-key-components)
5. [Key Design Decisions](#5-key-design-decisions-interview-gold)
6. [Debate Flow End-to-End](#6-debate-flow-end-to-end)
7. [Debate Modes](#7-debate-modes)
8. [ML &amp; Algorithms](#8-ml--algorithms)
9. [Challenges &amp; Edge Cases](#9-challenges--edge-cases)
10. [Scalability &amp; Production Path](#10-scalability--production-path)
11. [Evaluation Metrics](#11-evaluation-metrics)
12. [Mental Models &amp; Analogies](#12-mental-models--analogies)
13. [Tech Stack Summary](#13-tech-stack-summary)
14. [Key Code Patterns](#14-key-code-patterns)
15. [What I&#39;d Do Differently](#15-what-id-do-differently-honest-self-reflection)
16. [Theoretical Concepts &amp; Fundamentals](#16-theoretical-concepts--fundamentals-deep-dives)
17. [Failure Modes &amp; How to Resolve](#17-failure-modes--how-to-resolve)
18. [Interview Q&amp;A (26 Questions)](#possible-interview-questions--answers)

---

## 1. ELEVATOR PITCH (30 seconds)

> _"AgentBoard is a multi-agent AI debate system. Instead of one LLM call, it creates a panel of specialised AI agents — an Analyst, a Risk assessor, a Strategist, and an Ethics guardian — who propose positions, cross-examine each other, and refine their views over multiple rounds. A Moderator measures convergence and synthesises a final decision with confidence scores, risk flags, and dissenting opinions. The whole thing streams live over SSE with a Next.js frontend, persists to SQLite, and supports human-in-the-loop approval."_

### 💡 Why This Pitch Works

- Answers **what** (multi-agent debate), **how** (propose → critique → revise → converge), and **outcome** (confidence-scored final decision) in one breath.
- Mentions key differentiators: specialised roles, adversarial process, streaming, persistence, HITL.
- Use it verbatim for "Tell me about your project" openers.

---

## 2. PROBLEM & MOTIVATION

### The Core Problem with Single LLM Calls

When you ask one LLM a complex question, you get:

- A **plausible-sounding but shallow** answer
- **Single perspective** — the model has no mechanism to challenge its own reasoning
- **No adversarial pressure** — nothing forces the model to defend its claims
- **No measurable confidence in consensus** — you can't quantify how "good" the answer is

### The Solution: Structured Adversarial Debate

AgentBoard introduces a **boardroom-style debate protocol**:

```
Propose → Critique → Revise → Converge
```

Each agent sees the others' reasoning and must defend their own position against targeted challenges. This surfaces blind spots, contradictions, and overlooked risks that a single-call approach would miss.

### Key Differentiators vs. Existing Frameworks

| Framework                  | What It Does                  | What AgentBoard Adds                                         |
| -------------------------- | ----------------------------- | ------------------------------------------------------------ |
| **AutoGen**          | Agent conversation loops      | No built-in checkpointing, no HITL interrupt                 |
| **CrewAI**           | Sequential pipelines          | No conditional phase skipping, no quantified consensus       |
| **LangChain Agents** | Single-agent tool use         | No multi-agent adversarial debate                            |
| **AgentBoard**       | Structured adversarial debate | All of the above + measurable consensus + full-stack product |

### Why "Adversarial" Matters

- **Cognitive diversity** forces agents into roles they can't escape — Risk MUST look for failure modes even if it's inconvenient
- **Cross-examination** of other agents' reasoning is where the real value emerges — same as peer code review vs self-review
- **Quantified convergence** gives you a number to trust, not just a feeling

---

## 3. ARCHITECTURE AT A GLANCE

```
┌─────────────────────────────────────────────────────┐
│              Next.js 15 Frontend                     │
│   SSE Consumer · Debate Viewer · Analytics Dashboard │
└───────────────────────┬─────────────────────────────┘
                        │ SSE (Server-Sent Events)
                        ▼
┌─────────────────────────────────────────────────────┐
│              FastAPI Backend                         │
│   REST endpoints · SSE streaming · Rate limiting     │
└───────────────────────┬─────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│         LangGraph State Machine (DebateGraph)       │
│   proposals → critiques → revisions → convergence   │
│   → finalize · Conditional routing · HITL interrupt │
└───────────┬───────────────────┬─────────────────────┘
            │                   │
            ▼                   ▼
┌───────────────────┐  ┌──────────────────────────────┐
│   LLM Agents      │  │   Supporting Services        │
│  Analyst · Risk   │  │  LangChainProvider (Adapter) │
│  Strategy · Ethics│  │  Consensus Engine            │
│  Moderator +4 more│  │  RAG (ChromaDB)              │
└───────────────────┘  │  Agent Memory (SQLite)       │
                       │  Evaluator (LLM-as-Judge)    │
                       └──────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Persistence Layer            │
                    │  SQLite (aiosqlite) + Alembic │
                    │  ChromaDB (vector store)      │
                    └───────────────────────────────┘
```

### Layer Breakdown

| Layer                   | Tech                                                 | Purpose                                   | Key Design Choice                                           |
| ----------------------- | ---------------------------------------------------- | ----------------------------------------- | ----------------------------------------------------------- |
| **Presentation**  | Next.js 15, React 18, Tailwind, recharts             | Live debate viewer, analytics dashboard   | recharts for confidence drift visualisation                 |
| **API**           | FastAPI, Pydantic v2, slowapi                        | REST + SSE endpoints, input validation    | Pydantic at boundary = fail fast on bad input               |
| **Orchestration** | LangGraph StateGraph                                 | State machine driving the debate loop     | Checkpointing + conditional routing                         |
| **Agents**        | BaseAgent ABC + 5 core + 4 domain                    | Role-constrained LLM reasoning            | Template Method pattern for zero-boilerplate new agents     |
| **Services**      | LangChainProvider, Consensus, RAG, Memory, Evaluator | LLM abstraction, scoring, knowledge       | Each service is independently swappable                     |
| **Data**          | SQLite (aiosqlite), ChromaDB, Alembic                | Persistence, vector retrieval, migrations | Zero-infra stack, clear migration path to Postgres+Pinecone |

---

## 4. KEY COMPONENTS

### 4.1 BaseAgent (Template Method Pattern)

**What it is:**
An abstract base class that defines the skeleton of agent behavior. Subclasses just override the prompt-building methods.

**Three core methods every agent must expose:**

```
run()      → propose an initial position
critique() → cross-examine another agent's position
revise()   → update your position based on critiques received
```

**What the base class handles automatically:**

- KB enrichment — calls `_enrich_with_kb()` to fetch relevant RAG chunks
- Tool execution — web search, calculator, datetime
- Memory injection — prepends past lessons to system prompt
- Structured LLM calls — calls `LangChainProvider.ainvoke_structured()` with the right Pydantic schema

**Why this matters for interviews:**

> *"Adding a new domain agent requires overriding 3 prompt methods — zero boilerplate. The base handles all cross-cutting concerns."*

This is the Template Method pattern — define the invariant algorithm in the base class, let subclasses fill in the variant steps.

---

### 4.2 Agent Roles (Constrained Lens Design)

**Core insight:** Without role constraints, every LLM defaults to the same "balanced" generic answer. Constraints force genuine cognitive diversity.

| Agent               | Lens / Mandate          | May Do                                                                       | Must NOT Do                          |
| ------------------- | ----------------------- | ---------------------------------------------------------------------------- | ------------------------------------ |
| **Analyst**   | Facts & Data only       | Quantify, identify cause-effect, cite evidence                               | Propose strategy or solutions        |
| **Risk**      | Failure modes & threats | Categorise risks (financial/operational/reputational), stress-test proposals | Propose solutions or recommend paths |
| **Strategy**  | Actionable plans        | Propose alternatives, weigh trade-offs, recommend actions                    | Ignore risk data                     |
| **Ethics**    | Compliance & fairness   | Flag legal/ethical issues, issue a structured VETO (blocks consensus)        | Ignore business context entirely     |
| **Moderator** | Synthesis & arbiter     | Measure agreement, detect convergence, generate final decision               | Take sides, advocate a position      |

**Why role separation works:**

- The Analyst's refusal to recommend strategy **forces** the Strategy agent to fill that gap
- The Risk agent's adversarial mandate **forces** optimistic proposals to be stress-tested
- This is **Separation of Concerns applied to LLM reasoning**

**Follow-up Q:** *"What stops agents from breaking their roles?"*
→ Role constraint is in the system prompt. LLMs generally follow system prompt instructions reliably. Not 100% foolproof, but in practice the constrained lens produces meaningfully different outputs across agents.

---

### 4.3 LangChainProvider (Adapter Pattern)

**What it does:**
Provides a single abstraction layer over multiple LLM providers (Groq, OpenAI, Anthropic, Gemini).

**Key method:**

```python
await provider.ainvoke_structured(
    messages=...,
    schema=AgentPositionSchema  # Pydantic model
)
```

This uses `with_structured_output()` internally, returning a validated Pydantic object — never raw text.

**Why an Adapter?**

- Groq uses tool calling, OpenAI uses function calling, Anthropic uses tool_use — all different APIs, same interface to the rest of the system
- Switch provider = change one env var: `LLM_PROVIDER=openai`
- Enables per-agent model routing (Moderator on GPT-4o, others on Groq)

**Auto-retry:**

```python
with_retry(stop_after_attempt=2)
```

Two attempts with exponential backoff before returning `None`. Never crashes.

---

### 4.4 DebateGraph (LangGraph State Machine)

**What it is:**
The orchestration heart of the system. A directed graph where nodes are debate phases and edges define routing logic.

**Five phase nodes, plus a `hitl` node for supervised mode:**

```
proposals → critiques → revisions → convergence → finalize
```

**Conditional routing:**

- **Quick mode** skips the critique/revision nodes entirely via a one-line lambda edge
- HITL: when the gate stops a supervised debate, convergence routes to the `hitl` node, whose `interrupt()` pauses before finalize

**Checkpointing via `AsyncSqliteSaver`:**

- After every node execution, full graph state is serialized to SQLite
- On crash: reload the checkpoint and resume from the last completed node
- On HITL: state is frozen in `awaiting_approval` until human approval resumes it

**Node Factory Pattern:**
LangGraph nodes must be `async def node(state) → partial_state`. They can't accept extra arguments. Solution:

```python
def make_proposals_node(agents, emit_fn, persist_fn):
    async def proposals_node(state):
        # closes over agents, emit_fn, persist_fn
        ...
    return proposals_node
```

Dependencies captured at graph-build time via Python closure. Keeps the LangGraph API clean.

---

### 4.5 Consensus Engine (Evolution from V1 → V2 → Stance)

The Consensus Engine is a deterministic evaluation component that analyzes the outputs of all agents to determine whether the debate has sufficiently converged or should continue to another round. Think of it as the **deterministic decision engine** that evaluates whether the debate should continue or terminate based on predefined convergence rules.

Without a Consensus Engine, the debate would suffer from two major problems:

- **Stopping too early**, before agents have challenged and refined each other's reasoning.
- **Continuing indefinitely**, because there is no objective stopping criterion.

Rather than relying on intuition, the Consensus Engine **measures agreement between agents** and determines whether to **continue** or **finalize** the debate.

#### 4.5.1 Where it fits in the debate flow

At the end of every debate round:

```text
Agent Proposals
      ↓
Agent Critiques
      ↓
Agent Revisions
      ↓
Consensus Engine
      ↓
Consensus Reached?
      │
 ┌────┴────┐
 │         │
No         Yes
 │          │
 ▼          ▼
Next Round  Moderator
            ↓
      Final Decision
```

The **Consensus Engine** first evaluates the original outputs from all agents and determines whether the debate should continue or terminate using deterministic rules. Once consensus is reached, the **Moderator** synthesizes all agent positions into the final decision. This separation keeps the convergence logic deterministic, testable, and independent of LLM reasoning.

#### 4.5.2 Inputs & Outputs

**Inputs**

- Revised positions from all agents
- Agent confidence scores
- Each agent's structured `stance` (support / oppose / conditional / abstain)
- Previous round positions
- Debate configuration (thresholds, min/max rounds, agreement method)

**Outputs**

- `agreement_score` (and `agreement_method_used`)
- `should_continue`
- `termination_reason`

#### 4.5.3 Why three versions?

During testing, the initial implementation (V1) exposed an important correctness issue. V2 tried to fix it with text similarity and hit the same wall one level up. The fix that worked (V3) stops comparing text and asks each agent for its verdict.

---

##### V1 — Confidence-Based Consensus (Fast) ==>

```python
agreement_score = mean(agent.confidence_score for all agents)
```

The idea was simple:

> If all agents are highly confident, they have probably reached consensus.

##### Problem: False Consensus

Suppose two agents produce opposite recommendations:

| Agent   | Decision      | Confidence |
| ------- | ------------- | ---------: |
| Analyst | Expand        |       0.90 |
| Risk    | Do NOT Expand |       0.90 |

V1 computes:

```text
agreement_score = 0.90
```

Although the agents completely disagree, the system incorrectly concludes that consensus has been reached.

This revealed an important insight:

> **High confidence does not necessarily mean high agreement.**

---

##### V2 — Hybrid Consensus (Confidence + Semantic Agreement)==>

To address the false consensus problem, V2 combines **agent confidence** with **semantic agreement**.

```python
hybrid_score = (1 - w) × confidence_mean + w × semantic_similarity
```

where:

- **confidence_mean** measures how certain agents are about their own conclusions.
- **semantic_similarity** measures whether agents are actually reaching similar conclusions.
- **w** is a configurable weighting factor.

##### Semantic Agreement

Each agent's final position is embedded using **all-MiniLM-L6-v2 (384-dimensional embeddings)**.

The Consensus Engine then:

1. Generates embeddings for every agent position.
2. Computes pairwise cosine similarity.
3. Averages the similarity scores.
4. Combines the result with the confidence score.

This reduces false consensus when agents write about genuinely different things:

```text
High Confidence
		+                         ➔		Lower Hybrid Score		➔		Continue Debate
Low Semantic Similarity
```

**It does not solve it.** Embeddings are negation-blind: "Expand" and "Do NOT expand" share almost every word and embed close together, so the exact table above can still score high on cosine similarity. The word-overlap blend (`0.7 × confidence + 0.3 × rescaled Jaccard`) is negation-blind too, and its rescale window saturates: same-topic debates hit overlap 1.0, so the score collapses to `0.7 × confidence + 0.3`. A confident 2-vs-2 split (conf 0.80) scored 0.86 and passed even Thorough.

The root cause: text similarity, words or embeddings, measures **topic**. Role-bound agents word their agreement differently and share vocabulary when they disagree. We needed to measure **verdict**.

---

##### V3 — Stance Vote (the default) ==>

Each agent now declares its verdict as a structured field, the same pattern as the Ethics `veto`:

```text
stance ∈ { support, oppose, conditional, abstain }
```

The agreement score is the **confidence-weighted vote share of the largest stance group**:

```python
voters = [a for a in agents if a.stance not in (None, "abstain")]
if len(voters) < 2: fall back to the word-overlap blend
weight[stance] = sum(confidence of voters with that stance)
agreement = max(weight) / sum(weight)
```

- **What the stance is about:** round 1 → the decision the question asks for ("Should we expand?" → support = yes). Round 2+ → the Moderator's one-sentence `leading_proposal` from the previous round ("Proposal on the table: …").
- **`conditional` is its own group** — "yes, if X" is not a plain yes.
- **The Analyst abstains** (it makes no recommendations), so the default panel has three voters.
- **A veto means oppose** — an Ethics-class agent can't veto and support at once; the stance is coerced to `oppose`.

Back to the opening example:

| Agent    | Stance  | Confidence |
| -------- | ------- | ---------: |
| Strategy | support |       0.90 |
| Risk     | oppose  |       0.90 |

```text
agreement_score = 0.90 / 1.80 = 0.50   → no consensus
```

| Vote (similar confidence) | Score | Quick 0.60 | Standard 0.75 | Thorough 0.85 |
|---|---|---|---|---|
| 3 of 3 | 1.00 | ✅ | ✅ | ✅ |
| 2 of 3, dissenter unsure | 0.81 | ✅ | ✅ | ❌ |
| 2 of 3, dissenter confident | ~0.67 | ✅ | ❌ | ❌ |
| 2 vs 2 | ~0.50 | ❌ | ❌ | ❌ |

**What it doesn't solve:** the stance is self-reported, and a vague `leading_proposal` gives a vague vote. The gate in 4.5.4 still never relies on the score alone.

##### Why keep confidence?

The stance tells us **which way each agent lands**.

Confidence tells us **how certain each agent is about its own reasoning**.

Both signals are valuable:

- Confidence without agreement can produce false consensus.
- Agreement without confidence may indicate weak or uncertain reasoning.

That is why the vote is confidence-weighted: an unsure dissenter (0.40) pulls the score down less than a confident one.

---

##### Position Drift Detection

Agreement is not the only termination signal.

The Consensus Engine also checks whether agents are **still changing their positions** across rounds.

Instead of computing embeddings again, a lightweight **Jaccard word overlap** compares each agent's current position with its previous position.

```text
Round N		➔		Round N+1		➔		Jaccard Similarity
```

If the position drift is very small:

```text
drift < 0.05
```

the agents are considered to have **stopped moving**.

Low drift does **not** end the debate on its own. It is one of two ways to pass the "confidence has converged" signal (rule 5 in 4.5.4). The other gate signals, including agreement ≥ threshold, must still hold. If agents stall below the threshold, the debate runs on until `max_rounds`.

##### Why Jaccard instead of embeddings?

Position drift compares an agent **against its own previous response**, not against other agents.

A lightweight lexical comparison is sufficient to detect meaningful changes while avoiding additional embedding computations.

---

##### Choosing the agreement method

`AGREEMENT_METHOD` (server default) or `agreement_method` in the start request (per debate) picks which score drives the gate. The start form shows it as **Agreement: Vote / Text / Semantic**.

| Method | Formula | Role |
|---|---|---|
| `stance` (Vote) | confidence-weighted vote share | Default |
| `lexical` (Text) | `0.7 × mean confidence + 0.3 × rescaled word overlap` | Legacy, and the automatic fallback |
| `semantic` | `0.5 × mean confidence + 0.5 × mean pairwise cosine` | Experimental |

If the chosen method can't produce a score (fewer than two voters, stances missing in an old debate, embedding failure), the lexical blend takes over and the round records `agreement_method_used = "lexical"`. Every score is still emitted on the `synthesis` event, whichever one drives the gate.

##### Optional Semantic Similarity

Semantic similarity is **feature-flagged**:

```text
SEMANTIC_CONSENSUS_ENABLED=true
```

If enabled:

- sentence-transformers (~80 MB) computes the mean pairwise cosine every round, in a worker thread so it never blocks the SSE stream. It is logged and emitted as `semantic_agreement_score`, a **diagnostic**.
- the `semantic` agreement method becomes available. Without the flag (or the library), asking for it returns 422 and the UI greys the option out.

It does **not** change the agreement score unless a debate picks the `semantic` method. (It used to silently replace the whole blend; that changed once it was clear embeddings measure topic, not verdict.)

If disabled (the default), the embedding model is never loaded for consensus. This keeps the system lightweight for smaller deployments.

---

#### 4.5.4 The Consensus Gate (Actual Termination Logic)

The hybrid score alone **does not** determine whether the debate ends.

Instead, the Consensus Engine evaluates multiple convergence signals through `is_consensus_reached()`.

A debate terminates **only if all conditions are satisfied**:

1. **Agreement Score ≥ Threshold (Stance Vote by default)**

   - Ensures a confident majority of voting agents backs the same verdict, not just that agents are confident. Reduces **false consensus** caused by confidence alone or by shared wording (see 4.5.3).
2. **Minimum Rounds Completed ≥ `min_rounds`**

   - Prevents premature termination by ensuring agents have had enough opportunities to critique and revise each other's reasoning.
3. **Dissenting Agents ≤ 1**

   - A dissenter is a voting agent whose stance differs from the majority stance (the group with the largest summed confidence; ties go to head count, then oppose > conditional > support). Abstainers never dissent. So a confident opponent is a dissenter and an unsure ally isn't; the old rule (more than 0.20 below the mean confidence) had it backwards and is now only the fallback for debates without stances.
   - Rule 1 says how strong the majority is; Rule 3 caps how many agents it overrules. 2 supporters at 0.9 vs an oppose and a conditional at 0.2 score 0.82 on Rule 1 but have 2 dissenters.
4. **Open High/Critical Objections ≤ 2**

   - Counted **after revision**. Each revision replies to every critique it received with `addressed`, `rebutted` or `unaddressed`. A high/critical critique stays open when it is unaddressed or has no reply (e.g. the revision timed out); a `critical` one also stays open when it was only rebutted, because a critical issue needs a real change. Counted per critic→target pair. Three or more block consensus. In Quick mode critiques are skipped, so the count is always 0.
   - The replies are self-reported, but the loop checks them: next round the critic sees the revision and raises the issue again if it isn't really fixed.
5. **Confidence Has Converged**

   - Verifies that agents have settled, indicating further debate is unlikely to change the outcome.
   - Passes if either holds:
     - position drift < 0.05 (agents' wording barely changed since the previous round)
     - confidence spread (max − min) ≤ 0.15
   - The old "all agents ≥ 0.90" shortcut is off by default (`CONVERGENCE_ALLOW_ALL_CONFIDENT=false`): it was redundant with the spread check and read as "high confidence alone settles a debate".
6. **No Ethics Veto Stands**

   - An Ethics-class agent (Ethics, FinancialEthics, PatientSafety) can set a structured `veto`; while one stands in the current round, consensus can't be declared.

Only when **all six conditions** are satisfied is the debate declared converged and finalized. (The Moderator's own "should we continue?" opinion is advisory and only logged — the gate decides.) Each rule is written up in [`docs/consensus_engine.md`](../consensus_engine.md).

**How the agreement score is measured:** by default, the confidence-weighted vote share of the largest stance group (4.5.3, V3). The legacy lexical blend, `0.7 × mean confidence + 0.3 × position overlap`, is the fallback and the "Text" option; there, position overlap is the confidence-weighted Jaccard overlap of the agents' positions **rescaled** so 0.08 (unrelated positions) → 0 and 0.19 (the same stance reworded) → 1. Raw overlap between agents writing in different roles is low even when they agree; without the rescaling that score could never reach the thresholds. The `semantic` method (`0.5 × mean confidence + 0.5 × mean cosine`, no rescaling) is used only when a debate picks it.

This ensures that:

- a majority of voting agents back the same verdict, not just feel confident,
- enough discussion has occurred,
- at most one agent is overruled,
- few serious objections are still open after revision,
- agents have settled,

before the Moderator produces the final decision.

---

## 4.5.5 Overall Flow

```text
Agents
   │
   ▼
Consensus Engine
   │
   ├── agreement (stance vote)
   ├── semantic similarity (diagnostic)
   ├── dissent
   ├── confidence
   ├── position drift
   ▼
Consensus Reached?
   │
 ┌─┴─────────┐
 │           │
No           Yes
 │            │
 ▼            ▼
Next Round   Moderator
                 │
                 ▼
         Final Decision
```

---

### 4.6 RAG (Retrieval-Augmented Generation)

**The problem it solves:** Without RAG, agents only reason from LLM training data — which may be outdated, hallucinated, or irrelevant to the user's specific domain.

**RAG pipeline:**

```
User uploads PDF/TXT/MD
    → Text extraction
    → Sliding window chunking (1000 chars, 200 char overlap)
    → Embed with all-MiniLM-L6-v2
    → Store in ChromaDB
```

**At query time:**

```
Question text
    → Embed with all-MiniLM-L6-v2
    → Cosine similarity search in ChromaDB
    → Top-5 chunks with similarity ≥ 0.30
    → Inject as numbered context blocks into agent system prompt
```

**Why ChromaDB over Pinecone/FAISS?**

- Zero infrastructure — runs in-process, state persisted to disk
- ~5ms local retrieval vs ~100ms network for Pinecone
- Works completely offline
- Easy Pinecone swap later — same API shape

**Chunking rationale:**

- 1000 chars ≈ 200–250 words — meaningful semantic unit without overwhelming context
- 200 char overlap — prevents concept truncation at chunk boundaries

---

### 4.7 Agent Memory System

**Purpose:** Let agents learn from past debates. Without memory, every debate starts from zero — no institutional knowledge.

**How it works:**

```
After debate ends:
  → Each agent's final position (1-3 paragraphs) sent to LLM
  → LLM summarises to one-sentence lesson, e.g.:
     "Regulatory risk in Asian markets is consistently underestimated"
  → Store lesson in SQLite keyed by agent name
  → On next debate (enable_agent_memory=True):
     Retrieve 5 most recent lessons
     Prepend to agent system prompt
```

**Why LLM-summarised, not raw position?**

- Raw position: ~2000 tokens × 5 lessons = 10,000 tokens **polluting** the context
- Summarised lesson: ~30 tokens × 5 = 150 tokens of **distilled insight**
- The LLM extracts the transferable insight and discards the question-specific detail

**Follow-up Q:** *"How do you know which lessons are relevant?"*
→ Currently uses recency (last 5). A semantic similarity match between the new question and stored lessons would be a meaningful improvement.

---

### 4.8 SSE Streaming

**What it is:** Server-Sent Events — unidirectional server→client push over HTTP.

**Why SSE, not WebSockets?**

- Debate is a push-only stream: server pushes events, client only listens
- WebSocket's bidirectional capability is **unused overhead** for this use case
- SSE gives: built-in reconnection via `EventSource` API, `Last-Event-ID` header for recovery, HTTP/2 compatible, standard HTTP load balancers work without special config
- The only client→server message during a debate is HITL approval — handled via a regular `POST /debate/{id}/approve`

**Event types (in order):**

```
debate_started → round_started → phase_started → agent_output
→ critique_completed → synthesis → debate_completed → final_decision
(if HITL: approval_required injected before final_decision)
```

**Replay buffer:** Late-joining clients get buffered events so they see the full debate history, not just events from the moment they connected.

**Reconnection:** `Last-Event-ID` sent by `EventSource` → server replays from that event ID forward.

---

## 5. KEY DESIGN DECISIONS (Interview Gold)

| Decision                | Chosen                               | Over                       | Reason                                                     |
| ----------------------- | ------------------------------------ | -------------------------- | ---------------------------------------------------------- |
| **Orchestration** | LangGraph StateGraph                 | Procedural while-loop      | Checkpointing, HITL interrupts, conditional routing        |
| **Streaming**     | SSE                                  | WebSockets                 | Unidirectional, built-in reconnect, simpler                |
| **LLM Output**    | Pydantic`with_structured_output()` | Prompt-based JSON          | Type-safe, eliminates 40+ lines of parsing boilerplate     |
| **Database**      | SQLite                               | PostgreSQL                 | Zero infrastructure, sufficient for single-instance        |
| **Vector Store**  | ChromaDB (local)                     | Pinecone (cloud)           | Free, ~5ms local vs ~100ms network, works offline          |
| **Embeddings**    | sentence-transformers (local)        | OpenAI embeddings API      | No API cost, no latency, works offline                     |
| **Agent Design**  | Class-per-agent                      | Generic configurable agent | Type safety, custom logic per agent, individually testable |
| **State**         | In-memory + async DB persist         | Pure DB                    | Sub-ms SSE event access; DB as durable backup              |
| **Consensus**     | Deterministic + LLM advisory         | Pure LLM-judged            | Guaranteed termination, testable, reproducible             |
| **Data Access**   | Raw SQL + Alembic                    | ORM                        | Simple 4-table model, mostly JSON blob storage             |

### Deeper Explanations

**Why LangGraph over a while-loop?**
A while-loop approach like `while agreement < threshold: run_round()` has zero resilience — a crash loses all state and you restart from scratch. LangGraph's `AsyncSqliteSaver` checkpoints after every node. HITL interrupts with a while-loop would require complex manual state machines. LangGraph's `interrupt()` freezes the graph at a precise point and resumes from there. Conditional routing (skip critiques in Quick mode) is a one-line lambda versus complex conditional logic in a while-loop.

**Why Pydantic structured output?**
Free-form LLM text produces: "I'd say confidence is pretty high, maybe 8/10?" → unparseable for a consensus algorithm. Pydantic schema binding forces: `{"confidence_score": 0.82, "position": "...", "key_points": [...]}` — every time, validated. The algorithm gets a float, not a string interpretation.

**Why in-memory state + async DB persist?**
SSE events need to access current debate state at sub-millisecond latency for live streaming. A database round-trip (~1-5ms) would create noticeable jitter. In-memory = instant. The DB becomes the durable backup/recovery mechanism, not the primary state store.

---

## 6. DEBATE FLOW (End-to-End)

```
Step 1: User POST /debate/start-async
        → Pydantic v2 validates the request
        → DebateState object created with UUID thread_id
        → State stored in-memory + SQLite
        → BackgroundTask launched (non-blocking)
        → API returns {thread_id} immediately (< 50ms)

Step 2: Frontend subscribes to SSE stream
        → GET /debate/{thread_id}/stream
        → HTTP connection kept open
        → Replay buffer sends any already-emitted events

Step 3: LangGraph executes the debate graph
        ┌── Round N (repeats until convergence or max_rounds) ──┐
        │                                                       │
        │  PROPOSALS: All 4 agents run in PARALLEL              │
        │    → asyncio.gather() × 4 agents                      │
        │    → 45s timeout per agent (×1.5 if it uses tools)    │
        │    → Each agent queries RAG, injects memory           │
        │    → Returns structured AgentPosition (Pydantic)      │
        │                                                       │
        │  CRITIQUES: Each agent critiques all others           │
        │    → N agents × (N-1) critiques = O(N²) calls         │
        │    → Targeted: "Agent X said Y, here's why I disagree"│
        │                                                       │
        │  REVISIONS: Each agent reads critiques it received    │
        │    → Updates position, adjusts confidence score       │
        │    → "Given the Risk agent's point about X, I revise" │
        │                                                       │
        │  CONVERGENCE: consensus engine scores the round       │
        │    → Stance vote (confidence-weighted largest group)  │
        │    → Compute position drift vs. previous round        │
        │    → Moderator writes the round summary (advisory)    │
        └───────────────────────────────────────────────────────┘

        All six gate signals hold      → FINALIZE (consensus_reached)
        Else rounds = max_rounds       → FINALIZE (max_rounds_reached)
        Else                           → next round

Step 4: Finalize
        → Moderator generates FinalDecision (structured Pydantic)
          Fields: summary, recommendations, confidence_score,
                  risk_flags, dissenting_opinions, metadata

Step 5: Cleanup & Persistence
        → Each agent's final position → LLM summary → SQLite memory
        → Full debate state persisted to SQLite
        → SSE emits: debate_completed then final_decision

Step 6: Frontend renders
        → Final decision panel
        → Confidence drift chart (recharts line chart: score per round)
        → Analytics: rounds used, agents, LLM calls, convergence path
```

**Illustrative convergence trajectory (Thorough: threshold 0.85, min 3 rounds, max 6):**

```
Round 1: ~0.50  (agents just proposed, big disagreements)
Round 2: ~0.65  (critiques exposed weak points, positions adjusted)
Round 3: ~0.78  (min rounds met, still below 0.85 → continue)
Round 4: ~0.86  (above threshold and the other five signals pass → consensus_reached)
```

Standard caps at **2 rounds** (threshold 0.75, min 2), so a Standard debate always ends at round 2: `consensus_reached` if all six signals hold, otherwise `max_rounds_reached`.

---

## 7. DEBATE MODES

| Mode               | Max Rounds | Threshold | Critiques | Est. LLM Calls | Use Case                                |
| ------------------ | ---------- | --------- | --------- | -------------- | --------------------------------------- |
| **Quick** (default) | 2   | 0.60      | Skipped   | ~8             | Fast directional advice, time-sensitive |
| **Standard** | 2          | 0.75      | Yes       | ~20            | Balanced analysis, everyday decisions   |
| **Thorough** | 6          | 0.85      | Yes       | ~30+           | Deep strategic decisions, high-stakes   |

### Mode Selection Rationale

- **Quick mode** skips critiques entirely — proposals only, then direct convergence check. Useful when speed matters more than depth. It is the **default** (`DEFAULT_DEBATE_MODE`, configurable) so casual and test runs stay cheap; the UI pre-selects whatever the server's default is.
- **Custom** = Standard's full critique with your own round count (2–6) and threshold; it's stored as its own mode so analytics can tell it apart.
- **Thorough mode** runs more rounds before accepting convergence — forces agents to keep challenging each other until stronger agreement is found.
- The trade-off: **quality vs. cost vs. latency**. More rounds = more LLM calls = higher cost + slower response.

---

## 8. ML & ALGORITHMS

| Algorithm                             | Where Used                                          | Why This Algorithm                                                                       |
| ------------------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **LLaMA 3.3 70B (via Groq)**    | Agent reasoning, synthesis, memory summarisation    | State-of-the-art open model, free on Groq, 70B parameters = strong instruction following |
| **all-MiniLM-L6-v2**            | RAG embeddings, semantic similarity (V2 diagnostic) | 384-dim, fast local inference, strong semantic understanding for its size                |
| **Cosine similarity**           | Semantic diagnostic / `semantic` method (opt-in), RAG retrieval | Measures directional alignment of embeddings, scale-invariant                |
| **Confidence-weighted stance vote** | Live agreement score (default `stance` method)  | Measures verdict, not wording; negation-proof; O(N), no model download                   |
| **Jaccard word overlap**        | Lexical fallback score, position drift, simulation consistency | Lightweight, no ML needed; rescaled 0.08→0 / 0.19→1 for the score and consistency, raw for drift |
| **Confidence-weighted overlap** | Lexical agreement (blended 0.7 confidence / 0.3 overlap): "Text" option + fallback | Pairwise O(N²) but tiny N, provider-agnostic, no model download          |
| **LLM-as-Judge**                | Evaluator                                           | Flexible evaluation dimensions without labelled data                                     |
| **N-run simulation**            | Consistency testing                                 | Measures whether the system gives stable answers across runs                             |

### Deep Dive: Why `all-MiniLM-L6-v2`?

- **384 dimensions** — compact enough for fast cosine computation across agent pairs
- **Local inference** — no API call, no latency, no cost
- **Strong semantic understanding** — captures meaning, not just keywords
- **Known limitation:** Negation blindness — "should expand" and "should NOT expand" may have high cosine similarity because the model focuses on "expand" semantically. This is a documented sentence-transformer limitation, and why embeddings are a diagnostic rather than the agreement metric. MiniLM also truncates input at 256 word-pieces.

---

## 9. CHALLENGES & EDGE CASES

| Challenge                                  | How Handled                                                  | Why This Approach                                    |
| ------------------------------------------ | ------------------------------------------------------------ | ---------------------------------------------------- |
| **Agent timeout (> 45s, per phase)** | Skip that agent, debate continues with remaining             | One slow agent shouldn't block the whole debate      |
| **Structured output parse failure**  | `with_retry(stop_after_attempt=2)`, fallback to `None`   | Two chances; if both fail, graceful skip — no crash |
| **False consensus**                  | Six-signal gate: stance vote + dissent + open critiques + min rounds + veto. Agents declare a structured verdict, so "should" vs "should NOT" counts as a split, not agreement | Confidence and text similarity both miss verdicts    |
| **Stagnation / no progress**         | Drift < 0.05 only passes the "converged" signal; a stall below threshold runs to `max_rounds` | No standalone early stop: low drift alone isn't agreement |
| **Infinite oscillation**             | Hard ceiling:`max_rounds` stops debate                     | Safety net regardless of convergence                 |
| **KB empty or unavailable**          | `_enrich_with_kb()` returns prompt unchanged               | RAG is enhancement, not requirement                  |
| **Token limit exceeded**             | KB capped 5 chunks, tools 2KB, memory 5 lessons              | Prevents prompt ballooning, keeps inference fast     |
| **HITL user never approves**         | State persisted as`awaiting_approval` indefinitely         | Debate trails are auditable; no forced timeout       |
| **Concurrent debate isolation**      | Per-thread`asyncio.Lock`, unique LangGraph `thread_id`   | Two debates running simultaneously don't interfere   |
| **SSE client disconnect**            | `request.is_disconnected()` checked at least every 20 s (the keep-alive `ping` interval) + replay buffers released when a debate ends | Prevents zombie generators and unbounded memory |

### Most Critical Edge Case to Explain: False Consensus

This is the most technically interesting challenge because it's a correctness bug disguised as normal behavior. V1 would report high agreement even when agents were diametrically opposed — misleading the user into trusting a "consensus" that didn't exist. The fix took three steps. Blending confidence with word overlap helped, but overlap (and later embeddings) measures topic, so "should" vs "should NOT" still looked like agreement and a confident 2-vs-2 split passed Thorough. The fix that held: each agent declares a structured `stance`, and agreement is the confidence-weighted share of the largest stance group, so that split scores ~0.50. The gate also requires few dissenters, few high-severity critiques, a minimum number of rounds and no standing veto. Be honest about the limit: the stance is self-reported. The gate **reduces** false consensus but does not eliminate it.

---

## 10. SCALABILITY & PRODUCTION PATH

### Current Limitations (Be Honest in Interviews)

| Limitation                              | Impact                                          | Priority Fix  |
| --------------------------------------- | ----------------------------------------------- | ------------- |
| **SQLite: single-process writes** | Can't run multiple backend instances            | High          |
| **In-memory state**               | Not shareable across instances, lost on restart | High          |
| **ChromaDB: single-machine**      | Can't scale vector search horizontally          | Medium        |
| **No user auth/RBAC**             | Anyone can submit debates, read results (only admin actions need `X-Admin-Token`) | Critical (P0) |
| **Per-IP rate limit only**        | 30 req/min per client; no per-user quotas       | Medium        |

### Production Migration Path

```
Current (MVP)           →    Production-Ready
────────────────────────────────────────────────────
SQLite                  →    PostgreSQL (asyncpg)
In-memory state         →    Redis (state + locks + SSE pub/sub + rate limiting)
ChromaDB                →    Pinecone / pgvector
No auth                 →    JWT/OAuth2 + RBAC
No tracing              →    OpenTelemetry (distributed trace per debate)
FastAPI BackgroundTask  →    Celery/Dramatiq (durable task queue)
```

**Why this migration is low-risk:**

- `KnowledgeBase`, `LangChainProvider`, and CRUD layers are clean abstractions
- Swapping SQLite → PostgreSQL requires changing `DATABASE_URL` and import (`aiosqlite` → `asyncpg`)
- The business logic (debate flow, consensus, agents) is completely isolated from infrastructure

### Cost Analysis Per Debate

| Provider                       | Cost per Debate | Notes                          |
| ------------------------------ | --------------- | ------------------------------ |
| **Groq (LLaMA 3.3 70B)** | ~$0.006         | Near-free on current free tier |
| **GPT-4o (OpenAI)**      | ~$0.35–$0.70   | Standard mode: ~20 LLM calls   |
| **GPT-4o Turbo**         | ~$0.15–$0.30   | Cheaper per-token than GPT-4o  |

**Key insight:** LLM costs dominate infrastructure costs by **10–100×**. Optimising LLM spend matters more than optimising server cost.

**Cost optimisations available:**

1. Per-agent model routing — Moderator on GPT-4o, others on Groq
2. Quick mode — skips critiques, ~60% fewer calls
3. Early termination — stop before `max_rounds` once the gate passes (round 1 only in Quick mode, where `min_rounds` is 1)
4. Caching — for repeated identical questions

---

## 11. EVALUATION METRICS

### Process Metrics (measured during debate)

| Metric                       | Formula / Method                           | What It Tells You                                 |
| ---------------------------- | ------------------------------------------ | ------------------------------------------------- |
| **Agreement Score V1** | `mean(agent.confidence)`                 | Fast convergence proxy, can be fooled; still emitted as `confidence_agreement_score` |
| **Agreement Score (live, stance)** | `max(group confidence) / total voter confidence` | Default gate input: confidence-weighted share of the largest stance group; emitted as `stance_agreement_score` with a `stance_tally` |
| **Agreement Score (lexical)** | `0.7×confidence_mean + 0.3×normalize(cw_overlap)` | "Text" option and the fallback when < 2 agents vote; overlap emitted as `position_agreement_score` |
| **Agreement Score V2** | `0.5×confidence_mean + 0.5×cosine_sim` (opt-in) | Meaning-level overlap; still negation-blind. Diagnostic (`semantic_agreement_score`) unless the `semantic` method is chosen |
| **Score change**       | `score_round_N − score_round_N-1`        | How fast the debate is converging                 |
| **Position Drift**     | `1 − Jaccard(position_N, position_N-1)`  | How much agents are still updating their thinking |

### Output Quality Metrics (LLM-as-Judge, measured post-debate)

| Metric                   | What It Measures                                         | Range |
| ------------------------ | -------------------------------------------------------- | ----- |
| **Completeness**   | Does the decision cover all aspects of the question?     | 0–1  |
| **Consistency**    | Are there internal contradictions in the final decision? | 0–1  |
| **Actionability**  | Can a human act on the decision concretely?              | 0–1  |
| **Risk Awareness** | Are risks acknowledged and quantified?                   | 0–1  |

### Stability Metric (simulation-based)

| Metric                           | Method                                                          | Interpretation                                                |
| -------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------- |
| **Simulation Consistency** | Run same question N times → cosine_similarity(final decisions) | > 0.85 = reliable; < 0.65 = unreliable for this question type |

### Why Three Layers of Evaluation?

1. **Process metrics** tell you if the debate *converged well*
2. **Output quality metrics** tell you if the final *decision is usable*
3. **Stability metrics** tell you if the system is *deterministic enough to trust*

These are complementary — a debate can converge quickly but produce a low-quality decision, or vice versa.

---

## 12. MENTAL MODELS & ANALOGIES

These are powerful for making complex ideas accessible in interviews.

| Analogy                             | Maps To                                                               | Use When Asked About                                           |
| ----------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------------------- |
| **Corporate boardroom**       | CEO asks → CFO/CRO/VP/Counsel provide analysis → Chair synthesises  | Why multiple agents, why rounds, why a moderator               |
| **Judicial system**           | Opening statements → Cross-examination → Rebuttal → Judge's ruling | Why critique and revision phases matter                        |
| **Peer review**               | Submit paper → Reviewers critique → Author revises → Published     | Why not single-shot generation, quality assurance              |
| **GPS vs written directions** | LangGraph state machine vs a for-loop                                 | Why state machine over procedural code                         |
| **Bridge structure**          | Strength from arrangement of beams, not one magical beam              | Where quality comes from: structure + constraints, not one LLM |

### How to Use These in Interviews

- Interviewer asks: "Why not just use one LLM call?"
- You say: "Imagine asking one person to be the CFO, CRO, and General Counsel simultaneously — you'd get a single compromised view. AgentBoard is the boardroom: each specialist argues their angle, and the Chair synthesises the best decision from the debate."

---

## 13. TECH STACK SUMMARY

| Category              | Technology                                                                                      | Why Chosen                                                        |
| --------------------- | ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **Backend**     | Python 3.11+, FastAPI, Pydantic v2, LangChain, LangGraph                                        | Async, fast, type-safe, rich LLM ecosystem                        |
| **LLM**         | Groq (LLaMA 3.3 70B default), OpenAI (GPT-5.5), Anthropic (Claude Opus 4.8), Gemini (3.5 Flash) | Multi-provider flexibility, Groq for cost/speed                   |
| **Embeddings**  | sentence-transformers (all-MiniLM-L6-v2, local)                                                 | Free, fast, no API dependency, offline capable                    |
| **Vector DB**   | ChromaDB (local, persistent)                                                                    | Zero infra, fast, simple Pinecone migration path                  |
| **Database**    | SQLite (aiosqlite) + Alembic migrations                                                         | Zero infra, sufficient for single-instance, easy Postgres swap    |
| **Frontend**    | Next.js 15, React 18, TypeScript, Tailwind CSS, recharts                                        | SSR capable, strong TypeScript ecosystem, recharts for charts     |
| **Streaming**   | Server-Sent Events (SSE)                                                                        | Perfect for unidirectional push, simpler than WebSockets          |
| **Agent Tools** | DuckDuckGo (web search), numexpr (calculator), datetime                                         | Real-time data, safe arithmetic (no eval()), time context         |
| **Testing**     | pytest, pytest-asyncio, unittest.mock                                                           | Standard Python testing, async support                            |
| **Logging**     | structlog (JSON structured logging)                                                             | Machine-parseable, compatible with log aggregators (Datadog, ELK) |

---

## 14. KEY CODE PATTERNS

| Pattern                        | Where Used                      | What It Solves                                                      |
| ------------------------------ | ------------------------------- | ------------------------------------------------------------------- |
| **Template Method**      | `BaseAgent`                   | Skeleton algorithm in base; subclasses only override prompt methods |
| **Adapter**              | `LangChainProvider`           | Provider-agnostic LLM interface; swap backend with one env var      |
| **Factory (closure)**    | `DebateGraph` node factories  | Capture dependencies at graph-build time for LangGraph callables    |
| **Service Locator**      | `AgentRegistry`               | Decouple agent creation/config from the orchestrator                |
| **Graceful Degradation** | Consensus engine, KB, tools     | Stance/semantic fall back to lexical, KB returns unchanged prompt, tool skip on timeout |
| **Feature Flags**        | Semantic similarity, agreement method, RAG, memory | Enable/disable via env vars without code changes   |

### Pattern Explanations for Interviews

**Template Method (BaseAgent):**

```
BaseAgent.run():
    prompt = self._build_proposal_prompt()   # ← subclass overrides this
    enriched = self._enrich_with_kb(prompt)  # ← base handles this
    return await self._invoke_llm(enriched)  # ← base handles this

AnalystAgent._build_proposal_prompt():
    return "You are a data analyst. Only cite evidence. Never recommend..."
```

Subclass just writes prompts. Base handles all the machinery.

**Adapter (LangChainProvider):**

```
# Same call, different provider configured:
await provider.ainvoke_structured(messages, schema=AgentPosition)
# Internally routes to: Groq tool calling / OpenAI function calling / Anthropic tool_use
```

**Factory (closure) pattern:**

```python
# Node can't take extra args in LangGraph, so we use a factory:
def make_proposals_node(agents, emit_fn, persist_fn):
    async def proposals_node(state: DebateState):
        # agents, emit_fn, persist_fn captured via closure
        results = await asyncio.gather(*[a.run(state) for a in agents])
        await emit_fn("agent_output", results)
        return {"agent_positions": results}
    return proposals_node
```

---

## 15. WHAT I'D DO DIFFERENTLY (Honest Self-Reflection)

Interviewers love this question — it shows maturity, self-awareness, and production thinking.

| What                                       | Why I'd Change It                                                      | What I Learned                                                 |
| ------------------------------------------ | ---------------------------------------------------------------------- | -------------------------------------------------------------- |
| **Add authentication from day one**  | Security is never "add it later" — it's architectural                 | Auth touches every endpoint; retrofitting costs 3× as much    |
| **Start with PostgreSQL**            | SQLite→Postgres migration cost 2 days of work                         | No-infra simplicity isn't worth the migration pain             |
| **Add OpenTelemetry tracing**        | Debugging multi-agent execution without distributed tracing is painful | You can't reason about async multi-agent flows from logs alone |
| **Explicit token budget management** | Check prompt length before LLM calls, not after                        | Silent truncation is a hidden quality bug                      |
| **User feedback loop**               | We measure process quality but not outcome quality                     | Did the decision actually help? We have no idea                |

### Bonus: What I'd Keep the Same

- **LangGraph** — the checkpointing + HITL + conditional routing justify the learning curve
- **Pydantic structured output** — the first thing that obviously worked perfectly
- **SSE over WebSockets** — simpler is better when bidirectionality isn't needed
- **ChromaDB for MVP** — zero-infra RAG is perfect for prototyping, migration path is clear

---

## 16. THEORETICAL CONCEPTS & FUNDAMENTALS (Deep Dives)

> When an interviewer drills past "what you built" into "*why does this work?*", these are the theory anchors. Each one is explained from scratch so you can **teach** it, not just name-drop it: **plain words → the theory → how AgentBoard uses it → a one-liner to say out loud.**

### 16.1 Ensemble Theory — Why Multiple Agents Beat One

**In plain words:** Ask one expert and you get one opinion — with all of that expert's blind spots baked in. Ask five *different* experts and combine their views, and the individual mistakes tend to cancel out while the shared signal survives. AgentBoard is that idea applied to LLMs.

**The theory:** An *ensemble* is a group of models whose outputs are combined. The math comes from the **bias–variance decomposition** — any model's error splits into *bias* (consistent, systematic error) and *variance* (random, run-to-run error). If you average several models whose errors are *independent*, the random part shrinks while the systematic part stays, so the combination beats a typical single member. Two classic results make this concrete:

- **Condorcet Jury Theorem:** if each voter is independent and even slightly better than a coin flip, the chance the *majority* is correct climbs toward 100% as you add voters.
- **Diversity Prediction Theorem:** crowd error = (average individual error) − (diversity of the crowd). More diversity literally subtracts from the error.

The catch in both is the word **independent**. If the members make the *same* mistakes (correlated errors), averaging buys you nothing.

**In AgentBoard:** the five agents are the "members," and the Moderator's synthesis + the consensus gate are the "aggregation." The trap is that five copies of the same LLM are *not* independent — they'd just rephrase one answer. So diversity is **engineered**: each agent gets a constrained, non-overlapping lens (the Risk agent may only surface risks; the Analyst may not make recommendations). That forced disagreement is what makes the ensemble actually pay off.

**Say this:** *"Ensembles only help when members are diverse and independent — so the hard part isn't adding agents, it's forcing them to genuinely disagree."*

### 16.2 Consensus Theory — Agreement as a Measured Signal

**In plain words:** In distributed systems, "consensus" means getting a bunch of computers to agree on one value even if some crash. That is **not** AgentBoard's problem. Here, consensus means: looking at five opinions, *how much do they really agree, and should I trust that agreement enough to stop the debate?* It's a measurement, not a fault-tolerant commit protocol.

**The theory:**

- Classic consensus (Paxos, Raft) is a *coordination protocol* — binary and safety-critical: every node must commit to the same value.
- AgentBoard does **measured consensus** — each agent casts a structured verdict (support / oppose / conditional / abstain), the system *scores* the confidence-weighted share of the largest group, then decides whether that's good enough to stop.
- The danger is **false consensus**: a naive system shouts "agreement!" the moment agents merely *sound* confident — but confidence ≠ correctness, and a high *average* confidence can hide two agents flatly contradicting each other. Text similarity doesn't save you either: "expand" and "don't expand" read as the same topic.
- The fix borrows the database idea of a **quorum** (you need several independent confirmations, not one). A debate converges only when **all six** signals hold: (1) agreement (stance vote) ≥ threshold, (2) at least `min_rounds` completed, (3) ≤ 1 dissenter (agent voting against the majority stance), (4) ≤ 2 high/critical critiques still open after revision, (5) confidence has converged (low drift or spread ≤ 0.15), (6) no Ethics veto stands. Each signal closes a loophole the others miss.
- **Convergence vs. termination** (a distinction interviewers love): *convergence* = the gate is genuinely satisfied. *Termination* = the loop stopped for **any** reason, including just hitting the round limit. Reporting "max rounds reached" as if it were "consensus" is exactly the false-consensus bug.

**Say this:** *"I treat consensus as a calibrated score behind a multi-signal quorum gate, not a boolean — confidence alone can't end a debate."*

### 16.3 State Machines & Graph Orchestration

**In plain words:** You *could* run the debate with an ordinary loop ("for each round: do proposals, then critiques…"). But the moment you need to **pause** mid-debate for human approval and **resume** later — or recover after a crash — a plain loop falls apart, because there's no saved place to continue from. A **state machine** gives every step a name and saves the state at each step, like a save point in a video game.

**The theory:** Model the workflow as a **directed graph / finite-state machine**: *nodes* are steps, *edges* are transitions, and a *conditional edge* picks the next node from the current state. This cleanly separates two things a loop tangles together:

- the **control plane** — *what runs next* (the graph), and
- the **data plane** — *the state being transformed* (one `DebateState` object).

That separation unlocks **checkpointing** (save state at each node → pause/resume), **replayability**, **deterministic routing wrapped around non-deterministic LLM work**, and clean branching — none of which a `for`-loop gives you for free.

**In AgentBoard:** a LangGraph `StateGraph` with nodes `proposals → critiques → revisions → convergence`, conditional edges (loop again vs. finalize), a SQLite **checkpointer**, and an `interrupt()` for human-in-the-loop.

**One term to define out loud — idempotency:** an operation is *idempotent* if running it twice has the same effect as running it once. Resuming from a checkpoint can re-enter a node, so node logic must be safe to re-run — which is why the HITL pause lives in its **own** `hitl` node, so a resume never accidentally re-runs the Moderator's synthesis.

**Say this:** *"A state graph lets me wrap non-deterministic LLM nodes in deterministic, resumable control flow — that's what made pause/resume and HITL almost free."*

### 16.4 Concurrency — Async, Fan-out/Fan-in, Cancellation

**In plain words:** Each LLM call spends most of its time *waiting* for the model's server to answer — the CPU sits idle. If you call five agents one after another, you wait five times in a row. Instead you fire all five at once and wait for the slowest, so total time drops from "sum of five" to "the longest one."

**The theory:**

- Work is either **CPU-bound** (busy calculating) or **I/O-bound** (waiting on network/disk). LLM calls are I/O-bound.
- For I/O-bound work the efficient model is an **async event loop**: one thread runs many *coroutines*, and whenever one is waiting it hands the CPU to another (**cooperative scheduling**) — no threads, no locks around CPU work.
- `asyncio.gather` is **structured fan-out/fan-in**: *fan-out* = launch N coroutines at once; *fan-in* = await them all and collect the results.
- Each task gets its own **timeout** (`asyncio.wait_for`) so a slow one is bounded, and **cancellation** arrives as a `CancelledError` exception inside the coroutine, which you catch to clean up.

**In AgentBoard:** within a phase, all agents run concurrently via `gather` with per-phase timeouts (45 s; tool-using agents get 1.5× since they also run a web search); phases themselves run sequentially (critiques need the proposals first). Cancelling a debate raises `CancelledError` in the runner → status `cancelled`, persisted, terminal SSE event.

**Say this:** *"Agents fan out concurrently inside a phase, phases stay sequential, and every call is individually timeout-bounded so one slow agent can't stall the round."*

### 16.5 Streaming & Delivery Semantics

**In plain words:** A debate takes a minute or two, and the user shouldn't stare at a spinner. So the server *pushes* each event (a proposal appeared, a critique landed) to the browser the instant it happens — like a live sports ticker. The browser only listens; it never needs to talk back on that channel, which is why **SSE** is the right tool, not WebSockets.

**The theory:**

- **SSE (Server-Sent Events):** one long-lived HTTP response the server keeps writing to; the browser's `EventSource` receives a stream of events. One-directional (server → client).
- **WebSockets:** a separate, *two-way* protocol — more powerful but more moving parts. Overkill when the client only needs to listen.
- Streaming concepts worth naming: **backpressure** (don't flood a slow consumer), **replay buffer** (keep recent events so a late or reconnecting client can catch up), **delivery semantics** (chasing "exactly-once" is hard; "at-least-once **+** make applying an event *idempotent*" is simpler and just as correct), and **liveness** (heartbeats detect a dead connection).

**In AgentBoard:** debate nodes emit typed events into an `asyncio.Queue`; the SSE endpoint drains it to the client. A **replay buffer** lets a reconnecting client re-receive past events, and the frontend folds events through a **pure reducer** so replaying the same event twice is harmless (idempotent). If SSE keeps failing, the UI shows **"Connection lost"** with an in-place Reconnect (the debate keeps running server-side), and a finished debate always loads from the REST API.

**Say this:** *"SSE because the debate is a one-way firehose — and I make it robust with a replay buffer, an idempotent reducer, and a REST fallback."*

### 16.6 RAG, Embeddings & Vector Search

**In plain words:** An LLM only "knows" what was in its training data. To make it use *your* documents, you can't paste a whole PDF into every prompt. Instead you pre-index the docs, and at question time fetch just the few most-relevant paragraphs and hand those to the model — an open-book exam instead of relying on memory.

**The theory:**

- An **embedding** is a function that turns text into a list of numbers (a *vector*) positioned so that texts with similar *meaning* land near each other in space.
- "Near" is measured by **cosine similarity** — the cosine of the angle between two vectors (1 = same direction, 0 = unrelated).
- **The RAG pipeline:** split documents into **chunks** → embed each chunk → store the vectors in an index. At query time: embed the query → retrieve the **top-k** nearest chunks above a **similarity threshold** → inject them into the prompt as grounding context.
- Why it cuts **hallucination**: the model is handed real text to cite instead of guessing from parametric (training-baked) memory.

**In AgentBoard:** a ChromaDB vector store + `all-MiniLM-L6-v2` embeddings (384 numbers per chunk), chunk size 1000 with 200 **overlap** (overlap stops an idea being cut in half at a boundary), `top_k = 5`, similarity threshold 0.30, cosine distance.

**Why MiniLM:** it's small (~80 MB), 384-dim, and runs on a CPU — the classic **quality vs. latency vs. cost** tradeoff. You don't need a giant 1536-dim model just to find the right paragraph.

**Say this:** *"RAG grounds the agents in retrievable facts; cosine similarity over small MiniLM embeddings is the cheap, good-enough retriever."*

### 16.7 LLM Internals You Should Be Able to Defend

**In plain words:** A handful of facts about how LLMs actually behave explain half of AgentBoard's design choices.

- **Structured output / constrained decoding:** normally an LLM returns free-form text and you have to parse it — fragile. `with_structured_output()` forces the model to fill in a typed schema (using the provider's tool-calling / function-calling / JSON mode under the hood). You get back a *validated object or a clean retry* — never "hope the regex works."
- **Temperature & sampling:** at each step the model produces a probability for every possible next token. **Temperature** reshapes those probabilities — low temperature makes it pick the most likely token (more deterministic, repeatable), high temperature adds randomness (more variety). Some newer models (Opus 4.7+/Fable, `gpt-5*`) reject the `temperature` parameter, so `_sampling_kwargs()` omits it for them so the call doesn't 400.
- **Context window & token economics:** a **token** is roughly ¾ of a word; the **context window** is the max tokens a model can read at once. Every chunk, memory, and critique you inject eats into that window *and* costs money (you pay per input **and** output token). That's why every injection point has a hard cap, and why cheap Groq Llama is the default while frontier models are opt-in.
- **Calibration:** a model's stated confidence ("0.9") is **not** the probability it's right — LLMs are often *confidently wrong*. That single fact is why the consensus gate never trusts confidence by itself.

**Say this:** *"Structured output is the single highest-leverage reliability decision — it moved fragility from runtime text-parsing to schema validation."*

### 16.8 Reliability & Resilience Patterns

**In plain words:** Things on the internet fail at random — a request times out, a server is briefly overloaded. The trick isn't preventing every failure; it's making sure one failure doesn't take everything else down. A few standard patterns do exactly that.

- **Retry with exponential backoff (+ jitter):** if a call fails for a *transient* reason, wait and try again — but wait *longer each time* (`base · 2ⁿ`) and add a little randomness (**jitter**) so a thousand clients don't all retry on the same beat (a "thundering herd"). Used in the frontend `withRetry` to ride out backend **cold starts**, and in structured-output parsing (`stop_after_attempt = 2`).
- **Graceful degradation / fail-open:** when a non-essential part fails, return a *weaker* result instead of an error. A missing agent, empty KB, or unavailable embedding model degrades quality but doesn't crash the request — RAG is an *enhancement*, not a dependency.
- **Timeouts + bulkheads:** time-box every external call, and isolate each one so a single failure can't sink the whole operation. (A **bulkhead** is the shipbuilding metaphor: sealed compartments so one flooded section doesn't sink the ship.)
- **Fallback chains:** always have a Plan B — a finished debate loads from the REST API without a live stream; a lost stream shows "Connection lost" with Reconnect (the debate keeps running server-side); live templates/agents → built-in defaults.

**Say this:** *"Every external dependency is timeout-bounded and has a fallback — the system fails soft, never hard."*

### 16.9 Data Consistency — The Dual Store

**In plain words:** While a debate is running, its data lives in memory because that's fast. In parallel it's saved to a database for history — but that save is "fire and forget," so if the database is briefly slow, the live debate never waits on it.

**The theory:** AgentBoard runs a **dual store** — an **in-memory store** (fast, authoritative for the *active* debate) plus **fire-and-forget SQLite persistence** (durable, for history/recovery). This is a deliberate **eventual-consistency** tradeoff: the database may lag the in-memory truth by a few milliseconds, which is fine because nothing reads the database for a *live* debate. In **CAP-theorem** terms — Consistency, Availability, Partition-tolerance, of which you can't fully have all three — a single-node MVP chooses the *availability and latency* of the live path over *strict durability* of every single event.

**Say this:** *"Memory is the hot path, SQLite is the cold path — persistence is best-effort so a slow write never blocks the debate."*

### 16.10 Evaluation Theory — Judging Non-Deterministic Output

**In plain words:** How do you grade an AI's answer when there's no single correct answer? You can't compare it to a fixed string. So AgentBoard grades on *structure and process* — did agents converge, does the decision cover the question, is it self-consistent — and uses a second LLM as a rubric-based judge.

**The theory:**

- **LLM-as-judge:** a separate model scores an output against a fixed rubric (completeness, consistency, actionability, risk awareness). Cheap and scalable, and it correlates reasonably with human ratings — but the judge has its own biases, so treat it as a *signal*, not ground truth.
- **Process vs. outcome metrics:** AgentBoard measures **process** quality *during* the debate (convergence, agreement, confidence drift) and **output** quality *after* (judge scores). It honestly does **not** measure real-world **outcome** quality (did the decision actually help the user?) — naming that gap is itself a maturity signal.
- **Quantifying non-determinism:** because the same question can yield different answers, **simulation** runs it N times and measures the variance in decisions/agreement — turning "is it stable?" into an actual number.

**Say this:** *"I evaluate at three layers — process, output, and stability — and I'm explicit that real-world outcome quality is still unmeasured."*

---

## 17. FAILURE MODES & HOW TO RESOLVE

> **The single most important interview section.** Senior interviewers don't ask "does it work?" — they ask "*what happens when it doesn't?*". This section is written so a first-time reader can follow exactly what breaks and why the system survives it.

### 17.0 How to answer ANY failure question (the structure)

Whatever failure they throw at you, answer in the same **four beats, in order**:

1. **What breaks** — the symptom a user or operator actually sees.
2. **Why** — the root cause.
3. **How it's handled today** — what AgentBoard really does (this is where you show **isolate → degrade → recover**).
4. **How I'd harden it** — the production upgrade (shows you know the system isn't finished).

And the one sentence that ties every answer together — the **failure philosophy**:

> **Isolate** every failure with timeouts and per-call boundaries, **degrade** to a weaker-but-valid result instead of crashing, and **recover** with retries, replays, and checkpoints.

Below, each layer gets a plain-English walk-through of its headline failures, followed by a quick-reference table.

---

### 17.1 LLM

| col1 | col2 | col3 |
| ---- | ---- | ---- |
|      |      |      |
|      |      |      |

### -Layer Failures

These are failures of the model calls themselves — the most common in any LLM app.

**① Agent call times out.** *What happens:* one agent's LLM call hangs — maybe the provider is slow or the prompt is huge. *Why it's dangerous:* the phase launches all agents concurrently and waits for them together, so without a guard one stuck agent would freeze the entire round. *How it's handled:* every call is wrapped in `asyncio.wait_for` with a per-phase timeout (45 s; tool-using agents get 1.5× because they also run a web search). If it trips, AgentBoard emits an `agent_timeout` event, **drops just that one agent**, and the round continues with the rest; the Moderator is told the round is degraded so its synthesis accounts for the missing voice. That's graceful degradation — a 4-agent answer beats a failed request. *How I'd harden it:* timeouts tuned per provider, and speculatively re-issuing a slow call to a faster fallback model.

**② Malformed structured output.** *What happens:* even with schema enforcement, a model occasionally returns something that doesn't fit the Pydantic schema. *How it's handled:* `with_structured_output()` plus an automatic retry (`stop_after_attempt = 2`) gives the model a second chance; if both attempts fail, that agent's output for the phase becomes `None` and is skipped, with the bad payload logged for debugging. *Why it's safe:* one bad agent is not a crashed debate. *How I'd harden it:* a third "repair" attempt that feeds the malformed text back with the schema and asks the model to fix it.

**③ Provider rejects a parameter.** *What happens:* some models (Opus 4.7+/Fable, `gpt-5*`) return HTTP **400** if you send a `temperature`. *How it's handled:* `_sampling_kwargs()` detects those models and simply omits `temperature`, so the call never errors. *How I'd harden it:* a central per-model **capability registry** so unsupported parameters are stripped in one place instead of being special-cased.

**Quick reference:**

| Failure                                    | Symptom                                                  | How AgentBoard handles it                                                                                                                                | How I'd harden it                                                                                          |
| ------------------------------------------ | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| **Agent call times out**             | One agent hangs (slow provider, big prompt)              | `asyncio.wait_for` (45 s; tool agents 1.5×) → emit `agent_timeout`, drop that agent, continue with the rest; Moderator notes the round is degraded | Per-provider adaptive timeouts; speculative re-issue to a faster fallback model                            |
| **Malformed structured output**      | Model returns text that doesn't fit the schema           | `with_structured_output()` + retry `stop_after_attempt(2)` → on double failure return `None` and skip that agent's output (logged with payload)   | Add a repair prompt ("fix this to match the schema") as a third attempt before giving up                   |
| **Provider rejects sampling params** | HTTP 400 on`temperature` (Opus 4.7+/Fable, `gpt-5*`) | `_sampling_kwargs()` omits `temperature` for those models so the call never 400s                                                                     | Capability registry per model so unsupported params are stripped centrally                                 |
| **Rate limit (429) from provider**   | Burst of calls throttled                                 | Raised as`LLMRateLimitError` with a dedicated handler → clean 429 to client; frontend `withRetry` backs off                                         | Token-bucket client-side limiter + request queue; multi-key rotation                                       |
| **All agents fail in a phase**       | No proposals/revisions produced                          | Round has no outputs → surfaced as an error/degraded path rather than fabricating a decision                                                            | Circuit-breaker: after K consecutive provider failures, fail fast with a clear message instead of retrying |
| **Hallucinated / ungrounded claims** | Confident but wrong facts                                | RAG grounding + adversarial Risk/Ethics critique pressure-tests claims; Ethics can**veto**                                                         | Citation enforcement (require source spans for factual claims); groundedness scoring                       |

### 17.2 Orchestration-Layer Failures

These are failures of the debate *logic* — the most interesting ones to discuss, because they're correctness bugs, not crashes.

**① False consensus (the headline bug).** *What happens:* the system reports high agreement when the agents are actually opposed, so the user trusts a "consensus" that doesn't exist. *Why:* the earlier versions measured agreement from confidence and word overlap (and optionally embeddings), which stay high even when two agents *confidently* say opposite things: text similarity measures topic, not verdict. *How it's handled:* each agent now declares a structured `stance`, and agreement is the confidence-weighted share of the largest stance group. The **hybrid six-signal gate** only converges when that agreement, min-rounds, at most one agent voting against the majority stance, few serious critiques still open after revision, settled agents (low drift or tight confidence spread) *and* no standing Ethics veto all hold at once. Confidence by itself can never end a debate, and a 2-vs-2 split can't pass any mode. *What it doesn't fix:* the stance and critique replies are self-reported, so an agent that argues one way and labels it the other still fools the vote; the gate **reduces** false consensus rather than eliminating it. *How I'd harden it:* an NLI check that the position text actually matches the declared stance, or a calibrated agreement model trained on human-labeled debates.

**② Non-convergence.** *What happens:* the agents argue and never reach the agreement threshold. *How it's handled:* a hard `max_rounds` ceiling stops the loop, and the debate still returns a decision — but honestly labeled `max_rounds_reached` with low agreement, rather than pretending it converged. *Why this matters:* it's the difference between an honest "we couldn't fully agree" and a misleading fake consensus. *How I'd harden it:* an adaptive round budget based on question difficulty, plus escalation to a human.

**③ Stagnation (wasted rounds).** *What happens:* the agents stop changing their positions but still haven't hit the threshold — continuing would just burn money and time. *How it's handled:* there is **no standalone early stop**. Position **drift** below 0.05 is one of two ways to pass the "confidence converged" signal, and every other gate signal, including agreement ≥ threshold, must still hold. A stall below the threshold runs on until `max_rounds` and ends `max_rounds_reached`, so the cost is capped by the round limit, not by drift. *How I'd harden it:* stop a stalled debate early (honestly labelled as no consensus), and tell a true stall apart from oscillation (agents flip-flopping between two positions).

**Quick reference:**

| Failure                                | Symptom                                       | How AgentBoard handles it                                                                                                    | How I'd harden it                                                         |
| -------------------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **False consensus**              | High agreement reported for opposed positions | Stance vote inside the six-signal gate — confidence alone can't converge, a split vote can't pass; stance is self-reported | NLI check of position vs. declared stance; calibrated agreement model trained on labeled debates |
| **Non-convergence**              | Agents never reach the threshold              | Hard`max_rounds` ceiling → `termination_reason = max_rounds_reached`, decision still produced with honest low agreement | Adaptive round budget by question difficulty; escalate to HITL            |
| **Stagnation (no progress)**     | Positions stop moving but threshold unmet     | Drift < 0.05 only passes the "converged" signal; with agreement below threshold the debate runs to `max_rounds`               | Early-stop a true stall; detect oscillation vs. stall separately          |
| **Concurrent debates interfere** | State bleed between simultaneous debates      | Unique`thread_id` (UUID) scopes LangGraph state, event buffer, and DB rows; per-thread `asyncio.Lock`                    | Move state to Redis/Postgres keyed by`thread_id` for multi-worker scale |
| **Token budget overflow**        | Prompt exceeds context window                 | Hard caps: KB ≤ 5 chunks, tools ≤ 2 KB, memory ≤ 5 lessons, truncated critique history                                    | Pre-flight token counting; summarize-then-inject when over budget         |
| **HITL approver never responds** | Debate stuck`awaiting_approval`             | State persisted indefinitely — auditable, no forced timeout                                                                 | Configurable SLA + auto-escalation / default-action policy                |

### 17.3 Streaming & Frontend Failures

These are failures of the live connection between server and browser — they're about *user experience* under bad networks.

**① SSE connection dropped.** *What happens:* a proxy, load balancer, or idle browser kills the long-lived stream in the middle of a debate. *How it's handled:* the server sends periodic heartbeats so dead connections are noticed; the browser's `EventSource` auto-reconnects with backoff; and a **replay buffer** re-sends the events the client missed, so nothing is lost on reconnect. *How I'd harden it:* resume-from-cursor using the `Last-Event-ID` header for exact replay from the precise point of disconnection.

**② SSE keeps failing → REST fallback.** *What happens:* the stream simply won't stay up (a hostile network or proxy). *How it's handled:* the frontend stops fighting SSE and **polls REST endpoints** (`getDebateStatus` / `getDecision`) instead, so the user still sees progress and the final decision. *Why it matters:* the feature degrades from "live" to "slightly delayed," never to "broken." This is graceful degradation applied to the *transport* layer.

**③ Backend cold start.** *What happens:* the first request after the server's been idle is slow or fails — common on free tiers where heavy imports (LangChain/LangGraph) load lazily. *How it's handled:* the frontend `withRetry` uses exponential backoff, so it quietly retries instead of throwing an error in the user's face; the health-dot indicator also backs off and recovers on the next success. *How I'd harden it:* a warm-up ping / keep-alive and lazy-loading the heaviest dependencies.

**Quick reference:**

| Failure                                      | Symptom                                                           | How AgentBoard handles it                                                                                                    | How I'd harden it                                       |
| -------------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| **SSE connection dropped**             | Proxy/idle/browser kills the stream                               | Heartbeats +`EventSource` auto-reconnect with backoff + **replay buffer** so no events are lost                      | Resume-from-cursor (`Last-Event-ID`) for exact replay |
| **SSE never connects / keeps failing** | Stream errors repeatedly                                          | Backoff 1 s → 30 s, then after 10 failures a **"Connection lost"** view with an in-place Reconnect; finished debates load from REST (`getHistoryItem`) anyway | Auto-switch sooner based on connection health score     |
| **Backend cold start**                 | First request after idle is slow/fails (free-tier, heavy imports) | `withRetry` with exponential backoff on the frontend; health dot backs off and recovers                                    | Warm-up ping / keep-alive; lazy-load heavy deps         |
| **Zombie SSE generators**              | Disconnected clients leak server tasks                            | `request.is_disconnected()` checks (at least every 20 s) + the Next.js proxy forwards the browser's abort to the backend      | Centralized connection registry with TTL eviction       |

### 17.4 Data & Infrastructure Failures

These are failures of the storage and runtime underneath — the ones that decide whether a debate *survives* a bad moment.

**① SQLite write fails or is slow.** *What happens:* a history write errors or lags in the middle of a debate. *How it's handled:* persistence is **fire-and-forget** — the live debate is served entirely from the in-memory store, so a failed write is logged, not fatal (see the dual-store theory in §16.9). *How I'd harden it:* an outbox pattern with a retry queue, and Postgres with connection pooling.

**② Process crash mid-debate.** *What happens:* the server dies while a debate is running. *How it's handled:* the LangGraph **checkpointer** has persisted the graph state at each node, so the debate is resumable, and completed rounds are already in SQLite. *Why it matters:* a crash costs you the current step, not the whole debate. *How I'd harden it:* a durable task queue (Celery/Temporal) so the *runner itself* is recoverable, not just the state.

**③ Embedding model unavailable.** *What happens:* the knowledge base can't load its embedding model (offline, or out of memory). *How it's handled:* `KnowledgeBase.is_available` flips to `False` and agents simply run **without** RAG — degraded, not broken (the debate just loses its document grounding). *How I'd harden it:* pin/pre-pull the model into the container image and health-gate KB features.

**Quick reference:**

| Failure                                   | Symptom                                     | How AgentBoard handles it                                                                                         | How I'd harden it                                                        |
| ----------------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **SQLite write fails / is slow**    | Persistence error mid-debate                | **Fire-and-forget** writes — the live debate is served from memory, so a failed write is logged, not fatal | Outbox pattern + retry queue; move to Postgres with connection pooling   |
| **SQLite write-concurrency limits** | Many parallel debates contend on one writer | Acceptable for MVP (single node, low concurrency)                                                                 | Postgres for real concurrency; SQLite stays for local/dev                |
| **Process crash mid-debate**        | In-flight debate lost                       | LangGraph checkpointer persists graph state → resumable; completed rounds are in SQLite                          | Durable task queue (Celery/Temporal) so the runner itself is recoverable |
| **Embedding model unavailable**     | KB can't embed (offline / OOM)              | `KnowledgeBase.is_available = False` → agents run **without** RAG (degraded, not broken)                 | Pre-pull/pin the model in the image; health-gate KB features             |
| **Secret/key missing or invalid**   | Provider auth fails                         | Fails fast at startup if the **active** provider's key is missing (errors never echo secrets); user-supplied keys held in memory only; switching providers is admin-only | Secret manager + key validation on`/llm-settings` save                 |

### 17.5 The 30-Second Framing to Memorize

> *"My failure philosophy is **isolate, degrade, recover**. Every external call is **timeout-bounded** so failures are isolated to one agent or one request. The system **degrades gracefully** — a missing agent, empty KB, or dropped stream produces a weaker result, never a crash. And it **recovers**: structured-output retries, SSE replay + REST fallback, cold-start backoff, and LangGraph checkpoints. The honest gap is that it's single-node — the production hardening is durable task queues, Postgres, and a circuit breaker around the providers."*

---

---

# POSSIBLE INTERVIEW QUESTIONS & ANSWERS

> Each answer is structured: **Core Answer → Deep Dive → Key Phrase to Remember**

---

## Q1: "What is AgentBoard and what problem does it solve?"

**A:** AgentBoard is a multi-agent AI debate system that solves the problem of shallow, single-perspective decision-making from LLMs. Instead of one GPT call giving a monologue, it simulates a structured boardroom debate — specialised agents (Analyst, Risk, Strategy, Ethics) propose positions, cross-examine each other's reasoning, revise their views, and a Moderator synthesises a consensus decision.

**Why it matters:** The quality improvement comes from the adversarial process itself. Cross-examination catches blind spots that no single LLM call would identify — same as how peer review catches errors that self-review misses.

**Follow-up you may get:** "Why did you build this instead of using an existing framework?"
→ Existing frameworks like AutoGen and CrewAI lack: formal adversarial constraint (agents just chat), quantified consensus (no agreement score), and HITL with state persistence (checkpoint + resume).

**Key phrase:** *"Quality emerges from the adversarial process, not from a single more-capable LLM."*

---

## Q2: "Why not just use one LLM call with a detailed prompt?"

**A:** You could write a mega-prompt saying "consider risk, strategy, ethics..." but it fails in practice for five reasons:

1. **LLMs skip steps** — multi-step instructions in one call get forgotten or collapsed
2. **No real adversarial process** — the model role-plays all perspectives; it knows what it'll say next, so there's no genuine challenge
3. **No measurable convergence** — you can't track confidence numerically from a narrative response
4. **No interruptibility** — you can't pause mid-prompt for human approval
5. **Context window limits** — deep multi-round analysis hits token limits quickly

**Key phrase:** *"A single LLM with a complex prompt is still one voice talking to itself."*

---

## Q3: "Why did you choose LangGraph over AutoGen or CrewAI?"

**A:** LangGraph provides three things the alternatives don't:

1. **Checkpointing** — `AsyncSqliteSaver` persists state after every node. AutoGen has no built-in checkpointing. If the server crashes mid-debate, LangGraph resumes; AutoGen restarts from scratch.
2. **HITL interrupts** — `interrupt()` pauses the graph mid-execution and freezes state. The human approves, `graph.resume()` loads the exact checkpoint and continues. CrewAI and AutoGen have no equivalent.
3. **Conditional routing** — Quick mode skips critique/revision phases via a single lambda edge. CrewAI is sequential; you can't conditionally skip stages at runtime.

**What I gave up:** LangGraph has a steep learning curve and verbose graph definition syntax vs. simpler CrewAI decorators.

**Key phrase:** *"LangGraph is a state machine. CrewAI is a pipeline. We needed a state machine."*

---

## Q4: "How does the consensus engine work?"

**A:** Four steps, each fixing part of the problem:

**V1 (fast):** `agreement_score = mean(agent.confidence)`. Simple, but produces false consensus — two agents 90% confident in opposite positions still scores 0.9.

**V1.5 (lexical):** blend confidence with how much the agents' positions overlap:

```
agreement = 0.7 × confidence_mean + 0.3 × normalize(confidence_weighted_jaccard)
normalize: raw overlap 0.08 → 0, 0.19 → 1 (linear, clipped)
```

Agents writing in different roles share few words even when they agree, so raw overlap is rescaled before blending. But the window saturates: agents debating one question hit 1.0, so the score becomes `0.7 × confidence + 0.3` and a confident 2-vs-2 split (0.86) passes Thorough.

**V2 (semantic, opt-in):**

```
agreement = 0.5 × confidence_mean + 0.5 × mean_pairwise_cosine(position_embeddings)
```

Embeds each agent's position with `all-MiniLM-L6-v2`. That catches positions that are about different things, but it is **negation-blind**: "should expand" and "should NOT expand" still score as close. Word overlap has the same blind spot: both measure *topic*, not *verdict*.

**V3 (stance, the live default):** each agent declares a structured `stance` (support / oppose / conditional / abstain) toward the proposal on the table — the question in round 1, the Moderator's `leading_proposal` after that. Agreement is the confidence-weighted vote share of the largest group:

```
agreement = max(confidence sum per stance) / total voter confidence     # abstainers excluded
```

The 2-vs-2 split now scores ~0.50 and never passes. If fewer than two agents vote, it falls back to the lexical blend. The method is selectable (`AGREEMENT_METHOD`, or per debate: Vote / Text / Semantic in the UI). `SEMANTIC_CONSENSUS_ENABLED` now only reports the cosine score as a diagnostic and unlocks the `semantic` option; it no longer overrides the score.

**Stagnation signal:** if position *drift* between round N-1 and N (1 − Jaccard overlap, averaged over agents present in both rounds) is below 0.05, agents have stopped changing. That is one of the ways the "confidence converged" signal can pass, **not** an early stop on its own. Drift is only measured when the same agents spoke in both rounds.

**The gate, not just the score:** termination requires *six* signals together — agreement ≥ threshold, `min_rounds` reached, ≤ 1 agent voting against the majority stance, ≤ 2 high/critical critiques still open after revision, confidence converged, and no standing Ethics veto. So "everyone is confident after round 1" alone never ends the debate, and the non-score signals catch some of the contradictions the score misses.

**Key phrase:** *"Confidence tells you how sure agents are; the gate also checks they've actually stopped disagreeing — and for long enough."*

---

## Q5: "Why SSE instead of WebSockets?"

**A:** Three reasons this was a deliberate, correct choice for this use case:

1. **Unidirectional data flow** — the server pushes debate events, the client only receives. WebSocket's bidirectionality is wasted.
2. **Built-in reconnection** — `EventSource` API handles reconnect automatically with `Last-Event-ID`. With WebSockets, you'd implement this yourself.
3. **HTTP compatibility** — no upgrade negotiation, works with standard HTTP load balancers and proxies.

**The one client→server message** (HITL approval) is a standard `POST` endpoint — it doesn't need the persistent connection.

**When I'd use WebSockets instead:** If the user needed to send data mid-stream (e.g., inject context into a running debate, live collaborative editing).

**Key phrase:** *"SSE does one thing and does it right. WebSockets solves a different problem."*

---

## Q6: "How do you handle LLM failures mid-debate?"

**A:** Graceful degradation at four levels:

1. **Agent timeout (> 45s per phase, ×1.5 for tool-using agents)** → skip that agent, debate continues with remaining agents
2. **Structured output parse failure** → `with_retry(stop_after_attempt=2)` exponential backoff → if both fail, agent output is `None`
3. **Rate limiting (429)** → LangChain built-in retry handles backoff automatically
4. **ALL agents fail in a round** → agreement_score = 0, loop continues to next round until `max_rounds`

**The principle:** The system degrades in quality but never crashes. Availability is maintained even when a provider is having issues.

**Key phrase:** *"Every failure mode has a fallback. LLM failures are expected, not exceptional."*

---

## Q7: "Walk me through the end-to-end flow of a debate."

**A:**

**Step 1 — Request (< 50ms):**
User POSTs `/debate/start-async`. Pydantic validates. `DebateState` created with UUID. Stored in memory + SQLite. `BackgroundTask` launched. API returns `{thread_id}` immediately — non-blocking.

**Step 2 — Stream subscription:**
Frontend `GET /debate/{thread_id}/stream`. HTTP connection held open. Replay buffer sends already-emitted events for late joiners.

**Step 3 — LangGraph debate loop:**
Each round: proposals (all agents parallel, 45s timeout) → critiques (each critiques all others) → revisions (each updates based on critiques received) → convergence (the consensus engine computes the score and gate signals; the Moderator writes an advisory round summary).

**Step 4 — Convergence check:**
The six-signal gate decides, not the Moderator. All six hold → finalize with `consensus_reached`. Otherwise, if `rounds = max_rounds` → finalize with `max_rounds_reached`. Otherwise → next round.

**Step 5 — Finalize:**
Moderator generates `FinalDecision` (Pydantic: summary, recommendations, confidence_score, risk_flags, dissenting_opinions).

**Step 6 — Cleanup:**
Agent memories stored. Full state persisted. SSE emits `debate_completed` then `final_decision`. Frontend renders decision + confidence drift chart.

---

## Q8: "How do you ensure agents don't all say the same thing?"

**A:** Role constraint is the core design mechanism.

Each agent has a **deliberately narrow lens** defined in its system prompt:

- Analyst: **MUST NOT** propose strategy
- Risk: **MUST NOT** propose solutions
- Ethics: ignores business justification unless it involves harm
- Strategy: ignores risks only at its own peril (other agents will critique it)

**Why this works:**

- The Analyst's refusal to recommend creates a **gap** the Strategy agent must fill
- The Risk agent's adversarial mandate **forces** stress-testing of optimistic proposals
- Without constraints, all LLMs default to the same "balanced, moderate" answer

**This is Separation of Concerns applied to LLM reasoning.**

**Key phrase:** *"Constraints don't limit the debate — they're what makes it a debate."*

---

## Q9: "How would you scale this to production?"

**A:** Current architecture is single-instance by design (MVP). For horizontal scaling, each layer has a clear migration:

| Current         | Production           | Why                                          |
| --------------- | -------------------- | -------------------------------------------- |
| SQLite          | PostgreSQL (asyncpg) | Write concurrency, replication               |
| In-memory state | Redis                | Shared state, distributed locks, SSE pub/sub |
| ChromaDB        | Pinecone / pgvector  | Managed vector search at scale               |
| No auth         | JWT/OAuth2 + RBAC    | Secure multi-tenant access                   |
| BackgroundTask  | Celery/Dramatiq      | Durable task queue, retry on worker crash    |
| No tracing      | OpenTelemetry        | Distributed trace per debate across services |

**Why migration is low-risk:**

- `KnowledgeBase`, `LangChainProvider`, and CRUD layers are clean abstractions
- Swap SQLite → PostgreSQL: change `DATABASE_URL` + swap `aiosqlite` for `asyncpg`
- Business logic is completely decoupled from infrastructure

**Key phrase:** *"The architecture was designed for this migration — abstractions were the point."*

---

## Q10: "What's the cost of running this system?"

**A:**

- **Groq (LLaMA 3.3 70B):** ~$0.006/debate — essentially free on current free tier
- **GPT-4o:** ~$0.35–$0.70/debate (standard mode = ~20 LLM calls)

**LLM costs dominate infrastructure by 10–100×.** Optimise LLM spend before anything else.

**Cost optimisations in the system:**

1. **Per-agent model routing** — Moderator on GPT-4o (quality-critical), others on Groq (fast + cheap)
2. **Quick mode** — skips critiques, ~60% fewer calls
3. **Early termination** — halt before `max_rounds` once the gate passes (as early as round 1 in Quick mode, where `min_rounds` is 1)
4. **Query caching** — hash question → return cached decision for identical queries

**Key phrase:** *"The infra cost is noise. The LLM bill is the budget."*

---

## Q11: "How does the RAG system work?"

**A:**

**Indexing (offline):**

```
User uploads file → extract text → chunk (1000 chars, 200 overlap)
→ embed with all-MiniLM-L6-v2 → store in ChromaDB
```

**Retrieval (at query time):**

```
Question → embed → cosine search in ChromaDB
→ top-5 chunks with similarity ≥ 0.30
→ inject as numbered context blocks into agent system prompt
```

**Why these parameters?**

- 1000 chars ≈ 200-250 words — semantic unit without overwhelming the prompt
- 200 char overlap — prevents concept truncation at chunk edges
- Top-5 / 0.30 threshold — MiniLM cosine runs low even for relevant chunks, so a permissive floor keeps them; top-5 caps the noise

**ChromaDB vs Pinecone:**

- ChromaDB: zero infra, ~5ms, offline, free
- Pinecone: managed, scalable, ~100ms, $$$

**Key phrase:** *"RAG grounds agents in user-provided knowledge, not hallucinated training data."*

---

## Q12: "What's the hardest technical challenge you solved?"

**A:** The V1 → V2 → stance consensus engine evolution.

**The discovery:** V1 (confidence-based) reported false consensus. Two agents could be 90% confident in contradictory positions, and V1 reported 0.90 agreement. We only caught this during testing with carefully chosen adversarial scenarios.

**The first fix:** stop trusting a single number. The score blended confidence with rescaled word overlap between positions (embedding similarity with V2), and the termination gate also required few dissenters, few high-severity critiques, a minimum number of rounds and no standing veto.

**The second discovery:** that fix had the same bug one level up. Word overlap and embeddings both measure *topic*. "Should expand" vs "should not expand" scores as agreement on either, and once every agent writes about the same question the overlap saturates at 1.0. A confident 2-vs-2 split scored 0.86 and passed Thorough.

**The fix that held:** measure the *verdict*. Each agent fills a structured `stance` (support / oppose / conditional / abstain) toward a concrete proposal: the question in round 1, the Moderator's one-sentence `leading_proposal` after that. Agreement is the confidence-weighted share of the largest stance group, so the same split scores ~0.50. It follows the same pattern as the Ethics `veto`: a structured field beats parsing free text.

**What it doesn't solve (say this before they ask):** the stance is self-reported. An agent could argue against a proposal and still label it `support`. The gate reduces false consensus; an NLI check that the position matches the stance would close more of the gap.

**The hard part:** changing the metric without breaking anything:

- Stored debates have no `stance` → the field is optional on stored responses (required only in the LLM schema), and a round with < 2 voters falls back to the old lexical blend
- Semantic similarity stopped silently replacing the score: it is now a diagnostic, computed off the event loop, and only drives the gate when a debate explicitly picks it
- Every score (confidence, overlap, semantic, stance) is still emitted each round, so the methods can be compared on real debates
- sentence-transformers (~80MB) stays an optional, lazy-loaded dependency behind `SEMANTIC_CONSENSUS_ENABLED`

**Key phrase:** *"The bug was invisible because each version produced plausible-looking wrong answers. Text similarity tells you agents are talking about the same thing, not that they agree."*

---

## Q13: "How do you evaluate decision quality?"

**A:** Three independent evaluation layers:

**Layer 1 — Consensus metrics (process quality):**
Agreement score, confidence drift, position drift. Measures how well the debate converged, not what it decided.

**Layer 2 — LLM-as-Judge (output quality):**
A separate LLM call (not participating in the debate) scores the final decision on:

- Completeness: did it cover all aspects?
- Consistency: any logical contradictions?
- Actionability: can someone act on it?
- Risk awareness: are risks named?

**Layer 3 — Simulation consistency (stability):**
Run the same question N times. Compute the mean pairwise word overlap (Jaccard) of the final decisions, rescaled like the consensus score (0.08 → 0, 0.19 → 1).

- > 0.80: High stability
- > 0.55: Medium
- ≤ 0.55: Low — question type produces unstable answers, flag this

**Why three layers?**
A debate can converge quickly (good process) but produce a shallow decision (bad output). Or produce a detailed decision that changes completely on re-run (unstable). All three matter.

**Known limitation:** LLM-as-Judge can rationalise gaps rather than flagging them. It's a heuristic, not ground truth.

---

## Q14: "Why Pydantic structured output instead of free-form text?"

**A:** Free LLM text is unpredictable in format and impossible to process algorithmically.

**The problem with free text:**

- "I'd rate my confidence as pretty high, maybe around 80%"
- How do you compute `mean(confidence)` from that? You can't.

**What structured output gives you:**

```json
{
  "confidence_score": 0.82,
  "position": "The company should expand to Asian markets",
  "key_points": ["Market size 2.1B", "Regulatory risk high", "3-year payback"],
  "risk_level": "medium"
}
```

- `confidence_score` is always a Python float in [0, 1], never "approximately 0.8"
- Algorithms can operate directly on the output
- Eliminated ~40 lines of JSON parsing boilerplate per agent

**Provider-agnostic:** `with_structured_output()` routes to Groq tool calling / OpenAI function calling / Anthropic tool_use — all transparent to the rest of the code.

**Key phrase:** *"Without structured output, the consensus algorithm can't exist. Numbers need numbers."*

---

## Q15: "What design patterns did you use?"

**A:** Six patterns, each solving a specific problem:

1. **Template Method (BaseAgent)** — Skeleton algorithm in base (LLM call, KB enrichment, memory injection), subclasses override only prompt construction. Adding a new agent = 3 prompt methods.
2. **Adapter (LangChainProvider)** — Provider-agnostic LLM interface. Swap Groq → OpenAI → Anthropic with one env var.
3. **Factory with closure (node factories)** — LangGraph nodes can't accept extra arguments. Factory functions return closures that capture agents, event emitter, and persistence callback.
4. **Service Locator (AgentRegistry)** — Agent instantiation and configuration decoupled from the orchestrator. Registry knows how to build any agent; orchestrator just asks for one.
5. **Graceful Degradation** — stance or semantic agreement falls back to the lexical blend when it can't be computed, KB unavailable (returns unchanged prompt), tool timeout (agent skips tool, uses cached data).
6. **Feature Flags** — Semantic similarity, agreement method, RAG, agent memory all toggleable via environment variables, no code changes required.

---

## Q16: "Why SQLite and not PostgreSQL?"

**A:** Zero infrastructure was the deliberate choice for this project stage.

**SQLite advantages for this use case:**

- No DB server to install, configure, or maintain
- Handles concurrent reads, serialised writes — sufficient for single-user application
- Entire database is one portable file
- Alembic migrations work identically

**The data model is simple:** 4 tables, mostly JSON blob storage. An ORM would add complexity for zero benefit.

**Migration path is straightforward:**

```python
# Change:
DATABASE_URL = "sqlite+aiosqlite:///./agentboard.db"
# To:
DATABASE_URL = "postgresql+asyncpg://user:pass@host/db"
```

Plus: swap timestamp types (SQLite stores as TEXT, Postgres has native TIMESTAMPTZ), update aiosqlite → asyncpg import.

**When I'd start with PostgreSQL next time:** If the project has any multi-instance requirement from day one.

---

## Q17: "How does the Agent Memory system work?"

**A:** After each debate, each agent's final position text is sent to an LLM with a summarisation prompt:

```
"Summarise the core lesson from this agent's debate position in ONE sentence 
that would be useful in a future debate on a similar topic."
```

Result: `"Regulatory risk in Asian markets is consistently underestimated in expansion proposals."`

Stored in SQLite keyed by `agent_name`. On subsequent debates with `enable_agent_memory=True`:

- Retrieve 5 most recent lessons for that agent
- Prepend as numbered list in the system prompt before any debate-specific content

**Why LLM-summarised?**

- Raw position: ~500-2000 tokens × 5 = 2500-10000 token context pollution
- Distilled lesson: ~30 tokens × 5 = 150 tokens — 99% reduction, 100% of the insight

**Known limitation:** Currently uses recency, not relevance. A future improvement: semantic similarity match between new question and stored lessons to retrieve the *most relevant* memories.

---

## Q18: "What's the Ethics agent's veto power?"

**A:** A structured veto that **blocks consensus** — but doesn't end the debate or decide for the human.

**How it works:**

- Ethics-class agents (Ethics, FinancialEthics, PatientSafety) answer with a schema that has `veto: bool` and `veto_reason` — not a keyword in free text
- While any veto stands in the current round, the hybrid gate can't declare consensus (`active_vetoes == 0` is one of its signals); the agents keep debating, and in a revision the Ethics agent can withdraw the veto once its concerns are addressed
- If rounds run out with the veto still standing, the debate ends as `max_rounds_reached` — never as "consensus"
- The moderator's final prompt lists the standing vetoes ("don't adopt the vetoed course as proposed"), and `FinalDecision.vetoes` records them; the UI shows a Veto badge on the agent card and a "Standing veto" block on the decision, and exports include it
- In HITL mode the reviewer sees all of this before approving

**Why block consensus but not hard-stop?**

- An LLM can hallucinate an ethical problem; a hard stop would throw the whole debate away on a false positive
- Blocking *consensus* is the honest middle ground: the system won't claim agreement while a serious objection stands, yet the debate still produces a decision and the human makes the final call

**The principle:** *LLM opinions should inform, not override, human judgment on ethics — but they must not be silently outvoted either.*

**Follow-up Q:** "What if the human approves anyway?"
→ The veto is on the decision itself (`vetoes`) and in the trace. If a decision is later questioned you can see "Ethics vetoed X for reason Y, the reviewer approved/overrode with direction Z" (`human_feedback`).

---

## Q19: "How does Human-in-the-Loop work?"

**A:** Four-step process using LangGraph's native interrupt mechanism:

**Step 1 — Trigger:**
When `is_supervised=True` and convergence threshold is reached, the graph hits an `interrupt()` call before entering the finalize node.

**Step 2 — Freeze:**
LangGraph pauses execution. `AsyncSqliteSaver` persists the complete graph state (debate positions, scores, round history) to SQLite. SSE emits `approval_required` event with the current consensus state.

**Step 3 — Human decision:**
Frontend shows an approval dialog with the debate summary, consensus score, and any Ethics agent flags. User clicks "Approve" or "Reject".

**Step 4 — Resume:**
`POST /debate/{thread_id}/approve` triggers `graph.resume()`. The checkpointer loads the frozen state and continues execution into the finalize node — **exactly from where it paused**, not from the beginning.

**If nobody approves:**
State stays as `awaiting_approval` in the database. Visible in debate history. No timeout, no forced resolution — this is an audit decision.

**Key phrase:** *"LangGraph's interrupt is like `git stash` for a running debate — freeze it, examine it, resume it."*

---

## Q20: "What would you do differently if starting over?"

**A:** Five concrete changes, each with a lesson learned:

1. **PostgreSQL from day one** — SQLite migration costs more time than the original simplicity saves. If there's any chance of multi-instance, start with Postgres.
2. **Authentication from the start** — Auth touches every endpoint. Adding it later means retrofitting Pydantic models, adding middleware, updating tests. It's 3× the work.
3. **OpenTelemetry tracing from day one** — Debugging async multi-agent execution across LangGraph nodes without distributed traces is painful. You can see logs but not causality.
4. **Explicit token budget management** — Check prompt length before LLM calls, not after. Silent truncation is a quality bug that's hard to detect.
5. **User feedback loop** — We can measure consensus score and LLM-judge scores, but we can't know if the decision was actually useful to the user. This is the most important metric and we have no way to collect it.

---

## Q21: "How do you handle security concerns?"

**A:**

**What's solid today:**

- Pydantic validates all API inputs at the boundary — malformed requests never reach business logic
- Calculator uses `numexpr`, not Python `eval()` — prevents code injection via arithmetic expressions
- Rate limiting: 30 req/min per IP via slowapi

**Honest security gaps:**

- No authentication or RBAC — anyone with the URL can submit debates (P0 for production)
- CORS: `allow_origins=["*"]` — trivial to restrict to frontend domain
- No explicit prompt injection defense — adversarial inputs could potentially manipulate agent system prompts

**Production hardening plan:**

```
- JWT/OAuth2 authentication on all endpoints
- CORS restricted to specific frontend domain
- Secrets via AWS SSM / HashiCorp Vault (not env vars in production)
- Input sanitisation: strip or escape prompt injection patterns
- Content security policy headers
```

**Key phrase:** *"Security is architecturally sound for MVP; the gaps are all known and all fixable."*

---

## Q22: "Explain the Node Factory pattern in DebateGraph."

**A:** LangGraph enforces a simple contract: nodes must be `async def node(state: State) -> dict` — they accept only state, nothing else.

**The problem:** Nodes need access to agents, an event emitter function, and a DB persistence callback. How do you pass dependencies to a function that takes no arguments?

**The solution — factory with closure:**

```python
def make_proposals_node(agents: list[BaseAgent], emit_fn, persist_fn):
    """Factory returns a LangGraph-compatible node."""
    async def proposals_node(state: DebateState) -> dict:
        # agents, emit_fn, persist_fn captured via Python closure
        results = await asyncio.gather(
            *[agent.run(state) for agent in agents],
            timeout=15
        )
        await emit_fn("agent_output", results)
        await persist_fn(state)
        return {"agent_positions": results}
  
    return proposals_node  # ← LangGraph only sees this

# At graph build time:
graph.add_node("proposals", make_proposals_node(agents, emit, persist))
```

Dependencies are **captured at graph-build time**. The LangGraph API stays clean. The node function is fully configurable without breaking the contract.

**Key phrase:** *"The factory gives LangGraph what it wants (a simple callable) while giving us what we need (injected dependencies)."*

---

## Q23: "How does per-agent model routing work?"

**A:** Each agent can have a dedicated `AgentConfig` specifying which LLM provider and model to use.

```python
AgentConfig(
    name="Moderator",
    model_provider="openai",  # Use a frontier model for synthesis quality
    model_name="gpt-5.5"
)

AgentConfig(
    name="Analyst",
    model_provider="groq",    # Use LLaMA for speed + cost
    model_name="llama-3.3-70b"
)
```

When `AgentRegistry.get("Moderator", default_client)` is called: if the Moderator has a `model_provider` config, it creates a dedicated `LangChainProvider` pointing to GPT-4o. The Analyst gets the shared Groq client.

**Business value:** The Moderator's synthesis is the final output the user sees — maximum quality justified. The four domain agents are intermediate reasoning steps — speed + cost matters more.

**Zero code change needed:** Just config. `model_provider` + `model_name` in `AgentConfig` → the registry handles the rest.

**Key phrase:** *"Not every LLM call justifies GPT-4o pricing. Route quality where it matters."*

---

## Q24: "What metrics would you put on a production dashboard?"

**A:** Seven categories, each answering a different operational question:

| Metric                                 | Question It Answers                         | Alert Threshold                        |
| -------------------------------------- | ------------------------------------------- | -------------------------------------- |
| **Debates/day**                  | Is the system being used?                   | Below baseline = issue                 |
| **Completion rate**              | % of debates that reach`completed` status | < 95% = investigate                    |
| **P50/P95 debate duration**      | Is performance degrading?                   | P95 > 3× P50 = outlier problem        |
| **Average consensus score**      | Are debates producing good decisions?       | Trend down = prompt regression         |
| **LLM cost per debate**          | Are we within budget?                       | Spike = model routing misconfigured    |
| **Per-agent response time**      | Which agent is the bottleneck?              | Any agent > 2× others = investigate   |
| **Rounds-to-converge histogram** | Are thresholds correctly tuned?             | Mode = max_rounds = threshold too high |

**The analytics API already surfaces most of these.** The dashboard would be a recharts layer on top of the `/analytics` endpoint.

**Key phrase:** *"Operational metrics tell you when something is wrong. Quality metrics tell you what's wrong."*

---

## Q25: "What are the known limitations of the system?"

**A:** Six honest limitations — interviewers respect candor here:

1. **No factual accuracy checking** — Agents can confidently state wrong facts. RAG helps for uploaded documents, but hallucinations outside the KB go undetected. Mitigation: add a fact-checking tool that queries a verified source.
2. **Self-reported stances** — Text similarity (words or `all-MiniLM-L6-v2` embeddings) can't tell "should expand" from "should NOT expand", which is why agreement is now a structured stance vote. But the vote trusts each agent's label, and the agreement thresholds (0.60 / 0.75 / 0.85) haven't been re-calibrated for it. Mitigation: an NLI (Natural Language Inference) check that each position actually matches its stance, and calibrating thresholds on labeled debates.
3. **No user feedback loop** — We measure process quality (consensus score) and output quality (LLM judge), but we have zero data on whether decisions were actually useful. This is the most important unknown.
4. **Single-instance only** — In-memory state doesn't share across servers. Can't horizontally scale without the Redis migration.
5. **LLM-as-Judge unreliability** — The evaluator LLM can rationalise gaps rather than flagging them. It's an LLM judging an LLM — inherently susceptible to the same biases. Mitigation: human-labelled evaluation set as ground truth.
6. **No inter-agent influence tracking** — We know aggregate metrics but can't trace which specific critique caused which confidence change. Causal attribution within the debate is missing.

**Key phrase:** *"Knowing your limitations is half of having them. The other half is having a plan to fix them."*

---

## Q26: "How do you handle failure?"

> This is the broad version of the question — [Q6](#q6-how-do-you-handle-llm-failures-mid-debate) covers the narrower "LLM fails mid-debate" case, and [Section 17](#17-failure-modes--how-to-resolve) is the full catalogue. Start with the philosophy, then give one concrete example per layer.

**Core Answer:** My failure philosophy is three words — **isolate, degrade, recover**.

- **Isolate** — every external call (LLM, DB, tool, embedding model) is **timeout-bounded** and wrapped so a failure is contained to *one* agent or *one* request, never the whole debate. This is the bulkhead idea: sealed compartments so one flooded section doesn't sink the ship.
- **Degrade** — when something non-essential fails, the system returns a **weaker-but-valid** result instead of crashing. A timed-out agent is dropped and the round continues; an empty or unavailable knowledge base means the debate runs without RAG; a dead SSE stream turns into a "Connection lost" view with Reconnect, while the debate itself carries on server-side. The user always gets *an* answer.
- **Recover** — transient failures are absorbed automatically: structured-output retries (`stop_after_attempt = 2`), SSE replay buffer + auto-reconnect, frontend exponential-backoff retries for cold starts, and LangGraph checkpoints so a crash is resumable.

**Deep Dive — one example per layer:**

| Layer                   | Failure                         | What the system does                                                                                                                             |
| ----------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **LLM**           | An agent call times out         | `asyncio.wait_for` (45 s) drops that agent, emits `agent_timeout`, and the Moderator synthesises from the remaining agents (degraded round). |
| **Orchestration** | Agents never agree              | A hard`max_rounds` ceiling ends the loop and returns an honest `max_rounds_reached` decision with low agreement — never a faked consensus.  |
| **Streaming**     | The SSE stream keeps dropping   | The client reconnects with backoff and resumes after the last event id; after 10 failures it shows "Connection lost" with an in-place Reconnect — the debate keeps running on the server. |
| **Data**          | A SQLite write fails mid-debate | State snapshots are best-effort (logged, not fatal; event writes retry when the DB is busy). The final decision is stored *before* checkpoints are deleted — if storing fails the checkpoints stay, so the debate can be resumed. |

**The honest part (say this — interviewers reward it):** the biggest gap is that it's **single-node**, so the real production-hardening is a durable task queue (Celery/Temporal) so the runner itself recovers, Postgres + an outbox pattern for durable persistence, and a **circuit breaker** around the LLM providers (after K consecutive failures, fail fast instead of hammering a dead service).

**Key phrase:** *"Isolate, degrade, recover — every dependency is timeout-bounded, every failure degrades to a weaker-but-valid result, and the transient stuff recovers itself. The system fails soft, never hard."*

---

*Last updated: 2026-06-14 | AgentBoard Multi-Agent Decision Engine Interview Notes*
