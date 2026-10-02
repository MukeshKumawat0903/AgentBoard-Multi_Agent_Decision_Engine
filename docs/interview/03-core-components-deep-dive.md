# 🔍 Core Components Deep Dive

> Interview use: do not walk every component end to end. Pick 3 that best support the question, usually `BaseAgent`, `DebateGraph`, and `ConsensusEngine`.

## 1. BaseAgent — The Abstract Foundation

**File:** `app/agents/base_agent.py`

### What It Does
Abstract base class that defines the 3-action protocol every debate agent must follow:
- `run(state)` → Produce an initial proposal (`AgentResponse`)
- `critique(state, target)` → Cross-examine another agent's position (`CritiqueResponse`)
- `revise(state, critiques)` → Update position based on received critiques (`AgentResponse`)

### Why It Exists (Design Reasoning)
The **Template Method Pattern** keeps agent-specific logic in prompt builders while centralizing the common workflow: enrich prompt, call the LLM, validate the response, and return typed output.

In practice this gives you:
- **Fast extension** — a new agent usually means overriding three prompt methods.
- **Shared mechanics** — RAG, memory injection, tool execution, retries, and parsing live in one place.

### How It Interacts
```
DebateGraph (orchestrator)
    │
    │ calls agent.run(state) / agent.critique(state, target) / agent.revise(state, critiques)
    │
    ▼
BaseAgent
    ├── _build_*_prompt()        ← subclass provides the role-specific prompt
    ├── _enrich_with_kb()        ← appends relevant ChromaDB chunks (if enabled)
    ├── _run_tools()             ← executes allowed tools (web_search, calculator, date)
    ├── _build_system_prompt()   ← prepends agent memory lessons (if enabled)
    └── _call_structured()       ← calls LLM via LangChainProvider.ainvoke_structured()
            │
            ▼
        LangChainProvider → Groq/OpenAI/Anthropic API
            │
            ▼
        Validated Pydantic model (AgentLLMOutput or CritiqueLLMOutput)
```

### Key Trade-offs
- **Structured output schemas** (`AgentLLMOutput`, `CritiqueLLMOutput`) are deliberately minimal — position, reasoning, assumptions, confidence. This means the LLM fills a tight contract rather than free-forming.
- **Trade-off:** Less creative freedom for the LLM, but guaranteed parseable output. The old approach (prompting for JSON) failed ~10% of the time.

---

## 2. Agent Implementations — Role Specialisation

### Design Pattern: Constrained Lens Agents

Each agent is **deliberately constrained** to a single analytical lens:

| Agent | Lens | What It May Do | What It Must NOT Do |
|-------|------|---------------|---------------------|
| **Analyst** | Facts & Data | Extract variables, quantify, identify cause-effect | Propose strategy, assess risk |
| **Risk** | Failure Modes | Categorise risks, rate severity, stress-test | Propose solutions |
| **Strategy** | Actionable Plans | Propose ≥2 alternatives, evaluate trade-offs | Ignore risk, ignore data |
| **Ethics** | Compliance & Fairness | Flag ethical issues, VETO if needed | Ignore business context |
| **Moderator** | Synthesis | Measure agreement, detect convergence | Take sides |

### Why This Separation Matters
Without role constraints, the system collapses into four paraphrases of the same answer. The Analyst stays factual, the Risk agent stays adversarial, and the Strategy agent owns recommendations. That separation is what creates useful disagreement.

### Domain Agents — Composition via Inheritance

**File:** `app/agents/domain_agents.py`

Domain agents (`FinancialEthicsAgent`, `SecurityAgent`, `ComplianceAgent`, `PatientSafetyAgent`) are thin subclasses that:
- Extend an existing agent type (Ethics → FinancialEthics, Risk → Security/Compliance)
- Override only the system prompt with domain-specific language
- Inherit all debate mechanics unchanged

**Why not composition?** Because the prompt is the only variable. A `FinancialEthicsAgent` behaves exactly like `EthicsAgent` — same proposal/critique/revision flow — but evaluates through a financial regulatory lens. Inheritance is the simplest expression of this.

---

## 3. Agent Registry — Dynamic Configuration

**File:** `app/agents/registry.py`

