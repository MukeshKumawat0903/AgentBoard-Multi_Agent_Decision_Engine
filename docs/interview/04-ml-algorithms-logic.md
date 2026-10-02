# 🤖 ML, Algorithms & Logic Deep Dive

> Interview use: most interviewers only need three parts from this file: default model choice, consensus scoring, and RAG retrieval.

## What Models/Algorithms Are Used

AgentBoard uses separate model layers for reasoning, retrieval, and agreement scoring.

---

## 1. Large Language Models (LLMs) — The Reasoning Engine

### Models Used
| Provider | Default Model | Use Case | Why This Model |
|----------|-------|----------|----------------|
| **Groq** (default) | LLaMA 3.3 70B Versatile | All agent responses | Free tier, fast inference (~500 tokens/sec), 70B quality |
| **OpenAI** (optional) | GPT-5.5 | Whole-debate or per-agent override | Best structured-output compliance, highest quality |
| **Anthropic** (optional) | Claude Opus 4.8 | Whole-debate or per-agent override | Strong reasoning, long context |
| **Gemini** (optional) | Gemini 3.5 Flash | Whole-debate or per-agent override | Fast, low-cost, large context |

> Four providers are supported via the `LangChainProvider` adapter and switchable at runtime (`/llm-settings`). Note some newer models (Anthropic Opus 4.7+/Fable, OpenAI `gpt-5*`) reject sampling params, so the adapter omits `temperature` for them.

### Why LLaMA 3.3 70B via Groq as Default

**Default-model rationale:**
- Groq provides free-tier API access with high throughput
- 70B parameter model is in the "sweet spot" — large enough for structured reasoning, small enough for fast inference on Groq's LPU hardware
- "Versatile" variant is instruction-tuned for both structured output and free-form reasoning

**Why not a frontier model (GPT-5.5 / Claude Opus) as default?** Cost. A multi-round debate makes dozens of LLM calls (4 agents × N rounds × proposal/critique/revision + per-round moderator synthesis + finalization — standard caps at 2 rounds, thorough at 6). At frontier-model pricing this runs into dollars per debate; with Groq Llama the marginal cost is close to zero. Each `FinalDecision` now carries `token_usage` and `estimated_cost_usd` (from a LangChain usage callback) so you can see the real cost per run.

### How LLMs Are Used

LLMs serve four distinct roles in AgentBoard:

**Role 1: Agent Reasoning (Core)**
Each agent call = 1 LLM invocation with:
- System prompt: Role description + behavioral constraints
- User prompt: The question + context from prior rounds + KB chunks + tool outputs
- Output schema: Pydantic model (`AgentLLMOutput` or `CritiqueLLMOutput`) bound via `with_structured_output()`

**Role 2: Moderator Synthesis**
The Moderator makes 2 types of LLM calls:
- `synthesize()` → `ModeratorSynthesis` schema (agreement areas, disagreement areas, should_continue)
- `finalize()` → `FinalDecisionLLMOutput` schema (decision, rationale, risk flags, alternatives)

**Role 3: Meta-Evaluation (LLM-as-Judge)**
A separate LLM call evaluates the quality of the final decision:
- Input: The decision text + original query
- Output: `EvaluationScores` (completeness, consistency, actionability, risk_awareness, reasoning)
- This is a **different invocation** from the debate itself — it judges the output of the debate

**Role 4: Memory Summarisation**
After each debate, an LLM call summarises each agent's final position into a one-sentence lesson:
- Input: Agent name + final position text
- Output: `_MemorySummaryOutput` (summary, lesson)
- This is a **lightweight call** — just text compression

### Structured Output: How It Actually Works

```python
# What the code does:
result = await llm.with_structured_output(AgentLLMOutput).ainvoke(messages)

# What happens under the hood:
# 1. Pydantic schema → JSON Schema → Function/Tool calling schema
# 2. LLM is instructed to call a "function" with the schema as parameters
# 3. LLM response is parsed as function call arguments
# 4. Arguments are validated against the Pydantic model
# 5. Returns a typed Python object, not a string
```

**Why this is better than prompt-based JSON:**
- Provider-specific optimization: Groq/OpenAI use tool calling (constrained decoding), Anthropic uses tool_use
- Guaranteed valid types: `confidence_score` is always a float in [0, 1], never "high" or "0.8 approximately"
- No regex extraction or JSON.parse fallbacks needed

