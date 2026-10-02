# 🧠 Mental Models & Intuition

> Interview use: choose one analogy and one intuition pump. Treat this file as a recall aid, not a script to recite section by section.

## 1. The Boardroom Analogy

**Think of this system as a corporate boardroom meeting.**

| Boardroom Role | System Component | Why This Mapping Works |
|---|---|---|
| CEO asks a strategic question | User submits a question via API | Both initiate a decision process |
| CFO (financial analyst) | Analyst Agent | Provides data-driven, quantitative analysis |
| Chief Risk Officer | Risk Agent | Identifies what could go wrong |
| VP of Strategy | Strategy Agent | Proposes competitive moves and positioning |
| General Counsel / Ethics Board | Ethics Agent | Flags moral, legal, and societal concerns |
| Chief of Staff / Board Chair | Moderator Agent | Synthesises, mediates, drives to conclusion |
| Meeting agenda & rules | DebateConfig | Defines how many rounds, what format, when to stop |
| Meeting minutes | Round snapshots + DB persistence | Records what was said, when, and by whom |
| Past meeting archives | Agent Memory Store | Agents remember lessons from previous debates |
| Company knowledge base | ChromaDB RAG | Reference documents that inform the discussion |
| Time limit per speaker | Agent timeout (15s) | Forces concise, focused contributions |
| Consensus vote | ConsensusEngine agreement score | Determines if the group has reached a decision |

**When to use this analogy in an interview:**
> "The system models a structured board meeting where specialist executives each analyse a strategic question from their domain, then cross-examine each other's analysis, revise their positions, and a moderator synthesises the discussion into a final recommendation."

This analogy immediately communicates:
- Why multiple agents exist (diverse expertise)
- Why there are rounds (iterative refinement)
- Why there's a moderator (someone must synthesise)
- Why there's a consensus mechanism (group decision)

---

## 2. The Judicial System Analogy

**For explaining the critique/revision cycle:**

| Legal Concept | System Phase | What It Achieves |
|---|---|---|
| Opening statements | Proposal phase | Each party lays out their initial position |
| Cross-examination | Critique phase | Each party challenges the others' arguments |
| Rebuttal | Revision phase | Each party strengthens their case in response |
| Jury deliberation | Convergence check | Do we have agreement? |
| Judge's ruling | Final decision (Moderator) | Authoritative synthesis of all arguments |
| Appeals process | Multi-round debate | If first round fails, try again with better arguments |
| Case law | Agent memory | Past decisions inform future analysis |
| Expert witnesses | Tool calls | Agents bring external evidence (web search, calculations) |
| Ethics review | Ethics Agent veto | Blocks a "consensus" verdict while a serious ethical objection stands; the human still decides |

**Why this analogy is powerful for interviews:**
It explains WHY critique → revision matters. A single-pass LLM gives you an "opening statement" — confident but untested. The cross-examination (critique) exposes weaknesses. The rebuttal (revision) produces a battle-tested position.

---

## 3. The Scientific Peer Review Analogy

**For explaining quality assurance:**

| Peer Review | System Component |
|---|---|
| Researcher submits a paper | Agent generates proposal |
| Reviewers critique the paper | Other agents critique the proposal |
| Author revises and resubmits | Agent revises based on critiques |
| Editor decides: accept/revise/reject | Convergence check decides: finalize or continue |
| Published paper | Final decision |
| Citation count | Evaluation scores (completeness, consistency, etc.) |

**Key insight this analogy provides:**
"No serious science is published without peer review. Why should AI-generated strategic decisions be accepted without cross-examination? This system implements peer review for LLM outputs."

---

## 4. Think Like Each Component

Use this table when you want to explain the role of each component quickly.

| Component | Default instinct | Common failure mode it corrects |
|---|---|---|
| Analyst | Quantify the problem and surface evidence | Hand-wavy recommendations with weak factual grounding |
| Risk | Stress-test assumptions and expose downside | Optimistic plans that ignore failure modes |
| Ethics | Check fairness, harm, and compliance | Recommendations that are profitable but unsafe or unacceptable |
| Strategy | Turn analysis into options and execution paths | Good observations with no clear plan |
| Moderator | Synthesize, weigh trade-offs, and close the debate | Fragmented outputs that never become a decision |
| Convergence Engine | Ask whether there is enough agreement to stop | Endless debate loops or premature stopping |
| LangGraph | Enforce sequence, state, and resumability | Ad hoc orchestration that is hard to pause, debug, or recover |

---

## 5. Key Intuition Pumps

### Intuition 1: "Why Not Just Ask GPT-4 Directly?"
Single LLM call gives you one perspective. Multi-agent debate adds explicit role separation, critique, revision, and measurable convergence.

**Analogy:** Asking one person for advice vs convening a panel of experts.

### Intuition 2: "Why Structured Output Instead of Free Text?"
Free text is hard to validate, compare, and aggregate. Structured output gives the system typed fields, confidence values, and a stable schema for consensus and persistence.

**Analogy:** An API that returns JSON vs one that returns prose. Both contain the same information, but only one is programmable.

### Intuition 3: "Why Rounds Instead of One Big Prompt?"
You could theoretically write one massive prompt:
> "You are 4 experts. First, each give your analysis. Then critique each other. Then revise. Then build consensus."

