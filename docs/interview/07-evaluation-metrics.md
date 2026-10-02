# 📊 Evaluation & Metrics — Deep Dive

## 1. Consensus Metrics

### Agreement Score (V1: Confidence-Based)
```
agreement_score = mean(agent.confidence_score for agent in agents)
```

**What it tells you:** How confident agents are on average. Range: 0.0–1.0.

**What it does NOT tell you:** Whether agents agree with each other. Four agents can be 0.9 confident in four different (even contradictory) conclusions.

**When it's useful:** When you trust that agents self-calibrate — that high confidence reflects genuine conviction rather than LLM overconfidence.

**Interview insight:** "Agreement score V1 is a proxy, not a measurement. It confuses individual confidence with group consensus. We tried position overlap, then embeddings, and ended up asking each agent for a structured stance, inside a multi-signal gate."

> **V1 is no longer the displayed score or the gate.** See "The displayed score" and "The hybrid gate" below.

### Agreement Score (V1.5: Confidence-Weighted Position Overlap)
```python
# For each pair (i, j), i < j:
#   weight_ij     = (confidence_i + confidence_j) / 2
#   similarity_ij = jaccard_word_overlap(position_i, position_j)
score = sum(weight_ij * similarity_ij) / sum(weight_ij)
```

**What it adds:** Considers whether agents actually use the *same words*, weighted by how confident each pair is. Confident agents writing about different things (low overlap) no longer score high. It does **not** catch negation: "expand into Asia" vs "do NOT expand into Asia" share nearly every word, so they overlap heavily.

**Weakness:** word overlap is crude — "expand into Asia" vs "enter the Asian market" overlaps poorly despite identical meaning. That's what the semantic V2 below addresses.

### Agreement Score (V2: Semantic Consensus)
```
semantic_score = mean(
    cosine_similarity(embed(agent_i.position), embed(agent_j.position))
    for all pairs (i,j) where i < j
)

hybrid_score = ((1 - semantic_weight) * confidence_mean) + (semantic_weight * semantic_score)
```

**What it tells you:** How similar the *meaning* of agent positions is (paraphrases score high), combined with confidence.

**Status:** `SEMANTIC_CONSENSUS_ENABLED` (off by default) makes the cosine score a **diagnostic**: it is computed off the event loop, logged and emitted every round as `semantic_agreement_score`, but it does not change the agreement score. The hybrid below only drives the gate when a debate picks `agreement_method="semantic"`, which the API accepts only when `semantic_available()` (flag on and sentence-transformers installed); otherwise it returns 422.

**Components:**
- `confidence_mean`: Same as V1.
- `semantic_score`: Pairwise cosine similarity of sentence embeddings (all-MiniLM-L6-v2, 384-dim vectors).
- `semantic_weight`: Default 0.5 (equal weighting).

**Interpretation:**
| Confidence Mean | Semantic Score | Hybrid Score | Interpretation |
|---|---|---|---|
| High (0.9) | High (0.85) | 0.875 | True consensus: agents agree and are confident |
| High (0.9) | Low (0.3) | 0.60 | Confident but saying different things: the score drops, avoiding a false consensus |
| Low (0.5) | High (0.85) | 0.675 | Agents agree on content but are uncertain |
| Low (0.5) | Low (0.3) | 0.40 | No consensus: uncertain and saying different things |

The "Low semantic score" rows assume the positions are worded differently. Direct contradictions usually aren't, as the edge case below shows.

**Edge case:** Embedding models can report high similarity for semantically different but lexically similar sentences. "We should definitely enter the Asian market" vs "We should definitely NOT enter the Asian market" may have high cosine similarity because most words are identical. Negation detection is a known weakness of sentence embeddings. More broadly, embeddings encode *topic*, not *verdict*, and MiniLM only reads the first 256 word-pieces of a position.

