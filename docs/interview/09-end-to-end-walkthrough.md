# 🔄 End-to-End Execution Walkthrough

> This document traces a single debate request from the first HTTP byte to the final decision rendered on screen. It follows the async streaming path used by the live UI: `POST /debate/start-async` plus `GET /debate/{thread_id}/stream`.

---

## Phase 0: Application Startup

Before any request is handled, the server boots:

```
uvicorn app.main:app --reload
```

### What Startup Actually Prepares
During startup, the backend:

1. Runs migrations and TTL cleanup for old debates
2. Initializes the knowledge base and agent-memory stores
3. Registers built-in core and domain agents in `AgentRegistry`
4. Prepares in-memory stores for active debates, SSE queues, replay buffers, and background tasks

The important interview point is that the app is ready for both synchronous execution and the live async/SSE path before the first request arrives.

---

## Phase 1: User Submits a Question (Frontend)

### User Action
User types "Should we expand into the Asian market?" on the New Debate page. Selects:
- Mode: `Custom` — Standard's full-critique config (threshold 0.75) run with a 4-round budget, so the full debate loop has room to iterate (the `standard` preset itself now caps at 2 rounds)
- Agents: the default debate panel or a chosen subset
- Supervised: No
- Optional: knowledge base and agent memory, if enabled

### Frontend API Call (`lib/api.ts`)
```typescript
const start = await startDebateAsync({
    query: "Should we expand into the Asian market?",
    mode: "standard",
    agents: ["Analyst", "Risk", "Strategy", "Ethics"],
    supervised: false,
});

const threadId = start?.thread_id;
const streamUrl = start?.stream_url;
```

---

## Phase 2: API Receives the Request (Backend)

### Route Handler (`api/routes.py`)
```python
@router.post("/debate/start-async", response_model=AsyncDebateStartResponse)
@limiter.limit(f"{app_settings.RATE_LIMIT_PER_MINUTE}/minute")
async def start_debate_async(request: Request, body: DebateStartRequest, ...):
```

### Step-by-step:

**2.1 — Pydantic Validation**
`DebateStartRequest` validates:
- `query`: non-empty string
- `mode`: one of `"quick"`, `"standard"`, `"thorough"`
- Optional overrides: `max_rounds`, `consensus_threshold`, `skip_critique_phase`
- Optional agent selection: `agents` or `domain_pack`
- Flags such as `supervised`, `use_knowledge_base`, and `enable_agent_memory`

If invalid, FastAPI returns 422 with field-level errors. Request never reaches business logic.

**2.2 — Resolve Debate Config from Mode + Overrides**
```python
resolved_rounds, resolved_threshold, resolved_skip = resolve_debate_config(
    mode=body.mode,
    max_rounds=body.max_rounds,
    consensus_threshold=body.consensus_threshold,
    skip_critique_phase=body.skip_critique_phase,
    default_max_rounds=settings.MAX_DEBATE_ROUNDS,
    default_threshold=settings.CONSENSUS_THRESHOLD,
)
```

**2.3 — Create DebateState**
```python
debate_state = DebateState(
    user_query=body.query,
    max_rounds=resolved_rounds,
    use_knowledge_base=bool(body.use_knowledge_base),
    enable_agent_memory=bool(body.enable_agent_memory),
    selected_agents=selected_agents,
    domain_pack=domain_pack,
)
```

**2.4 — Create SSE Channels + Persist Initial State**
```python
thread_id = debate_state.thread_id
all_queues[thread_id] = []
all_replays[thread_id] = []
debate_store[thread_id] = debate_state
await _persist_debate_state(debate_state, settings.DATABASE_URL)
```

**2.5 — Launch Background Task**
```python
task = asyncio.create_task(
    _run_debate_background(
        graph,
        debate_state,
        debate_store,
        decision_store,
        all_queues,
        settings.DATABASE_URL,
        consensus_threshold=resolved_threshold,
        skip_critique_phase=resolved_skip,
        hitl_mode=bool(body.supervised),
    )
)
```

**2.6 — Return Immediately**
```python
return AsyncDebateStartResponse(
    thread_id=thread_id,
    status="initialized",
    stream_url=f"/debate/{thread_id}/stream",
)
```

The client receives the `thread_id` within milliseconds. The debate hasn't started yet — it runs in the background.

---

## Phase 3: Debate Execution (LangGraph)

