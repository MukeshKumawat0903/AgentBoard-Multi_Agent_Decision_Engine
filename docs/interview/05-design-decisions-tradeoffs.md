# ⚖️ Design Decisions & Trade-offs

> Interview use: pick 2-3 decisions and explain them well. Listing all 10 only works if the interviewer explicitly asks for a broad review.

## Decision 1: Deterministic Convergence vs LLM-Judged Convergence

### The Decision
Hybrid approach — the Moderator LLM suggests `should_continue`, but the actual termination logic is **deterministic** and multi-signal. Consensus is declared only when *all six* signals hold:
```python
consensus = (
    active_vetoes == 0                    # no Ethics-class veto stands
    and position_agreement >= threshold   # stance vote share (default), not raw confidence
    and rounds_completed >= min_rounds    # a single round can never end a multi-round debate
    and dissenting_agents <= 1            # at most one agent voting against the majority stance
    and open_disagreements <= 2           # at most two high/critical critiques still open after revision
    and confidence_converged             # drift < 0.05 / spread ≤ 0.15
)
if consensus:               → stop (consensus_reached)
elif round >= max_rounds:   → stop (max_rounds_reached)
else:                       → continue
```
This replaced the original single-threshold gate (`agreement_score >= threshold`), which could declare consensus after one round on confidence alone. Each rule is written up in [`docs/consensus_engine.md`](../consensus_engine.md).

### Why Not Let the LLM Decide?
The Moderator's `should_continue` flag is advisory only — it is logged, not used for routing, and not shown in the UI (so the stream can't display a call that contradicts what actually happens) — because:
- **LLMs are unreliable decision makers** — The Moderator might say "should_continue=false" in round 1 because it generates an overconfident agreement score.
- **Deterministic guarantees** — The system MUST terminate eventually. `max_rounds` is the hard ceiling. An LLM can't override this.
- **Reproducibility** — Deterministic termination conditions are testable and debuggable. "Why did the debate end?" has a clear programmatic answer.

### The Trade-off
- **Pro:** Predictable behavior, guaranteed termination, testable
- **Con:** May terminate a debate where the Moderator has nuanced reasons to continue that the numeric score doesn't capture

---

## Decision 2: Local RAG (ChromaDB) vs Full Vector DB Service

### The Decision
Local ChromaDB with `all-MiniLM-L6-v2` embeddings stored on disk.

### Why Not Pinecone/Weaviate/Qdrant?

| Factor | Local ChromaDB | Cloud Vector DB |
|--------|---------------|-----------------|
| **Setup** | `pip install chromadb` | API key + provisioning |
| **Cost** | Free | $0.07+ per 1M vectors |
| **Latency** | ~5ms (local disk) | ~50-200ms (network) |
| **Scalability** | Single-machine only | Horizontal scaling |
| **Persistence** | Local directory | Managed |
| **Offline** | ✅ Works offline | ❌ Requires internet |

**The reasoning:** AgentBoard is a single-user local application. A cloud vector DB would add network latency to every prompt-enrichment step. For the current deployment model, local retrieval is simpler, cheaper, and faster.

### Real-World Implications
- **For a demo/portfolio:** ChromaDB is perfect
- **For enterprise deployment:** You'd switch to pgvector (if already using PostgreSQL) or Pinecone (if managing infrastructure is undesirable)
- **Migration path:** The `KnowledgeBase` class is a clean abstraction. Replace `_ingest_sync` and `_retrieve_sync` internals, keep the same interface.

---

## Decision 3: In-Memory State + Async Persistence vs Pure Database-Driven

### The Decision
Active debates live in Python dicts. Completed debates are persisted to SQLite. Every state change triggers an async DB write, but the source of truth is memory.

### Why Not Just Use the Database for Everything?

**Performance:**
- SSE event emission happens inside the debate loop. Each agent output emits 1-3 events. A 4-round debate produces ~40-60 events.
- If every event required a DB read to know the current state, that's 40-60 extra SQLite queries per debate.
- In-memory: `debate_store[thread_id]` is O(1) dict lookup.