### What It Does
A singleton `AgentRegistry` that maps agent names → (class, config). At runtime:
- `registry.get("Analyst", llm_client)` instantiates a fresh `AnalystAgent` with the right LLM client
- `registry.enabled_agents()` returns which agents participate by default
- Per-agent model routing: if an agent's config has `model_provider="openai"`, it gets a dedicated `LangChainProvider` instead of the shared one

### Why It Exists
**Service Locator + Factory pattern** — The orchestrator asks for an agent by name and gets back a configured instance. It does not need to know provider details, tool policy, or domain-pack selection.

Practical impact:
- Per-agent model routing stays in config instead of orchestration code.
- Domain packs can activate specialized agents per debate without mutating global behavior.

### Tool Validation at Registration
When an agent registers with `allowed_tools=["web_search"]`, the registry validates that `"web_search"` exists in `TOOL_REGISTRY`. This is a **fail-fast safeguard** — mistyped tool names crash at startup, not mid-debate.

---

## 4. LangChainProvider — Multi-Provider LLM Adapter

**File:** `app/services/llm_client.py`

### What It Does
A provider-agnostic LLM client that wraps LangChain's chat models. Four providers (Groq, OpenAI, Anthropic, Gemini) share the same interface and are switchable at runtime via `/llm-settings`.

### Key Method: `ainvoke_structured()`
```python
async def ainvoke_structured(self, schema: type[T], system_prompt, user_prompt) -> T:
    chain = llm.with_structured_output(schema).with_retry(
        stop_after_attempt=2, wait_exponential_jitter=True
    )
    messages = self._build_messages(system_prompt, user_prompt)
    return await chain.ainvoke(messages)
```

### Why This Design
The adapter pattern keeps provider choice out of the rest of the system. The practical wins are simple provider switching, one mockable interface in tests, and one structured-output path for every agent.

Structured output plus retry also removes most of the old JSON parsing boilerplate and centralizes validation and backoff behavior.

### The GroqClient Alias
`GroqClient = LangChainProvider` — A backward-compatible alias so that old test imports (`from app.services.llm_client import GroqClient`) still work after the migration from the custom httpx client to LangChain. This is a pragmatic migration strategy.

---

## 5. DebateGraph — The Orchestration Engine

**File:** `app/orchestrator/debate_graph.py`

### What It Does
Builds and compiles a LangGraph `StateGraph` with 5 nodes and conditional edges. Executes the debate as a state machine.

### Why LangGraph Instead of a Simple Loop

The original `DebateController` was a procedural `while` loop:
```python
while should_continue and current_round < max_rounds:
    await run_proposals()
    await run_critiques()
    await run_revisions()
    should_continue = await check_convergence()
```

This was replaced with LangGraph because:

1. **Checkpointing** — `AsyncSqliteSaver` persists every state transition. The loop had no recovery mechanism.
2. **HITL interrupts** — LangGraph's `interrupt()` pauses the graph mid-execution and resumes from the exact same state. A procedural loop would need complex save/restore logic.
3. **Conditional routing** — "Quick" mode skips critiques/revisions. In LangGraph this is a conditional edge lambda. In a loop this is scattered if-statements.
4. **Concurrent debate isolation** — Each debate runs in its own `thread_id` scope. LangGraph checkpointer guarantees no state leakage between concurrent debates.

### The Node Factory Pattern

Each node is created by a factory function (`make_proposals_node(agents, emit)`) that captures dependencies via closure:

```python
def make_proposals_node(agents, emit, persist_state):
    async def proposals_node(state: DebateGraphState) -> dict:
        # ... uses agents, emit, persist_state from closure
        return {"debate_state": ds}
    return proposals_node
```

**Why factories?** Because LangGraph nodes must be simple async callables that accept state and return partial state. Dependencies (agents, event emitter, persistence callback) can't be passed as arguments — they must be captured at graph-build time. Closures are the cleanest way to do this.

---

## 6. Consensus Engine — Measuring Agreement

**File:** `app/services/consensus.py`

### What It Does
Quantifies how much agents agree, used to decide whether to stop debating.

### Three Agreement Methods

**Stance vote — `compute_stance_agreement()` (default, no ML dependencies)**
- Every proposal/revision carries a structured `stance` (support / oppose / conditional / abstain) toward the proposal on the table: the question in round 1, the Moderator's `leading_proposal` after that.
- Score = confidence-weighted vote share of the largest stance group. Abstainers and missing stances don't vote; returns `None` when fewer than two agents vote.
- `stance_tally()` counts agents per stance for logs and the UI ("2/3 vote").