---

## 2. Sentence Transformers — Semantic Similarity

### Model: all-MiniLM-L6-v2

**What it is:** A 22M parameter transformer model that maps sentences to 384-dimensional dense vectors. Trained via contrastive learning on 1B+ sentence pairs.

**Where it's used:**
1. **RAG embeddings** — Documents are chunked and embedded for ChromaDB storage/retrieval
2. **Semantic similarity** (V2, opt-in via `SEMANTIC_CONSENSUS_ENABLED`) — Agent positions are embedded, and pairwise cosine similarity measures "meaning overlap". It is a **diagnostic** reported every round; it only drives the gate when a debate explicitly picks the `semantic` agreement method (§3)

### Why all-MiniLM-L6-v2 Over Alternatives

| Model | Dim | Speed | Quality (STS Benchmark) | Size |
|-------|-----|-------|------------------------|------|
| **all-MiniLM-L6-v2** | 384 | Fast | 82.6 | 22M params, ~80MB |
| all-mpnet-base-v2 | 768 | Medium | 83.4 | 109M params, ~420MB |
| OpenAI text-embedding-3-small | 1536 | API call | ~83.5 | Cloud-only |
| OpenAI text-embedding-ada-002 | 1536 | API call | ~82.0 | Cloud-only |

**Decision rationale:**
- **Local execution** — No API calls, no cost, no latency. Critical for real-time consensus scoring during debates.
- **Good enough quality** — 82.6 STS benchmark is within 1 point of the best options.
- **Small footprint** — 80MB one-time download. Won't impact deployment size significantly.
- **Lazy loading** — Model is loaded on first use, not at application startup.

### When MiniLM Fails

- **Domain-specific jargon** — Financial regulation terms or medical terminology may not embed well because the model was trained on general web text.
- **Short positions** — If an agent's position is <10 words, the embedding is noisy. The consensus engine requires ≥2 responses to compute similarity.
- **Paraphrases with negation** — "We should expand" and "We should NOT expand" may have high cosine similarity because the sentence structures are identical. This is a known limitation of symmetric embeddings, and the main reason embeddings are not the agreement metric (see V3 in §3).
- **Long positions** — MiniLM truncates input at 256 word-pieces, so only the opening of a long position is embedded.
- **Topic, not verdict** — embeddings encode what a text is *about*. Two agents debating the same decision score high cosine whether they back it or reject it.

---

## 3. Consensus Algorithms — Measuring Agreement

### V1: Confidence-Based (Deterministic, No ML)

```
agreement_score = mean(all agent confidence scores)
```

**Intuition:** If all agents are highly confident, they've likely settled on consistent positions. If confidence is low or divergent, there's still instability.

**Weakness:** Agents can be confidently wrong in opposite directions. Two agents both at 0.9 confidence but proposing contradictory strategies still produce agreement_score = 0.9.

### V1.5: Confidence-Weighted Jaccard

```
For each pair (i, j):
    weight_ij = (confidence_i + confidence_j) / 2
    similarity_ij = jaccard_word_overlap(position_i, position_j)

score = sum(weight_ij * similarity_ij) / sum(weight_ij)
```

**Improvement:** Now considers actual text overlap, weighted by how confident each agent is. High-confidence agents who also use similar words produce high scores.

**Weakness:** Word overlap is a crude proxy. "The company should expand" and "Expansion is recommended for the firm" have low Jaccard despite identical meaning.

### V2: Semantic Hybrid

```
base_score = mean(confidence_scores)                         # V1
semantic_score = mean(pairwise_cosine_similarity(embeddings)) # New
hybrid = (1 - w) * base_score + w * semantic_score           # Blended
```

**Why hybrid?** Pure semantic similarity ignores confidence (an agent might be semantically close but low confidence = still uncertain). Pure confidence ignores meaning. The blend captures both.

**The weight parameter `w`:** Configurable via `SEMANTIC_CONSENSUS_WEIGHT` (default 0.5). In practice:
- w = 0 → pure V1 (fast, crude)
- w = 0.5 → balanced
- w = 1 → pure semantic (slower, more accurate for meaning, ignores confidence)