**Consistency model:**
- The `DebateState` Pydantic object is the single source of truth
- All agents, nodes, and the convergence check read from *the same object in memory*
- The DB is a *backup*, not the authority

### The Trade-off

**Risk:** If the server crashes mid-debate, the in-memory state is lost.

**Mitigations:**
1. `on_state_change` callback writes to SQLite after every phase
2. LangGraph checkpointer (`AsyncSqliteSaver`) saves state after every node transition
3. On restart, orphaned debates are recovered as "error" status
4. SSE events are persisted to `debate_events` table for replay

**For production:** You'd add Redis as the in-memory store (shared across instances) and PostgreSQL as the durable backend.

---

## Decision 4: Agent-Per-Class vs Configurable Generic Agent

### The Decision
Each agent is a separate class (`AnalystAgent`, `RiskAgent`, etc.) that extends `BaseAgent`.

### Alternative: Single `GenericAgent` with Config-Driven Prompts

```python
# Alternative approach (not chosen):
class GenericAgent(BaseAgent):
    def __init__(self, name, role, system_prompt, prompt_templates):
        ...
```

### Why Separate Classes Won?

1. **Type safety** — `AnalystAgent` is a real type. You can't accidentally pass a Risk agent where an Analyst is expected.
2. **Custom logic** — Each agent has unique helper methods:
   - `AnalystAgent._format_prior_rounds()` — includes all prior agent positions
   - `RiskAgent._analyst_context()` — specifically retrieves the Analyst's latest output
   - `EthicsAgent._strategy_context()` — specifically retrieves the Strategy agent's output
3. **Testability** — Each agent class is unit-tested with its specific prompt templates.
4. **Readability** — Opening `risk_agent.py` tells you everything about the Risk agent's behavior: system prompt, proposal template, critique template, revision template.

### The Trade-off
- **Pro:** Clear, type-safe, independently testable, self-documenting
- **Con:** Adding a new agent requires creating a new file with ~100 lines of boilerplate. Domain agents mitigate this (they're ~20 lines each by inheriting from a core agent).

---

## Decision 5: Per-Agent Model Routing

### The Decision
Each agent can optionally use a different LLM provider/model.

### Why This Matters
Real-world example: The Moderator needs strong synthesis capability (GPT-4 level). The Analyst just needs to extract facts (Llama 70B is fine). The Ethics agent needs careful reasoning about edge cases (Claude might be best).

```python
# In registry config:
AgentConfig(name="Moderator", model_provider="openai", model_name="gpt-5.5")
AgentConfig(name="Analyst", model_provider="groq", model_name="llama-3.3-70b-versatile")
```

### The Trade-off
- **Pro:** Optimal cost-quality trade-off per agent role
- **Con:** Harder to debug (different providers have different error modes, latencies, output characteristics); higher operational complexity

---

## Decision 6: Ethics Agent Veto Power

### The Decision
Ethics-class agents (Ethics, FinancialEthics, PatientSafety) return a **structured veto** — `veto: bool` and `veto_reason` in their output schema, not a keyword in free text. A standing veto **blocks consensus**: it is one of the gate's six signals. It does not end the debate or decide the outcome.

### Why block consensus rather than hard-stop — or just annotate?

- **Not a hard stop** — LLMs hallucinate ethical concerns; terminating the debate with "rejected" on a false positive would waste it, and what's "fundamentally unethical" is context-dependent.
- **Not just a note** — the original design only wrote "VETO" into the position text. Nothing read it: a debate could be declared "consensus" while the Ethics agent was objecting. Making it a gate signal means the system never *claims* agreement over a standing veto.
- **User agency** — the debate continues; the Ethics agent can withdraw the veto in a revision once its concerns are met. If rounds run out, the result is `max_rounds_reached`, and the human decides.

### Real-World Implication
The moderator's final prompt lists standing vetoes, and the decision records them in `FinalDecision.vetoes` (agent, reason, round). The UI shows a Veto badge on the agent card and a "Standing veto" block on the decision; Markdown/PDF exports include them. In HITL mode the supervisor sees all of this before approving or overriding.

---

## Decision 7: Debate Modes (Quick/Standard/Thorough) vs Fully Custom

### The Decision
Three preset modes with specific defaults, plus full override capability:

| Mode | Rounds | Threshold | Skip Critiques |
|------|--------|-----------|----------------|
| Quick (default) | 2 | 0.60 | Yes |
| Standard | 2 | 0.75 | No |
| Thorough | 6 | 0.85 | No |

Users can also pass `max_rounds`, `consensus_threshold`, and `skip_critique_phase` explicitly to override any preset. The UI's **Custom** option is a real `custom` mode (Standard's settings + your rounds/threshold), and the default mode for requests that don't choose is `DEFAULT_DEBATE_MODE` — Quick unless configured, to keep casual and test runs cheap.