### Background Task Entry
```python
async def _run_debate_background(graph, debate_state, debate_store, decision_store, ...):
    final_state, decision = await graph.run(
        debate_state.user_query,
        initial_state=debate_state,
        consensus_threshold=resolved_threshold,
        skip_critique_phase=resolved_skip,
        hitl_mode=hitl_mode,
    )
    debate_store[thread_id] = final_state
    if decision is not None:
        decision_store[thread_id] = decision
        await _persist_debate(final_state, decision, database_url)
```

### LangGraph State Machine
The `DebateGraph` compiles a `StateGraph` with this topology:

```
         ┌──────────────────────────────────────────────┐
         │                                              │
         ▼                                              │
    [proposals] → [critiques] → [revisions] → [convergence]
                                                   │
                                              (converged?)
                                              ├── No → (loop back to proposals)
                                              └── Yes ↓
                                                [finalize]
```

### Node 1: Proposals (Round 1)

**What happens:** Each agent generates an initial analysis of the question.

```python
async def proposal_node(state: DebateGraphState) -> dict:
    tasks = []
    for agent_name in state["agents"]:
        agent = AgentRegistry.get(agent_name)
        tasks.append(run_agent_with_timeout(agent, state, timeout=15.0))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Filter out timeouts and errors
    agent_outputs = [r for r in results if isinstance(r, AgentResponse)]
    
    # Emit SSE event for each successful output
    for output in agent_outputs:
        emit("agent_output", {
            "round_number": state["debate_state"].current_round,
            "phase": "proposal",
            "agent_name": output.agent_name,
            "position": output.position,
            "confidence_score": output.confidence_score,
        })
    
    return {"debate_state": state["debate_state"]}
```

**Inside each agent's `run()` method:**
1. Build system prompt (agent-specific persona + instructions)
2. Enrich with KB context: `_enrich_with_kb(question)` → adds relevant chunks from ChromaDB
3. Enrich with memory: `_enrich_with_memory(question)` → adds lessons from past debates
4. Enrich with tools: If tools are configured, execute them and inject results
5. Call LLM: `llm.with_structured_output(AgentResponse).ainvoke(messages)`
6. Parse response into `AgentResponse(position, confidence_score, key_risks, ...)`
7. Return `AgentResponse`

### Node 2: Critiques (Round 1)

**What happens:** Each agent critiques ALL other agents' proposals.

```python
async def critique_node(state: DebateGraphState) -> dict:
    for agent_name in state["agents"]:
        agent = AgentRegistry.get(agent_name)
        # Agent receives: the question + all other agents' proposals
        other_proposals = [o for o in state["agent_outputs"] if o.agent_name != agent_name]
        critique = await agent.critique(question, other_proposals)
        # critique includes: strengths, weaknesses, questions for each other agent
```

**Key insight:** Agents see each other's positions for the first time here. This is where the "debate" actually happens — agents challenge assumptions, point out blind spots, and question each other's reasoning.

### Node 3: Revisions (Round 1)

**What happens:** Each agent updates their position based on critiques received.

```python
async def revision_node(state: DebateGraphState) -> dict:
    for agent_name in state["agents"]:
        agent = AgentRegistry.get(agent_name)
        # Agent receives: their original proposal + all critiques of it
        my_critiques = [c for c in critiques if c.target_agent == agent_name]
        revised = await agent.revise(original_proposal, my_critiques)
        # revised.confidence_score may be higher or lower than original
```

**Confidence dynamics:** After receiving critiques:
- Agent that was overconfident may lower confidence (e.g., 0.9 → 0.7)
- Agent that was uncertain may gain confidence if others validated their position (e.g., 0.6 → 0.8)
- Agent may fundamentally change their position if critiques were compelling

### Node 4: Convergence Check + Moderator

**Step 1 — Moderator Synthesis (advisory):**
```python
synthesis = await moderator.synthesize(ds)
# synthesis includes:
#   summary: "Agents broadly agree on market opportunity but diverge on timing..."
#   agreement_areas: [...]
#   disagreement_areas: [...]
#   should_continue: True/False   # advisory only — logged, not used for routing or sent to the UI
# If this call fails (e.g. a rate limit), a placeholder summary is used and the round still scores.
```