**V1 — `ConsensusEngine` (no ML dependencies)**
- `compute_agreement_score()` — Mean confidence across all agents. Rationale: high confidence correlates with settled positions.
- `compute_confidence_weighted_score()` — Pairwise Jaccard word overlap, weighted by agent confidence.
- `detect_position_drift()` — How much agents changed between rounds (1 − Jaccard, averaged). Drift < 0.05 is one of three ways to pass the gate's "confidence converged" signal. It is not an early stop: every other signal must still hold.

**V2 — `SemanticConsensusEngine` (requires sentence-transformers)**
- `compute_semantic_similarity()` — Mean pairwise cosine similarity of sentence-transformer embeddings.
- `compute_agreement_score()` — Hybrid: `(1-w) × confidence_mean + w × cosine_similarity`. Weight `w` is configurable via `SEMANTIC_CONSENSUS_WEIGHT` (0.5).

**What `convergence_node` actually uses:** the debate's `agreement_method` (else `AGREEMENT_METHOD`, default `stance`), resolved by `resolve_agreement_method()`:
- `stance` → the stance vote above.
- `lexical` → `0.7 × compute_agreement_score() + 0.3 × normalize(compute_confidence_weighted_score())`, with raw overlap rescaled so 0.08 → 0 and 0.19 → 1.
- `semantic` → the V2 hybrid; only accepted when `semantic_available()` is true.

If the chosen score is `None` (fewer than two voters, semantic failure), the lexical blend is used and the round records `agreement_method_used = "lexical"`. Whichever score is chosen is then one of the six signals in `is_consensus_reached()`; all the others are still emitted on the `synthesis` event.

### Why Several Methods?
**Measuring verdict, not topic** — Jaccard and cosine both measure what the positions are *about*, so opposite verdicts on one question still score high. The stance vote measures the verdict directly; the text scores stay as the fallback and as diagnostics.

**Graceful degradation** — V2 requires `sentence-transformers` (~80 MB). It is feature-flagged via `SEMANTIC_CONSENSUS_ENABLED` (off by default); its import is guarded, the model only loads on first use, and encoding runs in a worker thread (`asyncio.to_thread`) so it never blocks the SSE stream. With the flag on, the cosine score is reported every round but only drives the gate when the `semantic` method is chosen.

### Trade-off: Jaccard vs Cosine Similarity
- **Jaccard** (V1): Simple word overlap. Fast. But "the market is growing" and "significant market expansion" have Jaccard ≈ 0.15 despite saying the same thing.
- **Cosine similarity** (V2): Embedding-based. Captures semantic meaning. But adds ~80 MB dependency and 100ms per scoring call.
- **Hybrid**: Blends either overlap signal with mean confidence; the weight parameter sets how much each counts.
- **Shared blind spot:** both are negation-blind. "We should expand" and "We should not expand" score as near-identical on Jaccard *and* on cosine. That's why the default agreement score is the stance vote, and why no score decides on its own; the other gate signals (dissent, high-severity critiques, min rounds, veto) have to agree.

---

## 7. Knowledge Base RAG — Grounding Agents in Your Data

**File:** `app/services/retriever.py`

### What It Does
ChromaDB-backed vector store. Users upload PDF/TXT/MD files → chunked → embedded with `all-MiniLM-L6-v2` → stored with cosine similarity index. At debate time, top-k relevant chunks are injected into agent prompts.

### The RAG Pipeline
```
Upload: PDF → pypdf text extraction → chunk (1000 chars, 200 overlap)
                                         → sentence-transformer embedding
                                         → ChromaDB upsert

Retrieve: query → embed → cosine similarity search → top-5 chunks
                                                       → filter by threshold (0.30)
                                                       → inject into prompt
```

### Why ChromaDB Over Alternatives

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **ChromaDB** | Local, persistent, free, Python-native | Limited to single-machine | ✅ Chosen — matches single-instance design |
| **FAISS** | Fast, well-tested | No persistence (in-memory only) | ❌ Would lose data on restart |
| **Pinecone** | Managed, scalable | Cloud dependency, API costs | ❌ Over-engineered for local app |
| **pgvector** | Integrates with PostgreSQL | Requires PostgreSQL | ❌ Would contradict SQLite decision |