### Why Presets?
**Cognitive load reduction.** Most users don't know what `consensus_threshold=0.75` means. "Standard" is instantly understandable. Power users can still tune every parameter.

### The Quick Mode Design — Why Skip Critiques?
Quick mode (2 rounds, no critiques) is for when you want fast directional advice, not deep analysis. Skipping critique/revision phases eliminates ~60% of LLM calls, reducing a debate from ~20 calls to ~8.

**Trade-off:** No adversarial challenge. The Risk agent identifies risks, but doesn't critique the Strategy agent's proposal. The result is less stress-tested.

---

## Decision 8: SSE vs WebSockets

### The Full Comparison

| Feature | SSE (Chosen) | WebSockets |
|---------|-------------|------------|
| Direction | Server → Client (unidirectional) | Bidirectional |
| Reconnection | Built-in (`EventSource` API) | Manual implementation |
| Protocol | HTTP/1.1 or HTTP/2 | Upgrade from HTTP |
| Proxy friendliness | Excellent | Needs special config |
| Scaling | Standard HTTP load balancing | Sticky sessions needed |
| Message format | Text (newline-delimited) | Binary or text frames |
| Browser API | `EventSource` (simple) | `WebSocket` (more complex) |

### The Decisive Factor
The only client→server message during a debate is the HITL approval, which is already a POST request. Everything else is server→client, so SSE matches the traffic pattern with less operational complexity.

---

## Decision 9: Pydantic v2 Everywhere

### The Decision
Pydantic v2 models for: API request/response contracts, internal state, LLM output schemas, configuration, and database serialization.

### Why Pydantic v2 Specifically?

1. **FastAPI integration** — Pydantic v2 is FastAPI's native validation layer. Models become OpenAPI schemas automatically.
2. **Performance** — v2's Rust-backed core is 2-50× faster than v1 for validation and serialization.
3. **LLM structured output** — `with_structured_output()` accepts Pydantic models to generate function-calling schemas.
4. **Single schema language** — The `AgentResponse` Pydantic model defines: the LLM output contract, the internal state representation, and the API response format. One model, three uses.

### The Trade-off
- **Pro:** Maximum consistency — what the LLM produces, the backend validates, and the API returns are all the same schema
- **Con:** Pydantic models are heavier than plain dicts or dataclasses. Every field access goes through descriptor protocols.

---

## Decision 10: SQLite + Alembic (Not ORM)

### The Decision
Raw SQL via `aiosqlite` with Alembic for migrations. No SQLAlchemy ORM models.

### Why No ORM?

1. **Simplicity** — The data model has 4 tables (debates, decisions, debate_events, agent_memory). An ORM is overhead for this scale.
2. **JSON storage** — The main data is `state_json` (DebateState serialized) and `decision_json` (FinalDecision serialized). ORMs don't add value for JSON blob storage.
3. **Async** — `aiosqlite` provides native async without the complexity of SQLAlchemy's async session management.
4. **Performance** — Raw queries with parameter binding are faster than ORM query construction for the simple operations this system needs.

### When You Would Switch
If the data model grew to 10+ tables with complex relationships, an ORM would make sense. The current model is mostly "store JSON blob, retrieve by thread_id" — perfect for raw SQL.
