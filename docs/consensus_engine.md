# Consensus Engine

## 🟢 What is it?

After every round of debate, a small piece of plain Python code (not an AI) checks whether the agents have truly agreed. If yes, the debate ends with "consensus reached." If not, the agents debate another round. If the rounds run out, the debate ends with "max rounds reached." It never pretends there was agreement.

The Moderator (an AI) also says whether it thinks the debate should continue, but that opinion is only logged. The code decides.

## How it decides

It asks six yes/no questions. Consensus needs a **yes to all six**:

1. **Agreement:** is the majority strong enough?
2. **Min rounds:** have we debated for enough rounds?
3. **Dissent:** is at most one agent overruled?
4. **Open objections:** are at most two serious critiques still unresolved?
5. **Settled:** have positions stopped changing, or are the agents about equally sure?
6. **Veto:** has no Ethics agent vetoed the proposal?

The [worked example](#worked-example-standard-mode) at the end walks through a full two-round debate.

### Key terms

- **Round:** every agent states a position, critiques the others, then revises its own position. The six checks run at the end of the round. (Quick mode skips critiques and revisions.)
- **Stance:** an agent's vote on the proposal: `support`, `oppose`, `conditional` ("yes, if…") or `abstain`.
- **Confidence:** each agent's own rating of how sure it is, from 0 to 1.
- **Critique severity:** `low`, `medium`, `high` or `critical`. Only `high` and `critical` can block consensus.
- **Leading proposal:** the Moderator's one-sentence summary of the plan most agents lean toward. The next round's votes are about it.
- **Mode:** Quick, Standard or Thorough, which set the number of rounds and how strong the majority must be (see [Configuration reference](#configuration-reference)).

### In code

```python
consensus = (
    active_vetoes == 0                                              # Rule 6: Veto
    and agreement_score >= consensus_threshold                      # Rule 1: Agreement
    and rounds_completed >= min_rounds                              # Rule 2: Min rounds
    and dissenting_agents <= MAX_DISSENTERS_FOR_CONSENSUS           # Rule 3: Dissent (1)
    and open_disagreements <= MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS  # Rule 4: Open objections (2)
    and confidence_converged                                        # Rule 5: Settled
)
if consensus:                     termination_reason = "consensus_reached"
elif current_round >= max_rounds: termination_reason = "max_rounds_reached"
else:                             run another round
```

`max_rounds` guarantees the debate always ends. In supervised (HITL) mode a human sees every stop first and can approve it, `override` it (ends as `human_override`) or add one more round (up to 8 in total).

Code: `backend/app/services/consensus.py` (signals and predicate) and `convergence_node` in `backend/app/orchestrator/nodes.py` (wiring).

---

## Rule 1: Agreement

**Question:** Is the majority strong enough?

**Passes when:** `agreement_score >= consensus_threshold` (Quick 0.60, Standard 0.75, Thorough 0.85).

**Why it exists:** the original gate used mean confidence, so two agents 0.9 sure of *opposite* answers looked like 0.9 agreement. Text similarity (word overlap or embeddings) doesn't fix this: it measures topic, not verdict. Asking for the verdict directly does.

**How it's measured:** one of three methods.

| Method | How it works | Status |
|---|---|---|
| **Vote** (`stance`) | Agents vote support / oppose / conditional / abstain; agreement = confidence-weighted share of the largest group | ✅ Default |
| **Text** (`lexical`) | 0.7 × mean confidence + 0.3 × word overlap between positions (confidence-weighted, rescaled to 0–1) | Legacy; automatic fallback |
| **Semantic** (`semantic`, hybrid) | 0.5 × mean confidence + 0.5 × mean pairwise embedding cosine (MiniLM) | Optional, experimental |

- **Choosing:** per debate with the UI row **Agreement [Vote] [Text] [Semantic]** (or `agreement_method` in the start request), otherwise the server default `AGREEMENT_METHOD`.
- **Only Rule 1 changes with the method.** Rules 2–6 are identical. Rule 3 counts stances under every method.
- **Every score is computed every round** (Semantic only when enabled) and reported side by side in the `synthesis` event. `agreement_method_used` names the one that drove the gate.
- **Fallback:** when the chosen score can't be computed (missing stances, fewer than 2 voters, Semantic unavailable or failed), the Text blend takes over, so a debate never stalls on a missing signal. The round records `agreement_method_used = "lexical"` and the log says `agreement_fallback_to_lexical`.

### Vote (default)

Every agent outputs a structured `stance`. Roles that don't recommend (the Analyst) abstain, and a veto forces `oppose`. `conditional` ("yes, if X") is its own group, not a plain yes.

```
agreement = (sum of confidence in the largest stance group) / (sum of confidence of all voters)
```

Round 1 stances are toward the decision the question asks for ("Should we expand?": support = yes). From round 2 on they are toward the Moderator's `leading_proposal` from the previous round (or the question again if it gave none).

**Voter count.** The default panel is Analyst, Risk, Strategy and Ethics. The Analyst abstains, so 3 agents vote:

| Votes | Score | Quick 0.60 | Standard 0.75 | Thorough 0.85 |
|---|---|---|---|---|
| 3 of 3 | 1.00 | ✅ | ✅ | ✅ |
| 2 of 3, dissenter unsure (0.85, 0.85 vs 0.40) | 0.81 (1.70 / 2.10) | ✅ | ✅ | ❌ |
| 2 of 3, dissenter confident (all 0.85) | 0.67 (1.70 / 2.55) | ✅ | ❌ | ❌ |

With two allies at 0.85, the score still passes when the lone dissenter's confidence is at most 0.56 for Standard or at most 0.30 for Thorough. In practice Thorough needs all three voters on one side. (One dissenter is fine for Rule 3.)

### Semantic (optional)

How to enable it, in two steps:

1. Set `SEMANTIC_CONSENSUS_ENABLED=true` and restart the backend. The cosine score (`semantic_agreement_score`) is now computed and reported every round, but it decides nothing. (It also needs `sentence-transformers`, which is in `requirements.txt`.)
2. Choose it: **Semantic** in the UI's Agreement row (greyed out until step 1 is done), `agreement_method: "semantic"` in the request (422 until step 1 is done), or `AGREEMENT_METHOD=semantic` server-wide (falls back to Text until step 1 is done).

- **When it's useful:** comparing methods on real debates (all scores sit side by side in each `synthesis` event), and spotting "same vote, very different reasoning": everyone votes support but the cosine is low.
- **Its limitation:** embeddings measure topic, not verdict, so "should expand" and "should not expand" still look similar. It also reads only the first 256 word-pieces of each position. That's why Vote is the default.
- **Naming:** this is similarity *scoring*, not similarity *search* (that's the RAG knowledge base). With default settings both use `all-MiniLM-L6-v2` and share one loaded copy, so the extra cost is one small encode per round.
- **Mental model:** Vote tells you *what* agents decided; Semantic tells you whether they're *talking about the same thing*.

---

## Rule 2: Min Rounds

**Question:** Have we debated for enough rounds?

**Passes when:** `rounds_completed >= min_rounds` (Quick 1, Standard 2, Thorough 3; never more than `max_rounds`).

**Why it exists:** LLMs are overconfident on first answers. Without a floor, a multi-round debate could stop after round 1, before any cross-examination has had an effect.

**Note:** Standard has `min_rounds = max_rounds = 2`, so in Standard this rule decides the *label* (consensus vs max rounds), not when the debate stops.

---

## Rule 3: Dissent

**Question:** Is at most one agent overruled?

**How it's measured:** a dissenter is a voting agent whose stance differs from the majority stance. The majority is the stance group with the largest summed confidence (the same weighting as Vote). Abstainers never dissent. Fallback when fewer than two agents voted (e.g. debates stored before stances): agents more than `MINORITY_REPORT_BAND` (0.20) below the mean confidence.

**Ties** resolve toward the cautious side: first the larger group, then `oppose` > `conditional` > `support`. So a split board is never reported as backing the proposal. (An even 2-vs-2 split has 2 dissenters either way, so it fails this rule.)

**Passes when:** `dissenting_agents <= MAX_DISSENTERS_FOR_CONSENSUS` (1).

**Why it exists:** Rule 1 measures how strong the majority is; it can look strong while several agents are overruled. Example: 2 supporters at 0.9, one opponent and one conditional at 0.2 score 0.82 on Rule 1 but have 2 dissenters. Rule 3 caps how many voices can be overridden. A confident opponent counts; an unsure ally doesn't.

The same function produces the final decision's **minority report**, so the gate and the report always name the same agents ("Voted oppose while the majority voted support.").

---

## Rule 4: Open Objections

**Question:** Are at most two serious critiques still unresolved?

**How it's measured:** each round runs critiques → revisions → checks. Only `high` and `critical` critiques count. In its revision, each agent replies to every critique it received (`critique_replies`):

- `addressed`: "I changed my position because of it."
- `rebutted`: "It's wrong, and here is why."
- `unaddressed`: "I didn't deal with it."

An objection stays open when it is `unaddressed`, has no reply at all (the revision failed or ran past `AGENT_REVISION_TIMEOUT`), or is `critical` and was only `rebutted`. It is counted once per critic→target pair: two critiques from Risk to Strategy are one objection. The signal is called `open_disagreements` in code and events.

| Reply | `high` | `critical` |
|---|---|---|
| `addressed` | closed | closed |
| `rebutted` | closed | **open** |
| `unaddressed` / no reply | open | open |

**Passes when:** `open_disagreements <= MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS` (2).

Quick mode has no critiques, so this rule passes automatically.

**Why it exists:** consensus should not be declared while serious problems are still on the table. Counting critiques *after* revision (instead of when they are raised) means a round that raises and fixes issues isn't punished. A critical issue needs a real change, not just an argument. Self-reported statuses are checked by the loop itself: if an issue isn't really fixed, the critic raises it again next round.

The final decision's key disagreements leave out critiques the target addressed; rebutted ones stay listed, since they are real, argued disagreements.

---

## Rule 5: Settled

**Question:** Have positions stopped changing, or are the agents about equally sure? (Code name: `confidence_converged`.)

**Passes when** either is true:

- **Positions stopped changing:** drift `< DRIFT_EARLY_STOP_THRESHOLD` (0.05). Drift compares each agent's position with its own position last round: 0 = the same words, 1 = all new words. It is the **average** over agents who spoke in both rounds (formally: 1 − word overlap).
- **Agents are about equally sure:** confidence spread (highest − lowest confidence among every agent that spoke this round, abstainers included) `<= CONFIDENCE_CONVERGENCE_SPREAD` (0.15).

In round 1 there is no previous round, so only the spread check can pass. The same goes when no agent from the previous round spoke again (e.g. they all timed out): drift is "not measurable", never "no movement".

(The old "every agent ≥ 0.9" shortcut is disabled by default via `CONVERGENCE_ALLOW_ALL_CONFIDENT=false`. It was redundant with the spread check and suggested that high confidence alone could settle a debate.)

**Why it exists:** avoids declaring consensus while positions or confidence are still moving widely between agents. Low drift is not a stop on its own: all other rules must still pass, and a debate that stalls below the threshold runs to `max_rounds`.

---

## Rule 6: Veto

**Question:** Has no Ethics agent vetoed the proposal?

**How it's measured:** Ethics-class agents (Ethics, FinancialEthics, PatientSafety) can set a structured `veto: bool` with a `veto_reason`. The check counts the vetoes in this round's outputs. A veto forces that agent's stance to `oppose`.

**Passes when:** `active_vetoes == 0`.

**Why it exists:** Rule 3 allows one dissenter, so a lone ethical objection could otherwise be outvoted. The veto is a hard block on the *consensus label*, not on the debate: the debate continues, the agent can lift the veto in a revision, and if rounds run out the result is `max_rounds_reached` with the veto recorded in `FinalDecision.vetoes` for the human to decide.

---

## Summary: thresholds and loopholes

| # | Rule | Passes when | Loophole it closes |
|---|---|---|---|
| 1 | Agreement | agreement score (Vote by default) ≥ mode threshold | Confident agents with opposite verdicts look like agreement |
| 2 | Min rounds | rounds ≥ `min_rounds` | Stopping on overconfident first answers |
| 3 | Dissent | ≤ 1 agent votes against the majority | A strong-looking majority that overrides several agents |
| 4 | Open objections | ≤ 2 high/critical critiques unresolved after revision | Declaring consensus with serious problems on the table |
| 5 | Settled | drift < 0.05 OR confidence spread ≤ 0.15 | Stopping while positions or confidence are still moving |
| 6 | Veto | no standing Ethics-class veto | Outvoting a lone ethical objection |

No two rules measure the same thing: Rules 1 and 3 both use stances but ask different questions (strength of the majority vs number overruled), and Rule 6 is a hard block that Rule 3's tolerance of one dissenter would otherwise miss.

## Where to see it

- **In the UI:** a stance chip on each agent card, "78% agreement · 2/3 vote" in each round header, a muted "Open: Risk → Strategy" line while objections are open, and the minority report, key disagreements and standing vetoes in the decision panel.
- `synthesis` SSE event, every round: `agreement_score`, `agreement_method_used`, every candidate score (`stance_agreement_score`, `confidence_agreement_score`, `position_agreement_score`, `semantic_agreement_score`), `stance_tally`, `leading_proposal`, `dissenting_agents` (names) and `open_disagreements` (`[{critic, target, severity, status}]`).
- `convergence_gate` log line: every signal, the threshold, `consensus` and `should_continue`.
- The debate trace: each revised agent output keeps its `stance` and `critique_replies`. The final decision records `agreement_method`, `stance_tally`, `minority_report`, `key_disagreements` and `vetoes`.

## Configuration reference

**Mode presets.** A request that names no mode gets `DEFAULT_DEBATE_MODE` (`quick`). Custom mode is Standard plus your own rounds and threshold.

| Mode | `max_rounds` | `min_rounds` | `consensus_threshold` | Critiques & revisions |
|---|---|---|---|---|
| Quick | 2 | 1 | 0.60 | skipped |
| Standard | 2 | 2 | 0.75 | yes |
| Thorough | 6 | 3 | 0.85 | yes |

A debate can override `max_rounds` (2–6 in the UI, 2–8 via the API), `min_rounds` (clamped to `max_rounds`) and `consensus_threshold` (0.1–0.95).

**Settings** (`backend/app/core/config.py`):

| Setting | Default | Rule |
|---|---|---|
| `AGREEMENT_METHOD` | `stance` | 1 |
| `SEMANTIC_CONSENSUS_ENABLED` | `false` | 1 (semantic score + method) |
| `SEMANTIC_CONSENSUS_WEIGHT` | 0.5 | 1 (semantic method) |
| `SEMANTIC_MODEL` | `all-MiniLM-L6-v2` | 1 (semantic method) |
| `CONSENSUS_POSITION_WEIGHT` | 0.3 | 1 (Text method) |
| `POSITION_OVERLAP_FLOOR` / `POSITION_OVERLAP_CEILING` | 0.08 / 0.19 | 1 (Text method) |
| `MAX_DISSENTERS_FOR_CONSENSUS` | 1 | 3 |
| `MINORITY_REPORT_BAND` | 0.20 | 3 (fallback only) |
| `MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS` | 2 | 4 |
| `AGENT_REVISION_TIMEOUT` | 45 s (× `AGENT_TOOL_TIMEOUT_MULTIPLIER` 1.5 for agents that use tools) | 4 (a timed-out revision has no replies) |
| `DRIFT_EARLY_STOP_THRESHOLD` | 0.05 | 5 |
| `CONFIDENCE_CONVERGENCE_SPREAD` | 0.15 | 5 |
| `CONVERGENCE_ALLOW_ALL_CONFIDENT` | `false` | 5 |
| `ALL_CONFIDENT_THRESHOLD` | 0.9 | 5 (only with the flag above) |

## Known limitations

- Stance, confidence and critique replies are self-reported by the LLM.
- Stances assume a yes/no decision. For choice or open-ended questions ("Which market first?"), round-1 stances are weak until the Moderator's `leading_proposal` exists.
- The Semantic method shares the embedding blind spot: opposite verdicts on one topic still score as similar.
- Thresholds are round numbers, not yet calibrated against labelled debates.
- Drift uses word overlap, so heavy rephrasing reads as movement.

## Worked example (Standard mode)

Question: "Should we expand into Southeast Asia next year?" Panel: Analyst, Risk, Strategy, Ethics. Standard mode: threshold 0.75, `min_rounds` 2, `max_rounds` 2.

| | Round 1 | Round 2 |
|---|---|---|
| Votes (confidence) | Strategy support 0.85, Ethics support 0.80, Risk oppose 0.80, Analyst abstain 0.75 | Toward the `leading_proposal` "Pilot in one market first": Strategy support 0.85, Ethics support 0.80, Risk support 0.75, Analyst abstain 0.80 |
| 1. Agreement | 1.65 / 2.45 = 0.67 ❌ | 2.40 / 2.40 = 1.00 ✅ |
| 2. Min rounds | 1 < 2 ❌ | 2 ✅ |
| 3. Dissent | 1 (Risk) ✅ | 0 ✅ |
| 4. Open objections | 1: Risk's critical critique of Strategy was only rebutted ✅ | 0: Risk raised it again and Strategy addressed it ✅ |
| 5. Settled | spread 0.85 − 0.75 = 0.10 ✅ | spread 0.85 − 0.75 = 0.10 ✅ |
| 6. Veto | none ✅ | none ✅ |
| Result | 2 checks failed: run another round | all six pass: `consensus_reached` |

Round 2 is also Standard's last round, so the debate would end either way; the gate decides the label. Had any rule failed, it would end as `max_rounds_reached`.