**Weakness:** the same blind spot as word overlap, one level up. Embeddings encode *topic*, not *verdict*: "expand into SE Asia" and "do not expand into SE Asia" score close. It also blocks: `model.encode()` is CPU-bound, so it now runs in a worker thread (`asyncio.to_thread`) to keep the SSE stream flowing.

**Status today:** with `SEMANTIC_CONSENSUS_ENABLED=true` the cosine score is computed, logged and emitted every round as `semantic_agreement_score`, but it **does not change the agreement score** unless the debate picks `agreement_method="semantic"`. That method is only offered when `semantic_available()` is true (flag on *and* sentence-transformers installed); asking for it otherwise returns 422.

### V3: Stance Vote (default)

The root problem with V1.5 and V2: text similarity, words or embeddings, measures **topic**. Role-bound agents word their agreement differently (low overlap when they agree) and share the same vocabulary when they disagree (high overlap on "should" vs "should not"). So each agent now declares its **verdict** as a structured field, the same pattern as the Ethics `veto`:

```
stance ∈ {support, oppose, conditional, abstain}      # required in the LLM output schema

voters = agents whose stance is not abstain (and not missing)
if len(voters) < 2: return None                       # caller falls back to lexical
weight[stance] = sum(confidence of voters with that stance)
agreement = max(weight) / sum(weight)                 # confidence-weighted share of the largest group
```

- **What the stance is about:** round 1 → the decision the question asks for ("Should we expand?" → support = yes). Round 2+ → the Moderator's one-sentence `leading_proposal` from the previous round, injected into the proposal and revision prompts as "Proposal on the table: …".
- **`conditional` is its own group.** "Yes, if X" is not counted as a plain yes.
- **Analyst abstains** (it makes no recommendations), so the default panel has three voters: Risk, Strategy, Ethics.
- **Veto consistency:** an Ethics-class agent that vetoes cannot also support; `support`/`conditional` with `veto=true` is coerced to `oppose`.

| Vote (similar confidence) | Score | Quick 0.60 | Standard 0.75 | Thorough 0.85 |
|---|---|---|---|---|
| 3 of 3 | 1.00 | ✅ | ✅ | ✅ |
| 2 of 3, dissenter unsure (0.85, 0.85 vs 0.40) | 0.81 | ✅ | ✅ | ❌ |
| 2 of 3, dissenter confident | ~0.67 | ✅ | ❌ | ❌ |
| 2 vs 2 (4 voters) | ~0.50 | ❌ | ❌ | ❌ |

Under the old lexical blend the 2-vs-2 split scored 0.86 (conf 0.80, overlap saturated at 1.0) and passed Thorough. Under stance it scores ~0.52 and never passes.

**Weakness:** it trusts the agent's self-reported label, and the anchor depends on the Moderator naming a sensible leading proposal. Thresholds were kept at 0.60 / 0.75 / 0.85; calibrating them against real debates is still open.

> **What actually ships as the live score:** `AGREEMENT_METHOD` (default `stance`, overridable per debate with `agreement_method` in the start request) picks which score drives Rule 1:
>
> | Method | Formula | Role |
> |---|---|---|
> | `stance` | V3 vote share | Default |
> | `lexical` | `0.7 × mean confidence + 0.3 × rescaled overlap` | Legacy, and the automatic fallback |
> | `semantic` | `0.5 × mean confidence + 0.5 × cosine` | Experimental, needs `semantic_available()` |
>
> The lexical overlap is the V1.5 score **rescaled** onto 0–1 with `POSITION_OVERLAP_FLOOR` 0.08 (unrelated positions → 0) and `POSITION_OVERLAP_CEILING` 0.19 (same stance reworded → 1), because agents writing in different roles share few words even when they agree. If the chosen method cannot produce a score (fewer than two voters, stances missing, semantic engine failed), the lexical blend takes over and the round records `agreement_method_used = "lexical"`. Every available score (confidence, overlap, semantic, stance) is still emitted on the `synthesis` event; only the chosen one feeds the hybrid gate in §4.

### Position Drift Detection

```
For each agent that appears in both rounds:
    drift_i = 1 - jaccard(previous_position_i, current_position_i)

overall_drift = mean(drift_i for all matched agents)
```