### Thread Safety
`KnowledgeBase` uses an `asyncio.Lock` for writes (ingestion) but allows concurrent reads (retrieval). This is safe because ChromaDB reads are thread-safe but writes need serialisation to avoid index corruption.

---

## 8. Agent Memory — Learning Across Debates

**File:** `app/services/agent_memory.py`

### What It Does
After each debate, every agent's final position is summarised by an LLM call into a one-sentence lesson. These lessons are stored in SQLite and injected into the agent's system prompt at the start of future debates.

### The Memory Pipeline
```
Debate ends → for each agent:
    LLM call: "Summarise this position into one lesson"
    → { summary: "...", lesson: "..." }
    → INSERT INTO agent_memory (agent_name, debate_id, lesson_learned)

New debate starts (with enable_agent_memory=True):
    → SELECT lesson_learned FROM agent_memory WHERE agent_name = ? LIMIT 5
    → Prepend to system prompt: "Lessons from your past debates:\n- ..."
    → Agent now has historical context
```

### Why LLM-Summarised Lessons (Not Raw Positions)

Raw positions are 1-3 paragraphs. Injecting 5 of them into a system prompt would consume ~2000 tokens and pollute the context. A one-sentence lesson is ~30 tokens and distills the actionable insight.

**Trade-off:** The LLM summary might lose nuance. But the alternative (raw injection) would degrade prompt quality by flooding it with old context.

---

## 9. SSE Streaming Architecture

### The Event Flow

```
DebateGraph node
    │
    ├── emit("agent_output", { agent_name, position, ... })
    │       │
    │       ├── replay_buffer.append(payload)      ← for late-joining clients
    │       ├── asyncio.Queue.put_nowait(payload)  ← for live subscribers
    │       └── on_event(payload)                   ← persist to debate_events table
    │
    ▼
SSE endpoint (stream_debate_events)
    │
    ├── Replay: emit stored events first (from DB or replay_buffer)
    ├── Live: await queue.get() in a loop
    ├── Watchdog: 30s timeout → emit keepalive comment
    └── Cleanup: remove queue from list on disconnect
```

### Reconnection Strategy (Frontend)
- `Last-Event-ID` header sent on reconnect
- Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s max
- Max 10 attempts before switching to "disconnected" state
- 60s heartbeat timer: if no event arrives, force reconnect

### Why This Is Non-Trivial
1. **Late joiners** need replay, not just live events.
2. **Reconnects** need deduplication and recovery after transient failures.
3. **Completed or failed debates** still need to surface the correct terminal state after restarts.

---

## 10. Evaluator — LLM-as-Judge

**File:** `app/services/evaluator.py`

### What It Does
Scores a completed `FinalDecision` on 4 dimensions using a second LLM call:
- **Completeness** — Does it address all aspects of the query?
- **Consistency** — Is it internally coherent?
- **Actionability** — Does it contain concrete next steps?
- **Risk awareness** — Are risks identified and addressed?

### Why LLM-as-Judge Over Rule-Based Scoring
Rule-based scoring would require defining "what makes a good decision" for every possible query domain — impossible. The LLM evaluator applies general quality criteria adaptively.

**Trade-off:** The evaluator LLM might disagree with itself on repeated calls (non-deterministic). This is acknowledged — evaluations are cached in the `decisions.evaluation_json` column to avoid re-scoring.

---

## 11. Simulation Service — Consistency Testing

**File:** `app/services/simulation.py`

### What It Does
Runs N independent debates for the same query concurrently. Computes:
- **Consistency score** — Mean pairwise word overlap of the decision texts, **rescaled** with the consensus gate's anchors (0.08 → 0 = as different as decisions to unrelated questions, 0.19 → 1 = the same decision reworded). Raw overlap between independently written decisions is low even when they agree, so unscaled it could never say "High"
- **Confidence variance** — Stdev of agreement scores across runs
- **Stable risk flags** — The same risk **in any wording** in ≥70% of runs (flags are matched on their content words, lightly stemmed), each listed once
- **Stability rating** — High (>0.80), Medium (>0.55), Low

### Why This Exists
Because LLMs are non-deterministic. The simulation service measures how much repeated runs differ and which risk flags stay stable across runs.

**Interview angle:** This is analogous to **ensemble methods in ML** — running multiple models and looking at agreement as a confidence signal.
