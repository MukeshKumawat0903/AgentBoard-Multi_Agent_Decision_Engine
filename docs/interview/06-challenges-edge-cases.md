# 🚨 Challenges & Edge Cases

> Interview use: keep this as a menu of examples. Usually 2-3 concrete failure modes are enough for one answer.

## 1. LLM Failure Modes

### Agent Timeout
**What happens:** An agent's LLM call takes longer than 15 seconds (the `_PROPOSAL_TIMEOUT`, `_CRITIQUE_TIMEOUT`, or `_REVISION_TIMEOUT`).

**How the system handles it:**
```python
try:
    result = await asyncio.wait_for(agent.run(ds), timeout=15.0)
except asyncio.TimeoutError:
    logger.warning("agent_proposal_timeout", ...)
    emit("agent_timeout", { agent_name, phase })
    return None  # This agent's output is skipped
```

**Graceful degradation:** The debate continues with whatever agents succeeded. If the Analyst times out, the Risk, Strategy, and Ethics agents still produce proposals. The Moderator synthesises from available outputs.

**Edge case: What if ALL agents time out?**
The round produces zero `agent_outputs`. The convergence node runs with an empty list → agreement_score = 0.0 → debate continues to the next round (or hits max_rounds). The final decision will be based on whatever outputs existed in prior rounds.

### Structured Output Parse Failure
**What happens:** The LLM returns output that doesn't conform to the Pydantic schema (e.g., `confidence_score: "high"` instead of `0.85`).

**How the system handles it:** `with_structured_output()` + `with_retry(stop_after_attempt=2)` automatically retries. If both attempts fail, `LLMResponseError` is raised, caught by the node's `_safe_run()`, and the agent's output is `None` for that round.

### Rate Limiting
**What happens:** Groq API returns 429 (rate limit exceeded).

**How the system handles it:** LangChain's `.with_retry()` uses exponential backoff with jitter. If the limit persists, the call fails and the agent produces no output for that round.

**Real-world scenario:** Simulation workloads can trigger 429s quickly on a free tier. The practical mitigation is fewer parallel runs or a higher-capacity provider.

---

## 2. Consensus Failure Modes

### False Consensus
**Problem:** All agents produce high confidence scores (0.85+) but their actual positions are contradictory. Agreement_score (V1 = mean confidence) reports 0.85, suggesting consensus, but there's no real agreement.

**Why it happens:** The V1 consensus engine only looks at confidence, not content. An agent can be 0.9 confident in "expand to Asia" while another is 0.9 confident in "do NOT expand to Asia."

**Mitigation (shipped):** the measured agreement now blends mean confidence with the agents' **position overlap** (rescaled so unrelated positions score 0 and restated ones 1), and the hybrid gate additionally requires few dissenters, few open high-severity critiques, converged confidence, no standing Ethics veto and a minimum number of rounds. Positions about genuinely different things keep the overlap term low, and an agent that opposes the others often raises high-severity critiques, which count against consensus. The optional V2 semantic engine swaps word overlap for embedding similarity, which handles paraphrases better.

**Remaining gap (say it plainly):** the gate *reduces* false consensus, it doesn't eliminate it. Overlap is stance-blind with or without V2. "Expand to Asia" and "do NOT expand to Asia" share almost every word, so their Jaccard overlap is high and rescales to ~1.0, and sentence embeddings also put them close together. If the opposed agents are confident and don't flag each other with high-severity critiques, the gate can still pass. A contradiction check (NLI model) between positions would be the real fix.

### Premature Termination
**Problem:** Debate ends in round 1 because agents produce uniformly high confidence on their initial proposals (before any cross-examination).

**Why it happens:** LLMs tend to be overconfident on initial responses. If `consensus_threshold=0.60` (quick mode), a mean confidence of 0.60 is reached without any actual debate.

**Mitigation:** confidence alone can't end a debate: the gate also needs real position overlap, few dissenters and few open critiques, and `min_rounds` (2 for Standard, 3 for Thorough) means a single round can't end a multi-round debate. The Moderator's `should_continue` opinion is advisory and ignored by the routing. In Quick mode (`min_rounds` 1, no critiques) an early stop is by design — speed over depth.

### Infinite Oscillation
**Problem:** Agents keep changing positions (high drift) without converging. Round N position contradicts round N-1 position, which contradicts round N-2 position.

**Why it happens:** Agents over-weight critiques and swing between extremes.

**How the system handles it:** `max_rounds` is the hard ceiling. The debate terminates with `termination_reason = "max_rounds_reached"` regardless of agreement score. The final decision is the best the Moderator can synthesise from the oscillating positions.

---

## 3. RAG Edge Cases

### Knowledge Base Empty or Unavailable
**What happens:** Agent prompts are enriched with `_enrich_with_kb()`, but ChromaDB returns no results or isn't installed.

**How the system handles it:** The `_enrich_with_kb()` method returns the original prompt unchanged:
```python
try:
    chunks = await self.knowledge_base.retrieve(query)
    if chunks:
        return f"{user_prompt}\n---\nContext:\n{context}"
except Exception:
    self.logger.warning("kb_retrieval_failed")
return user_prompt  # Fallback: prompt without KB context
```

### Irrelevant Chunks Retrieved
**Problem:** User uploads a financial report, then asks about cybersecurity. The top-k chunks are about stock prices, not security vulnerabilities.