### Agreement Score (V3: Stance Vote, the default)
```python
# Each agent's output carries stance ∈ {support, oppose, conditional, abstain}
voters = [r for r in responses if r.stance and r.stance != "abstain"]
if len(voters) < 2: return None                  # caller falls back to lexical
weight[stance] += r.confidence_score             # per voter
agreement = max(weight.values()) / sum(weight.values())
```

**What it tells you:** The confidence-weighted share of the largest verdict group. It measures *what agents decided*, not how they worded it, so negation and role-specific vocabulary no longer matter.

**Anchor:** round 1 stances are toward the decision the question asks for; round 2+ stances are toward the Moderator's one-sentence `leading_proposal` from the previous round.

**Interpretation** (default panel: Analyst abstains, so Risk, Strategy and Ethics vote):
| Vote (similar confidence) | Score | Quick 0.60 | Standard 0.75 | Thorough 0.85 |
|---|---|---|---|---|
| 3 of 3 | 1.00 | ✅ | ✅ | ✅ |
| 2 of 3, dissenter unsure (0.85, 0.85 vs 0.40) | 0.81 | ✅ | ✅ | ❌ |
| 2 of 3, dissenter confident | ~0.67 | ✅ | ❌ | ❌ |
| 2 vs 2 (4 voters) | ~0.50 | ❌ | ❌ | ❌ |

`conditional` is its own group ("yes, if X" ≠ "yes"), and an Ethics-class veto forces the stance to `oppose`.

**Weakness:** the label is self-reported, and a vague `leading_proposal` makes the vote vague too. The thresholds were kept from the lexical era and have not been re-calibrated against real debates.

### The Displayed Score (what `convergence_node` actually shows)

The live `agreement_score` comes from the debate's agreement method: `agreement_method` in the start request, else `AGREEMENT_METHOD` (default `stance`).

| Method | UI label | Formula |
|---|---|---|
| `stance` | Vote | V3 above |
| `lexical` | Text | `(1 − w)·confidence_mean + w·normalize(confidence_weighted_overlap)`, w = `CONSENSUS_POSITION_WEIGHT` (0.3) |
| `semantic` | Semantic | `(1 − w)·confidence_mean + w·semantic_score`, w = `SEMANTIC_CONSENSUS_WEIGHT` (0.5), no rescaling |

```
normalize(x) = clip((x − 0.08) / (0.19 − 0.08), 0, 1)     # POSITION_OVERLAP_FLOOR / _CEILING
```
The rescaling matters for the lexical blend: agents writing in different roles share few words even when they agree (raw overlap ~0.08 for unrelated positions, ~0.19 for the same stance reworded), so without it the blend could never reach the mode thresholds. It also saturates: same-topic debates hit 1.0, so the lexical score collapses to `0.7 × confidence + 0.3`, which is why a 2-vs-2 split (conf 0.80) scored 0.86 and passed Thorough.

**Fallback:** if the chosen method can't produce a score (fewer than two voters, stances missing in an old debate, semantic engine failed) the lexical blend is used and the round records `agreement_method_used = "lexical"`.

**Every score is reported.** The `synthesis` event carries `agreement_score` plus `agreement_method_used`, `confidence_agreement_score`, `position_agreement_score`, `semantic_agreement_score`, `stance_agreement_score` and `stance_tally` (e.g. `{"support": 2, "oppose": 1, "abstain": 1}`). The UI shows "78% agreement · 2/3 vote" when the method is stance. `FinalDecision` records `agreement_method` and the final-round `stance_tally`.

### The Hybrid Gate (what decides termination)

The score is only one of six signals. A debate converges only when **all** hold (`is_consensus_reached`): agreement score ≥ threshold, `rounds_completed ≥ min_rounds`, `dissenting_agents ≤ 1`, `open_disagreements ≤ 2`, `confidence_converged`, and no standing Ethics veto. This is why "all agents confident after round 1" alone never ends a debate.

### Confidence Drift
```
confidence_drift = abs(agent.confidence_score_round_N - agent.confidence_score_round_1)
```

**What it tells you:** How much an agent's confidence changed during the debate.

**High drift (>0.3):** Agent significantly revised their view — the debate had a real impact.