**Step 2 — Calculate Agreement Score:**
```python
confidence_agreement = mean(o.confidence_score for o in agent_outputs)          # V1, shown separately
position_agreement = normalize(confidence_weighted_jaccard(agent_outputs))   # 0.08 → 0, 0.19 → 1
lexical_agreement = 0.7 * confidence_agreement + 0.3 * position_agreement
stance_agreement = compute_stance_agreement(agent_outputs)   # confidence-weighted largest stance group; None if < 2 voters
semantic_agreement = mean_cosine(...)                         # only with SEMANTIC_CONSENSUS_ENABLED; diagnostic

method = ds.agreement_method or settings.AGREEMENT_METHOD    # "stance" by default
agreement_score = stance_agreement            # if method == "stance"
              # 0.5 * confidence_agreement + 0.5 * semantic_agreement   if method == "semantic"
              # lexical_agreement            if method == "lexical", or as the fallback when the chosen score is None
```

**Step 3 — Convergence Decision (Hybrid 6-signal gate):**
```python
# Consensus requires ALL six signals to hold (is_consensus_reached):
consensus = (
    active_vetoes == 0                                   # no Ethics veto stands
    and agreement_score >= consensus_threshold           # score from Step 2 (stance vote by default)
    and rounds_completed >= min_rounds                   # 1 round can't end it
    and dissenting_agents <= 1                            # at most one agent votes against the majority
    and open_disagreements <= 2                           # high/critical critiques still open after revision
    and confidence_converged                             # drift low / spread tight
)

if consensus:                     return "finalize"   # consensus_reached
if current_round >= max_rounds:   return "finalize"   # out of rounds
return "proposals"                                    # keep debating
# (supervised mode routes a stop decision through the hitl node first)
```

**Step 4 — If supervised mode and the gate says stop (consensus or out of rounds):**
```python
if supervised and not should_continue:
    emit("approval_required", {...})
    # Graph pauses in the hitl node until POST /debate/{thread_id}/approve
    # (/resume is refused for a debate paused for review)
```

### Round 2+ (If Not Converged)

The loop repeats: proposals → critiques → revisions → convergence. Each round, agents have richer context:
- They've seen each other's positions
- They've received and processed critiques
- The Moderator has summarised areas of agreement/disagreement

Illustrative convergence pattern:
- Round 1: Wide spread of opinions (agreement ~0.5)
- Round 2: Positions narrow after critiques (agreement ~0.65)
- Standard (threshold 0.75, max 2 rounds) ends here either way: `consensus_reached` if all six signals hold, otherwise `max_rounds_reached`
- Thorough (threshold 0.85, min 3, max 6) keeps going, e.g. ~0.78 in round 3 and ~0.86 in round 4, until the gate passes or the rounds run out

### Node 5: Finalize

**What happens:** The Moderator generates the final decision.

```python
async def finalize_node(state: DebateGraphState) -> dict:
    decision = await moderator.generate_final_decision(
        question=question,
        all_round_outputs=state["round_snapshots"],
        agreement_score=state["agreement_score"]
    )
    # decision: FinalDecision(
    #   recommendation: str,
    #   confidence: float,
    #   key_factors: List[str],
    #   dissenting_views: List[str],
    #   risk_summary: str,
    #   implementation_notes: str,
    #   termination_reason: "consensus_reached" | "max_rounds" | ...
    # )
    
    # Store agent memory for future debates
    emit("debate_completed", {
        "thread_id": ds.thread_id,
        "termination_reason": ds.termination_reason,
        "total_rounds": ds.current_round,
        "agreement_score": ds.agreement_score,
    })
    
    return {"debate_state": ds, "final_decision": decision}
```

After the graph finishes, the background runner persists the result and pushes a separate `final_decision` event to all connected SSE subscribers.

---

## Phase 4: SSE Streaming (Real-Time Updates)

### How the Frontend Receives Updates

**Frontend subscribes immediately after creating the debate:**
```typescript
const controller = connectToStream(threadId, {
  onEvent: (event) => {
    switch (event.type) {
      case "round_started":
      case "phase_started":
      case "agent_output":
      case "critique_completed":
      case "synthesis":
        // Update the live timeline and charts
        break;
      case "approval_required":
        // Show supervised approval UI
        break;
      case "debate_completed":
        // Debate loop is finished
        break;
      case "final_decision":
        // Render the final answer and close the stream
        break;
    }
  },
});
```