**Why it happens:** Cosine similarity finds the "most similar" chunks, not the "most relevant." If the entire KB is finance-related, the "most similar" to a security query is still a finance chunk.

**Mitigation:** The similarity threshold (0.30) filters out clearly unrelated chunks. It's deliberately permissive, because MiniLM cosine runs low even for relevant passages, so it won't catch everything: if the query contains words like "risk" or "impact" that also appear in financial context, irrelevant chunks may still pass.

**Future improvement:** Query classification to decide whether to use KB at all, or metadata-filtered retrieval (only search chunks from documents tagged as relevant to the query domain).

### Chunk Boundary Information Loss
**Problem:** A critical fact spans two chunks. The overlapping window captures it in both, but the relevant context is truncated in each.

**Example:** "The regulatory deadline is March 31, 2026. Failure to comply results in a $10M fine per occurrence." If the chunk boundary falls between these sentences, one chunk has the date without the penalty, the other has the penalty without the date.

**Mitigation:** 200-character overlap is designed to catch this for typical sentence lengths. But for very long sentences or multi-sentence reasoning chains, information can still be split.

---

## 4. Concurrency & State Race Conditions

### Two SSE Subscribers + Background Task Modifying State
**Problem:** An SSE endpoint reads `debate_store[thread_id]` while the background task is writing to it.

**How the system handles it:** Per-thread `asyncio.Lock` in `dependencies.py`:
```python
lock = get_thread_lock(thread_id)
async with lock:
    debate_store[thread_id] = final_state
```

Both the background task (writing state) and the SSE route (reading status) acquire the same lock. Since `asyncio.Lock` is cooperative (not preemptive), this prevents torn reads.

### Multiple Debates Sharing State
**Problem:** Two concurrent debates could corrupt each other's state if they share the same in-memory objects.

**How the system handles it:** Each debate creates its own `DebateState` with a unique `thread_id`. Debate stores are keyed by thread_id. LangGraph checkpoints are scoped by `{"configurable": {"thread_id": ...}}`. No shared mutable state between debates.

---

## 5. Human-in-the-Loop Edge Cases

### User Never Approves
**Problem:** A supervised debate reaches convergence, emits `approval_required`, and waits. The user closes the browser and never approves.

**How the system handles it:** The debate state is persisted as `status = "awaiting_approval"`. On server restart, orphaned awaiting-approval debates remain in the DB. They're visible in the history page but won't auto-resume.

**Current gap:** No timeout on HITL approval. The debate waits forever. A production system would add a configurable approval timeout (e.g., 24 hours) after which the debate auto-approves or auto-cancels.

### User Approval After Server Restart
**Problem:** The server crashes while a debate is awaiting approval. After restart, the user clicks "Approve."

**How the system handles it:** The `POST /debate/{thread_id}/approve` endpoint calls `DebateGraph.approve()`, which uses `DebateGraph.resume()` internally. `resume()` loads the LangGraph checkpoint from SQLite to reconstruct the graph state and continues execution from the interrupt point.

---

## 6. Scaling Edge Cases

### Memory Exhaustion from Large Debate History
**Problem:** Thousands of completed debates accumulate in `_debate_store` and `_decision_store` (in-memory dicts).

**How the system handles it:** `DEBATE_TTL_DAYS=90` triggers `cleanup_old_debates()` at startup, removing DB records older than 90 days. However, in-memory dicts are NOT cleaned — they grow unbounded during a server session.

**Production fix:** Add a background task that periodically evicts completed debates from memory (they're already in the DB).

### SSE Queue Memory Leak
**Problem:** A client connects, then disconnects without the server detecting it. The `asyncio.Queue` accumulates events that nobody reads.

**How the system handles it:** The SSE generator checks `request.is_disconnected()` periodically. On disconnect, the queue is removed from the queue list. A watchdog timeout (30s idle) also triggers cleanup.

**Edge case:** If the client disconnects during a brief network blip, the queue may not be cleaned up immediately. It'll be garbage collected when the debate finishes and the queue list is cleared.

---

## 7. LLM-Specific Edge Cases

### Token Limit Exceeded
**Problem:** After adding KB context, tool outputs, memory lessons, and prior round summaries, the prompt exceeds the model's context window.

**How the system handles it:** Currently, **it doesn't handle this explicitly.** The LLM provider will either truncate or return an error.

**Mitigations in practice:**
- KB context is capped at top-5 chunks (max ~5000 characters)
- Tool output for web search is capped at 2000 characters
- Memory injection is capped at 5 lessons
- Prior round formatting truncates positions to 200-400 characters

**Production fix:** Add a token counter that checks prompt length against the model's context window and intelligently truncates (summarise prior rounds instead of including raw text).

### Model Hallucination in Evaluation
**Problem:** The LLM-as-judge evaluator scores a terrible decision as 0.95 completeness because it generates a convincing justification.

**Why it happens:** LLMs are agreeable and can justify almost anything if prompted to. The evaluator might rationalise gaps in the decision rather than identifying them.

**Mitigation:** The evaluation prompt is calibrated to be "critical" and includes specific scoring anchors ("0.9–1.0 = excellent, below 0.5 = poor"). But this is still prompt engineering, not a fundamental solution.

**Future fix:** Compare against a rubric of expected elements (does the decision mention risk? alternatives? timeline?) for semi-deterministic scoring.
