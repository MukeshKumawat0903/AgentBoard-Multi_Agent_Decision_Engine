# 🧠 Problem Understanding — AgentBoard

> Interview use: explain the problem, why single-shot LLMs fall short, and what makes AgentBoard different. Leave implementation detail to the later docs.

## What Real-World Problem Is This Solving?

**Core problem:** High-stakes strategic decisions degrade when they are evaluated from a single perspective.

Strategic decisions — "Should we expand to Asia?", "Should we adopt Kubernetes?", "Should we acquire Company X?" — require simultaneously weighing data, risk, ethics, and strategy. No single person (or single LLM call) does this well because:

1. **Cognitive tunnel vision** — A CEO thinks about growth, misses regulatory risk. A CFO thinks about costs, misses strategic opportunity.
2. **LLM single-perspective bias** — A single GPT-4 call produces plausible but superficial answers. It doesn't stress-test its own reasoning.
3. **No adversarial challenge** — Real board decisions improve because a risk officer pushes back on an optimistic strategy. Single-call LLMs don't have this dynamic.

AgentBoard solves this by **simulating a structured boardroom debate** — multiple specialised AI agents with different mandates argue, critique each other, refine positions, and converge on a well-defended decision.

### The Analogy

Think of it like the difference between:
- **Asking one smart friend** for advice → Single LLM call
- **Convening your own board of advisors** where each has a specific lens (data, risk, strategy, ethics), they challenge each other's blind spots, and a moderator synthesises the outcome → AgentBoard

---

## Why Is This Problem Hard?

### 1. Multi-Agent Coordination Is Non-Trivial

You can't just run 4 LLM calls in parallel and concatenate the results. You need:
- **Structured sequencing** — Proposals → Cross-examination → Revisions → Convergence
- **Information flow** — The Risk agent needs to see the Strategy agent's position to critique it
- **Convergence detection** — When to stop debating? Too early = shallow decision. Too late = token waste.
- **Graceful degradation** — What if one agent times out? The debate must continue.

### 2. LLM Output Is Non-Deterministic

Running the same debate twice produces different decisions. This creates:
- **Reproducibility concerns** — How do you trust a system that gives different answers each time?
- **Consensus measurement difficulty** — How do you score "agreement" between agents whose outputs are free-form text?
- **Evaluation challenges** — How do you measure if the decision quality is actually good?

### 3. Real-Time Streaming with State Machines

The system must stream debate progress live to the UI via SSE while maintaining consistent state across:
- Concurrent subscribers reconnecting mid-debate
- Server restarts (checkpoint recovery)
- Human-in-the-loop interrupts that pause/resume the state machine

### 4. Prompt Engineering at Scale

Each agent needs carefully designed prompts that:
- Enforce its role boundary (Analyst must NOT propose strategy)
- Produce structured output (Pydantic schemas via `with_structured_output`)
- Incorporate context from prior rounds without exceeding token limits
- Integrate RAG context and agent memory without prompt pollution

---

## Existing Solutions and Their Limitations

| Solution | What It Does | Limitation |
|----------|-------------|------------|
| **Single LLM call** (ChatGPT, Claude) | One-shot answer to a question | No adversarial challenge, no structured reasoning, no role separation |
| **Chain-of-Thought (CoT)** | LLM reasons step-by-step | Still a single perspective; no cross-examination |
| **AutoGen (Microsoft)** | Multi-agent conversation framework | Generic framework — requires heavy custom orchestration; no built-in consensus mechanics |
| **CrewAI** | Role-based agent teams | Sequential pipeline, not adversarial debate; no convergence scoring |
| **LangGraph multi-agent examples** | State-machine agent workflows | Demos are minimal; no real consensus engine, no RAG integration, no HITL |
| **ChatDev** | Multi-agent software development | Domain-specific to coding; not general decision-making |

### Where AgentBoard Is Different

1. **Structured debate protocol** — Not just "agents talking to each other." A formal propose → critique → revise → converge loop with measurable convergence.
2. **Adversarial by design** — The Risk agent's job is literally to find holes. The Ethics agent has veto power. This isn't cooperative; it's constructively adversarial.
3. **Quantified consensus** — Agreement scores, confidence drift tracking, position overlap measurement.
4. **Full-stack product** — Not a library or framework. A complete application with live streaming UI, persistence, analytics, export, and HITL workflows.
5. **Knowledge-grounded** — RAG integration means agents can cite uploaded documents, not just their training data.

---

## Interview-Ready Explanation (30 seconds)

> "AgentBoard is a multi-agent AI debate system. Instead of asking one LLM for an answer, it creates a panel of specialised AI agents — an analyst, a risk assessor, a strategist, and an ethics guardian — who propose positions, cross-examine each other, and refine their views over multiple rounds. A moderator agent measures convergence and synthesises a final decision with confidence scores, risk flags, and dissenting opinions. The whole thing streams live over SSE with a Next.js frontend, persists to SQLite, and supports human-in-the-loop approval before finalisation."

## Interview-Ready Explanation (2 minutes)

> "The core insight is that *deliberation improves decisions*. In corporate governance, you don't make a major acquisition based on one person's opinion — you have a CFO analyse the numbers, a risk committee stress-test the deal, a legal team check compliance, and a board chair synthesise the recommendation.
>
> AgentBoard replicates this digitally. The backend uses LangGraph to orchestrate a state-machine debate: each round has four phases — proposals, cross-examination, revisions, and convergence scoring. The agents are LangChain-backed with Pydantic structured output, so every response is type-validated. Consensus is measured by blending mean confidence with the word overlap between agents' positions (optionally sentence-transformer cosine similarity instead), and a six-signal gate decides when the debate ends.
>
> What makes it more than a prompt experiment is the productization: live SSE streaming, SQLite persistence, RAG over uploaded documents, agent memory, human-in-the-loop approval, simulation, and evaluation. The frontend exposes the debate trace and confidence drift so the recommendation is inspectable, not just generated."