**Backend SSE endpoint (`routes.py`):**
```python
@router.get("/debate/{thread_id}/stream")
async def stream_debate(thread_id: str, request: Request):
    personal_queue = asyncio.Queue()
    all_queues.setdefault(thread_id, []).append(personal_queue)
    replay_snapshot = await get_debate_events(db, thread_id, after_event_id=last_event_id)
    
    async def event_generator():
        for payload in replay_snapshot:
            yield _sse_line(payload["type"], payload)

        while True:
            payload = await asyncio.wait_for(personal_queue.get(), timeout=20.0)
            if payload is None:
                break
            yield _sse_line(payload["type"], payload)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### SSE Event Timeline (Standard Mode, 3 Rounds)

```
t=0s      POST /debate/start-async → 200 {thread_id, stream_url}
t=0.1s    GET /debate/{id}/stream → SSE connection opened
t=0.2s    event: debate_started
t=0.3s    event: round_started (round=1)
t=0.3s    event: phase_started (phase=proposal)
t=1s      event: agent_output (Analyst, proposal, confidence=0.75)
t=1.5s    event: agent_output (Risk, proposal, confidence=0.60)
t=2s      event: agent_output (Strategy, proposal, confidence=0.80)
t=2.5s    event: agent_output (Ethics, proposal, confidence=0.70)
t=3s      event: phase_started (phase=critique)
t=5s      event: phase_started (phase=revision)
t=7s      event: synthesis (agreement=0.58)   # gate: keep going
t=8s      event: round_started (round=2)
...
t=15s     event: synthesis (agreement=0.68)
t=22s     event: debate_completed (agreement=0.79)
t=22.1s   event: final_decision
```

Total wall-clock time: ~20-30 seconds for 3 rounds with Groq (fast inference).

---

## Phase 5: Results Display (Frontend)

### Final Decision Fetch
```typescript
// After final_decision, or on page load for a completed debate:
const status = await getDebateStatus(threadId);
const decision = await getDecision(threadId);
```

### What the Results Page Shows
1. **Final Recommendation** — The Moderator's synthesised answer
2. **Confidence Score** — Overall system confidence
3. **Key Factors** — Bullet points of major considerations
4. **Agent Positions** — Each agent's final position with confidence bar
5. **Round Timeline** — Expandable round-by-round breakdown
6. **Dissenting Views** — What agents disagreed about
7. **Risk Summary** — Consolidated risk assessment
8. **Convergence Chart** — Agreement score over rounds (recharts line chart)

---

## Phase 6: Post-Decision (Evaluation & Persistence)

### Evaluation (Optional)
```python
evaluator = Evaluator()
eval_result = await evaluator.evaluate(question, final_decision)
# Scores: completeness=0.85, consistency=0.90, actionability=0.75, risk_awareness=0.80
```

### Database Persistence
The async path persists four kinds of data:

1. Debate state snapshots to the debates table
2. Final decisions to the decisions table
3. Streamed events to the debate_events table for replay/recovery
4. Summarised lessons to the agent_memory table

### Agent Memory Storage
Each agent stores a summarised lesson for future debates:
```python
# For the analyst agent:
lesson = await llm.summarize(
    f"Question: {question}\nMy position: {my_final_position}\n"
    f"Outcome: {final_decision.recommendation}\n"
    f"What I learned: ..."
)
# stored in SQLite: agent_memory(agent_name, debate_id, summary, lesson_learned, created_at)
```

In the next debates with memory enabled, the analyst's five most recent lessons are injected into its system prompt (retrieval is by recency today, not by similarity to the new question).

---

## Complete Data Flow Summary

```
User types question
         │
         ▼
    [Frontend: POST /debate/start-async]
         │
         ▼
    [FastAPI: Validate → Create state + SSE channels → Launch asyncio task → Return thread_id]
         │                              │
         │                              ▼
         │                    [LangGraph: Build graph]
         │                              │
         │                    ┌─────────┼──────────┐
         │                    │    Per Round Loop   │
         │                    │                     │
         │                    │  Proposals ──────►  │
         │         SSE ◄──────│  Critiques ──────►  │
         │                    │  Revisions ──────►  │
         │                    │  Convergence ─────► │
         │                    │    (check)          │
         │                    │     │ No → loop     │
         │                    │     │ Yes ↓         │
         │                    │  [Finalize]         │
         │                    └─────────────────────┘
         │                              │
         │              ┌───────────────┼───────────────┐
         │              ▼               ▼               ▼
         │         [Save to DB]  [Store Memory]  [Evaluate]
         │
         ▼
    [Frontend: Render results with charts + timeline]
```