**Purpose:** Detect stagnation. If drift < 0.05, agents have stopped changing their positions — further rounds won't produce new insights. It's one way the "confidence converged" signal can pass. Drift is only measured when the two rounds share agents; otherwise it's "not measurable" (`None`), never "0 = stopped moving".

---

## 4. Convergence Decision Logic — Hybrid Consensus Gate

The naïve "stop when mean confidence ≥ threshold" gate was replaced by a **hybrid gate that requires six signals to all hold** (`is_consensus_reached` in `consensus.py`). The single-threshold version let a debate end after one round on confidence alone — the hybrid gate fixes that.

```python
# agreement_score comes from the debate's agreement method (default "stance"):
#   stance   : confidence-weighted vote share of the largest stance group
#   lexical  : 0.7*mean_confidence + 0.3*clip((overlap - 0.08) / (0.19 - 0.08), 0, 1)
#   semantic : 0.5*mean_confidence + 0.5*mean_pairwise_cosine
# Falls back to lexical when the chosen method can't produce a score.

consensus = (
    active_vetoes == 0                                   # no Ethics-class veto stands
    and agreement_score >= consensus_threshold           # e.g. 0.75 (Standard)
    and rounds_completed >= min_rounds                   # floor: 1 round can't end it
    and dissenting_agents <= MAX_DISSENTERS (1)           # few agents below the mean
    and open_disagreements <= MAX_OPEN_DISAGREEMENTS (2)  # few high/critical critiques this round
    and confidence_converged                             # agents stopped moving / uniformly sure
)

if consensus:                       termination_reason = "consensus_reached"; stop
elif current_round >= max_rounds:   termination_reason = "max_rounds_reached"; stop
else:                               continue
```

**The six signals:**
1. **Agreement** — the agreement score clears the threshold. By default that is the stance vote, so it measures verdicts, not confidence or shared wording
2. **Minimum rounds** — at least `min_rounds` completed (1/2/3 for quick/standard/thorough), so a single round can never end a multi-round debate
3. **Dissent** — at most one agent sits more than `MINORITY_REPORT_BAND` (0.20) below the group-mean confidence
4. **Open disagreements** — at most two high/critical critiques raised in this round's critique phase (counted per critic→target critique, however many bullet points it has). They are counted before revisions, and nothing checks whether a revision answered them. In Quick mode critiques are skipped, so this is always 0.
5. **Confidence converged** — agents stopped moving (drift < 0.05) OR confidence spread ≤ 0.15 OR every agent ≥ 0.90 (current-round confidences only)
6. **No veto** — no Ethics-class agent's structured `veto` stands this round

The Moderator's own `should_continue` opinion is **not** a signal — it's logged for comparison only.

**Why this matters in an interview:** it shows you understood that *confidence ≠ agreement*. Two agents can be 90% confident in opposite conclusions. Requiring a majority stance, few dissenters and few high-severity critiques makes that much harder to pass as consensus, and the min-rounds floor stops premature termination. The story to tell is V1 → V2 → stance: confidence alone was fooled by confident opposites, word overlap and then embeddings were both negation-blind (they measure topic), so the gate now counts structured verdicts. Be precise about the limit: the stance is self-reported, and Rules 3–4 (dissent, open disagreements) still use confidence and critique severity. The gate reduces false consensus; it doesn't eliminate it. A human-approved `override` in supervised mode also ends the debate (`termination_reason = "human_override"`). The same `select_dissenting_agents` / `count_open_disagreements` helpers feed both the gate and the final minority report, so they can never disagree.

---

## 5. RAG Algorithm — Retrieval-Augmented Generation

### The Pipeline

```
Document Ingestion:
    text = extract_text(file)          # pypdf for PDF, direct read for TXT/MD
    chunks = sliding_window(text,
        chunk_size=1000,               # characters per chunk
        overlap=200                    # overlapping characters
    )
    embeddings = MiniLM.encode(chunks)
    ChromaDB.upsert(ids, chunks, embeddings, metadata)

Query-Time Retrieval:
    query_embedding = MiniLM.encode(query)
    results = ChromaDB.query(
        query_embedding,
        n_results=5,                   # top-k (KB_TOP_K)
        keep where similarity >= 0.30  # KB_SIMILARITY_THRESHOLD
    )
    context = format_as_numbered_blocks(results)
    enriched_prompt = f"{original_prompt}\n---\nRelevant context:\n{context}"
```