**Low drift (<0.1):** Agent was stubborn or the debate didn't challenge their initial position.

**Negative vs positive:** If an agent starts at 0.9 and drops to 0.6, that's a 0.3 drift. The agent was challenged and became less certain. This is valuable signal — not a failure.

### Position Drift
```
# As implemented in detect_position_drift (per agent matched across rounds):
position_drift = 1.0 - jaccard_word_overlap(round_N-1_position, round_N_position)
```

**What it tells you:** How much the agent's actual recommendation changed.

**Relationship with confidence drift:**
- High position drift + high confidence drift → Agent genuinely changed their mind
- High position drift + LOW confidence drift → Agent reworded but stayed equally (un)certain
- LOW position drift + high confidence drift → Agent kept the same position but gained/lost confidence

### Round-by-Round Convergence Tracking
The system stores snapshots per round:
```python
round_snapshots.append({
    "round_number": n,
    "summaries": [{agent_name, confidence, position}],
    "agreement_score": current_score,
    "moderator_summary": moderator_output.summary
})
```

**Interview visualization:** "Draw a convergence curve: round on x-axis, agreement score on y-axis. In a healthy debate, you see a monotonically increasing curve. Oscillation signals a problem. A flat curve means the debate isn't changing anything — agents are not engaging with critiques."

---

## 2. Decision Quality Evaluation

### LLM-as-Judge (4 Dimensions)

The Evaluator asks the LLM to score the final decision on 4 axes:

#### Completeness (0.0–1.0)
**What it measures:** Did the decision address all aspects of the question?

**Prompt anchor:**
> Does the decision cover: strategic analysis, risk factors, ethical considerations, and implementation plan?

**Why it's hard:** The LLM judge needs to know what "all aspects" means for a given question. For "Should we enter the Asian market?", completeness means covering market size, competition, regulatory environment, logistics, cultural factors. The judge doesn't have a rubric — it infers the expected scope from the question.

#### Consistency (0.0–1.0)
**What it measures:** Are there internal contradictions?

**Example of inconsistency:** "We recommend aggressive expansion... our risk assessment indicates the market is too volatile for entry." These are contradictory.

**Why it matters:** Multi-agent systems can produce composite decisions where Agent A's recommendation directly contradicts Agent B's risk assessment. The Moderator should catch this, but if it doesn't, the evaluator should flag it.

#### Actionability (0.0–1.0)
**What it measures:** Can someone actually act on this decision?

**High actionability:** "Enter the Thai market through a JV with a local partner within Q3 2025. Budget: $2M. First milestone: regulatory approval by June 2025."

**Low actionability:** "Consider exploring Asian market opportunities at an appropriate time based on market conditions."

#### Risk Awareness (0.0–1.0)
**What it measures:** Does the decision acknowledge and address risks?

**Why this dimension exists:** A common failure mode of LLM-generated decisions is unwarranted optimism. If the decision says "expand aggressively" without mentioning any risks, it's dangerous regardless of how complete or actionable it is.

### Evaluation Confidence
```
overall = mean(completeness, consistency, actionability, risk_awareness)   # EvaluationResult.overall
```

**Shortcoming:** Equal weights assume all dimensions are equally important. For a safety-critical decision, risk_awareness should be weighted higher. For a startup's pivoting decision, actionability matters more.

**Future improvement:** Configurable dimension weights per question domain.

---

## 3. Simulation Metrics

### Cross-Run Consistency
```
consistency_score = mean(
    normalize(jaccard(run_i.decision, run_j.decision), floor=0.08, ceiling=0.19)
    for all pairs (i, j)
)
```

As implemented: pairwise word overlap of the decision texts, rescaled with the consensus gate's anchors — 0.08 (decisions to unrelated questions) → 0, 0.19 (the same decision reworded) → 1. Measured on stored debates, repeat runs of one question overlap ≈ 0.20 raw, so without the rescaling the score could never read "stable". Embedding cosine similarity would be the natural upgrade. `stability_rating` buckets the score: High > 0.80, Medium > 0.55, Low otherwise.