This fails because:
- LLMs struggle with multi-step instructions in one call (they forget or skip steps)
- No real adversarial process (the model role-plays the debate, it knows what it will say next)
- No measurable convergence (no intermediate checkpoints)
- No human intervention point (can't stop mid-prompt)
- Context window limits (one call can't hold 4 agents × critiques × revisions)

Multi-round orchestration is the value: explicit state, checkpoints, conditional routing, and interruptibility.

### Intuition 4: "Where Does Quality Come From?"
Quality in this system emerges from **constraint and structure**, not from any single LLM call being "better."

Main sources of improvement over raw LLM output:
1. **Lens constraint** — each agent stays in role.
2. **Cross-examination** — critiques expose blind spots.
3. **Revision pressure** — agents must answer criticism.
4. **Measurement** — confidence and similarity make stopping criteria explicit.
5. **Grounding** — RAG and memory anchor the debate in prior evidence.

**Analogy:** A bridge isn't strong because of any single beam. It's strong because of how the beams are arranged and connected. This system is the arrangement.

### Intuition 5: "State Machine vs Just Running Code"
Why LangGraph instead of a for-loop?

```python
# Simple approach:
for round in range(max_rounds):
    proposals = await get_proposals()
    critiques = await get_critiques(proposals)
    revisions = await get_revisions(critiques)
    if converged(revisions): break
```

This works for simple cases. LangGraph adds:
- **Checkpointing:** Save state after every node. Resume from any point. Survive crashes.
- **Conditional edges:** Branch based on runtime conditions (converged — incl. no standing ethics veto? supervised? quick mode?).
- **Interrupt/resume:** HITL pauses the graph mid-execution. A for-loop can't pause.
- **Visualization:** LangGraph can render the graph topology for debugging.
- **Composability:** Add new nodes (e.g., a "fact-check" node) without rewriting the loop.

**Analogy:** A for-loop is like driving with written directions. A state machine is like a GPS — it tracks where you are, can reroute when conditions change, and remembers your position if you stop.

---

## 6. Pattern Recognition for Interview Questions

### "Tell me about a technical challenge you solved"
→ Use the consensus evolution. "We discovered that confidence-based consensus created false consensus when agents were confident but contradictory. We reduced it by blending confidence with how much the agents' positions overlap, and by making termination a six-signal gate that also requires few dissenters, few high-severity critiques, a minimum number of rounds and no standing veto. It isn't fully solved: word overlap and embeddings are both negation-blind, so 'should' vs 'should not' can still look like agreement. An NLI contradiction check is the next step."

### "How did you handle trade-offs?"
→ Use SQLite vs PostgreSQL, SSE vs WebSocket, or any row from the Design Decisions document. Follow the format: "We considered X and Y. We chose X because [reason], accepting the trade-off of [downside]."

### "How would you scale this?"
→ Walk through the Redis + PostgreSQL + Pinecone migration path from document 08. Show you understand the current limitations AND the path forward.

### "What would you do differently?"
→ Pick 2-3 honest improvements:
1. "Add authentication from day one — we deprioritised it for the MVP"
2. "Use PostgreSQL from the start — the SQLite-to-Postgres migration cost us time"
3. "Add OpenTelemetry tracing — debugging multi-agent execution without distributed tracing is painful"

### "Walk me through the code"
→ Use the end-to-end walkthrough (document 09). Start from the HTTP request and trace through every layer. Mention specific function names and data transformations.

### "What are you most proud of?"
→ The debate architecture itself. "A single LLM call gives you a monologue. Our system gives you a structured, measurable adversarial process. The quality improvement isn't from a better model — it's from better process."

---

## 7. One-Sentence Summaries (For Rapid Recall)

| Component | One-Sentence Summary |
|---|---|
| AgentBoard | A structured adversarial debate system where AI agents with different specialist lenses cross-examine each other to produce better decisions than any single LLM call. |
| BaseAgent | Template Method pattern that standardises every agent's lifecycle: enrich prompt → call LLM → parse structured output. |
| LangGraph | State machine that manages the propose → critique → revise → converge loop with checkpointing, conditional routing, and HITL interrupts. |
| ConsensusEngine | Scores agreement by blending confidence (are agents sure?) with position overlap (are they using the same words? or, with opt-in V2, the same meaning?), then feeds a six-signal gate. Neither overlap measure can see negation. |
| KnowledgeBase | ChromaDB RAG pipeline that grounds agent responses in uploaded documents instead of relying solely on LLM training data. |
| Agent Memory | LLM-summarised one-sentence lessons from past debates, stored per agent in SQLite; the 5 most recent are injected into the agent's prompt. |
| Moderator | The synthesiser — reads all agent outputs and crafts a coherent recommendation that honours the strongest arguments. |
| SSE Streaming | Real-time event pipeline from LangGraph nodes to the browser, enabling live debate visualization. |
| Evaluator | LLM-as-judge that scores decisions on completeness, consistency, actionability, and risk awareness. |
| Simulation | N-run consistency test: same question, multiple debates, calibrated word overlap of the final decisions + risks that recur in any wording. |