### Chunking Strategy: Why 1000/200?

- **1000 characters** — roughly 200-250 tokens. Small enough to fit multiple chunks in context window; large enough to contain a complete thought.
- **200 character overlap** — ensures sentences split across chunk boundaries are captured in at least one chunk. Without overlap, a key fact at a chunk boundary would be missed.

**Alternative considered:** Semantic chunking (split at paragraph/section boundaries). Rejected because it requires content-aware parsing that doesn't generalise across PDF layouts.

### Similarity Threshold: Why 0.30?

The configured default is `KB_SIMILARITY_THRESHOLD = 0.30` (with `KB_TOP_K = 5`). Cosine similarity of normalised MiniLM embeddings tends to run **low even for clearly relevant chunks** (general-purpose embeddings rarely score a query/passage pair above ~0.6), so a permissive floor of 0.30 keeps genuinely relevant passages instead of discarding them.

- **Too high (0.5–0.8):** the recall problem — relevant paraphrases score below the cutoff and get dropped, so the agent loses useful context.
- **Too low (≈0):** noise creeps in, polluting the prompt.

The trade-off is tuned for recall (don't miss relevant context) and paired with the top-k cap so at most 5 chunks are ever injected.

---

## 6. Simulation Algorithm — Consistency via Repetition

### The Logic

```python
# Run N independent debates concurrently
results = await asyncio.gather(*[run_debate(query) for _ in range(N)])

# Compute consistency: pairwise word overlap, rescaled like the consensus gate
consistency = mean(normalize(jaccard(a, b), floor=0.08, ceiling=0.19) for a, b in pairs(decision_texts))

# Compute confidence variance
variance = stdev(agreement_scores)

# Stable risk flags: the same risk, in any wording, in ≥70% of runs
stable_flags = flags whose content words (lightly stemmed) match a flag in ≥ ceil(0.7 * N) runs

# Rate stability
if consistency > 0.80: "High"
elif consistency > 0.55: "Medium"
else: "Low"
```

### Why 70% Threshold for Stable Flags?

This is a **supermajority threshold** — a risk flag that appears in 2 out of 3 runs (67%) doesn't qualify, but 3 out of 4 (75%) does. This filters out one-off risks that were artifacts of LLM randomness while keeping risks that the system consistently identifies.

### Strengths and Weaknesses

**Strengths:**
- Quantifies LLM reliability for a specific question
- Identifies which risk flags are robust vs noise
- Gives users a "trust score" for the decision

**Weaknesses:**
- N× cost (3 runs = 3× LLM API calls)
- All runs use the same model/temperature, so they share the same systematic biases
- Word overlap is still a lexical measure: the rescaling makes "same decision, different words" score high on average, but two decisions that share vocabulary and differ in substance can still look alike (embeddings would be the next step)

---

## 7. Tool Use — Controlled Agent Actions

### Available Tools

| Tool | Implementation | Input | Output |
|------|---------------|-------|--------|
| `web_search` | DuckDuckGo via langchain-community | Search query | Top-2KB of snippets |
| `calculator` | numexpr (safe arithmetic) | Math expression | Numeric result |
| `get_current_date` | `datetime.now(UTC)` | (none) | "2026-03-25 (Wednesday)" |

### Why These Specific Tools?

**web_search:** Agents operate on training-data knowledge by default. Web search grounds them in current facts. Only the Analyst gets this — other agents shouldn't be "Googling" during a debate.

**calculator:** For when an agent needs to compute a percentage, growth rate, or comparison. Uses `numexpr` (not `eval()`) to prevent code injection.

**get_current_date:** Time-sensitive questions ("Should we expand in Q3?") need to know what month it is. The Strategy agent gets this for time-aware reasoning.

### Security: Why Not Python eval()?

```python
# DANGEROUS:
eval("__import__('os').system('rm -rf /')")

# SAFE:
numexpr.evaluate("2 ** 10 + 1")  # → 1025
```

`numexpr` only evaluates mathematical expressions. It has no access to Python builtins, imports, or the file system. An additional character whitelist prevents even creative injection attempts.

### Tool Execution Cap

Each agent is limited to `max_tool_calls_per_round = 3`. This prevents:
- Runaway tool invocation loops
- Excessive API costs (web searches)
- Debate step timeout (each tool call adds latency)