**What it measures:** If you run the same question through the system N times, do you get similar answers?

**Why it matters (interview gold):** LLMs are non-deterministic even at temperature=0 (due to floating-point non-determinism in GPU kernels). A system that gives wildly different answers to the same question is unreliable, regardless of how good each individual answer is.

**Interpretation:**
| Consistency Score | Interpretation | Action |
|---|---|---|
| >0.80 (High) | Highly stable — system reliably reaches similar conclusions | Trustworthy for production use |
| 0.55–0.80 (Medium) | Moderately stable — core conclusions similar, details vary | Acceptable for advisory use |
| ≤0.55 (Low) | Unstable — different runs produce different recommendations | Investigate: are agents' prompts too open-ended? |

### Confidence Stability Across Runs
```
confidence_variance = std_dev(run_i.agreement_score for all runs i)   # SimulationResult.confidence_variance (lower = more stable)
```

**What it measures:** How consistent the confidence/agreement levels are across runs.

**Low stability + high consistency:** Agents reach similar conclusions but with varying confidence. The answer is stable but self-assessment varies.

**Low stability + low consistency:** Both answers and confidence vary. The system is unreliable for this question type.

---

## 4. API & System Metrics

### Rate Limiting Metrics
```
Rate limit: 30 requests/minute per IP (debate creation)
```

**Monitored via:** slowapi `Limiter` with in-memory counters in the current single-instance deployment.

### Response Time Metrics (Prometheus-style)
```python
debate_rounds = DebateRoundsMetric()      # Histogram of rounds to converge
agent_response_time = AgentResponseTime()  # Per-agent LLM call latency
consensus_score = ConsensusScoreMetric()   # Final agreement score distribution
```

**What these tell you at scale:**
- `debate_rounds` histogram: If the median is hitting max_rounds, your consensus threshold is too high or agents can't converge.
- `agent_response_time` by agent: If one agent is consistently 3× slower, it might be using a different model or making tool calls that take long.
- `consensus_score` distribution: If it's bimodal (peaks at 0.4 and 0.9), some question types converge and others don't.

### Analytics Aggregations
```python
GET /analytics/overview → {
    total_debates,
    avg_rounds_to_consensus,
    avg_agreement_score,
    debates_by_termination,
    debates_per_day
}

GET /analytics/convergence → {
    avg_agreement_by_round,
    mode_breakdown: { "quick": 30, "standard": 45, "thorough": 25 },
    domain_pack_breakdown
}
```

**Interview question: "How would you build a dashboard for this?"**
Answer: These analytics already provide the aggregated data. A dashboard would show:
1. **Throughput:** Debates per day (time series)
2. **Quality:** Average consensus score trend (should be stable or improving as you tune prompts)
3. **Cost:** LLM calls per debate × cost per call (derived from rounds × agents × phases)
4. **Reliability:** Completion rate (completed / total) — should be >95%
5. **Latency:** P50/P95 debate duration (time from creation to final decision)

---

## 5. What's NOT Measured (and Should Be)

### Factual Accuracy
The system has no way to verify that agents' claims are factually correct. An agent can confidently state "the Indian market grew 40% last year" and no one checks if that's true. The RAG system helps (it provides real documents as context), but hallucinatory claims outside the KB go undetected.

### User Satisfaction
There's no feedback loop — no way for users to rate whether a decision was actually useful. An end-to-end evaluation would compare system recommendations against what the user actually decided, but this requires longitudinal tracking.

### Debate Efficiency
The system tracks rounds but not wasted rounds. If rounds 2 and 3 produced no meaningful change (same positions, same confidence), those rounds consumed LLM credits for zero information gain. An "information gain per round" metric would help tune when to stop.

### Inter-Agent Influence
The system doesn't track which agent influenced which. If the Risk Agent's critique caused the Strategy Agent to drop confidence from 0.9 to 0.6, that's valuable causal information. Currently, only the aggregate metrics are tracked, not the influence graph.
