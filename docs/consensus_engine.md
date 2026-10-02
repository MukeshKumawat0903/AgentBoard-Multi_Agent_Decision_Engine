# Consensus Engine

The consensus engine decides when a debate may stop with a **consensus** label.
It is plain, deterministic Python (no LLM). The Moderator's own
`should_continue` opinion is logged for comparison but never used.

Every round, after revisions (Quick mode skips critiques and revisions), the
convergence node computes six signals. A debate reaches consensus only when
**all six pass**:

```python
consensus = (
    active_vetoes == 0                                  # Rule 6
    and agreement >= consensus_threshold                # Rule 1
    and rounds_completed >= min_rounds                  # Rule 2
    and dissenting_agents <= MAX_DISSENTERS             # Rule 3 (1)
    and open_disagreements <= MAX_OPEN_DISAGREEMENTS    # Rule 4 (2)
    and confidence_converged                            # Rule 5
)
if consensus:            termination_reason = "consensus_reached"
elif round >= max_rounds: termination_reason = "max_rounds_reached"
else:                    run another round
```

`max_rounds` guarantees termination. A debate that runs out of rounds is
reported honestly as `max_rounds_reached`, never as consensus.

Code: `backend/app/services/consensus.py` (signals and predicate) and
`convergence_node` in `backend/app/orchestrator/nodes.py` (wiring).

---

## Rule 1: Agreement

**Question:** How strong is the majority?

**How it's measured (default `AGREEMENT_METHOD=stance`):** every agent outputs
a structured `stance`: `support`, `oppose`, `conditional`, or `abstain`
(roles that don't recommend, like the Analyst, abstain). Agreement is the
confidence-weighted vote share of the largest stance group:

```
agreement = (sum of confidence in the largest stance group) / (sum of confidence of all voters)
```

Round 1 stances refer to the decision implied by the question; later rounds
refer to the Moderator's `leading_proposal`.

**Passes when:** `agreement >= consensus_threshold` (Quick 0.60, Standard 0.75, Thorough 0.85).

**Why it exists:** the original gate used mean confidence, so two agents 0.9
sure of *opposite* answers looked like 0.9 agreement. Text similarity (word
overlap or embeddings) doesn't fix this: it measures topic, not verdict, so
"should expand" and "should not expand" look nearly identical. Asking for the
verdict directly does.

**Alternatives:** `lexical` (0.7 × confidence + 0.3 × rescaled word overlap,
the legacy formula and automatic fallback when fewer than two agents vote) and
`semantic` (0.5 × confidence + 0.5 × embedding cosine, experimental, needs
`SEMANTIC_CONSENSUS_ENABLED`). All available scores are always logged for
comparison.

---

## Rule 2: Minimum Rounds

**Question:** Did we debate long enough?

**How it's measured:** `rounds_completed >= min_rounds` (Quick 1, Standard 2, Thorough 3; clamped to `max_rounds`).

**Why it exists:** LLMs are overconfident on first answers. Without a floor, a
multi-round debate could stop after round 1, before any cross-examination
has had an effect.

**Note:** Standard has `min_rounds = max_rounds = 2`, so in Standard this rule
decides the *label* (consensus vs max rounds), not when the debate stops.

---

## Rule 3: Dissent

**Question:** How many agents are being overruled?

**How it's measured:** a dissenter is a voting agent whose stance differs from
the majority stance. The majority is the stance group with the largest summed
confidence (the same weighting as Rule 1); ties go to the larger group, then
`oppose` > `conditional` > `support`, so the answer never depends on agent
order. Abstainers never dissent. (Fallback when fewer than two agents voted,
e.g. debates stored before stances: agents more than `MINORITY_REPORT_BAND`
(0.20) below mean confidence.)

**Passes when:** `dissenting_agents <= MAX_DISSENTERS_FOR_CONSENSUS` (1).

**Why it exists:** Rule 1 measures how strong the majority is; it can look
strong while several agents are overruled. Example: 2 supporters at 0.9 and 2
unsure others with different stances score 0.82 on Rule 1 but have 2
dissenters. Rule 3 caps how many voices can be overridden. A confident
opponent counts; an unsure ally doesn't.

The same function produces the final decision's **minority report**, so the
gate and the report always name the same agents ("Voted oppose while the
majority voted support.").

---

## Rule 4: Open Objections

**Question:** Are serious critiques still unanswered?

**How it's measured:** each round runs critiques → revisions → gate. In its
revision, each agent replies to every critique it received with
`addressed`, `rebutted`, or `unaddressed` (`critique_replies`). An objection
is open when a `high`/`critical` critique is `unaddressed` (or has no reply,
e.g. the revision timed out), or when a `critical` critique was only
`rebutted`. Counted per critic→target pair.

| Reply | `high` | `critical` |
|---|---|---|
| `addressed` | closed | closed |
| `rebutted` | closed | **open** |
| `unaddressed` / no reply | open | open |

**Passes when:** `open_disagreements <= MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS` (2).

**Why it exists:** consensus should not be declared while serious problems are
still on the table. Counting critiques *after* revision (instead of when they
are raised) means a round that raises and fixes issues isn't punished. A
critical issue needs a real change, not just an argument. Self-reported
statuses are checked by the loop itself: if an issue isn't really fixed, the
critic raises it again next round.

The final decision's key disagreements leave out critiques the target
addressed; rebutted ones stay listed, since they are real, argued
disagreements.

---

## Rule 5: Confidence Converged

**Question:** Are we still making progress?

**How it's measured:** passes if either
- positions stopped changing: position drift `< DRIFT_EARLY_STOP_THRESHOLD` (0.05), where drift = 1 − word overlap of each agent's position vs its previous round, or
- agents are about equally sure: confidence spread (max − min) `<= CONFIDENCE_CONVERGENCE_SPREAD` (0.15).

(The old "every agent ≥ 0.9" shortcut is disabled by default via
`CONVERGENCE_ALLOW_ALL_CONFIDENT=false`. It was redundant with the spread
check and suggested that high confidence alone could settle a debate.)

**Why it exists:** stops wasting rounds once the debate has plateaued, and
avoids declaring consensus while confidence is still moving widely between
agents. Drift is not a standalone stop: all other rules must still pass.

---

## Rule 6: No Standing Veto

**Question:** Is an ethical red line crossed?

**How it's measured:** Ethics-class agents (Ethics, FinancialEthics,
PatientSafety) output a structured `veto: bool` and `veto_reason`. Count of
vetoes in the current round's outputs. A veto forces that agent's stance to
`oppose`.

**Passes when:** `active_vetoes == 0`.

**Why it exists:** Rule 3 allows one dissenter, so a lone ethical objection
could otherwise be outvoted. The veto is a hard block on the *consensus
label*, not on the debate: the debate continues, the agent can lift the veto
in a revision, and if rounds run out the result is `max_rounds_reached` with
the veto recorded in `FinalDecision.vetoes` for the human to decide.

---

## Summary

| Rule | Question it answers |
|---|---|
| 1. Agreement | How strong is the majority? |
| 2. Min rounds | Did we debate long enough? |
| 3. Dissent | How many agents are overruled? |
| 4. Open objections | Are serious critiques still unanswered? |
| 5. Settled | Are we still making progress? |
| 6. Veto | Is an ethical red line crossed? |

### At a glance: thresholds and loopholes

| # | Rule | Question it answers | Passes when | Loophole it closes |
|---|---|---|---|---|
| 1 | Agreement | How strong is the majority? | confidence-weighted stance share ≥ threshold | Confident agents with opposite verdicts look like agreement |
| 2 | Min rounds | Did we debate long enough? | rounds ≥ min_rounds | Stopping on overconfident first answers |
| 3 | Dissent | How many agents are overruled? | ≤ 1 agent votes against the majority | A strong-looking majority that overrides several agents |
| 4 | Open objections | Are serious critiques still unanswered? | ≤ 2 high/critical critiques unresolved after revision | Declaring consensus with serious problems on the table |
| 5 | Settled | Are we still making progress? | drift < 0.05 OR confidence spread ≤ 0.15 | Stopping while positions or confidence are still moving |
| 6 | Veto | Is an ethical red line crossed? | no standing Ethics-class veto | Outvoting a lone ethical objection |

No two rules measure the same thing: Rules 1 and 3 both use stances but ask
different questions (strength of the majority vs number overruled), and Rule 6
is a hard block that Rule 3's tolerance of one dissenter would otherwise miss.

## Where to see it

- `synthesis` SSE event, every round: `agreement_score`, every candidate score,
  `stance_tally`, `dissenting_agents` (names) and `open_disagreements`
  (`[{critic, target, severity, status}]`). The round header shows a muted
  "Open: Risk → Strategy" line while objections are open.
- `convergence_gate` log line: every signal, the threshold, `consensus` and
  `should_continue`.

## Configuration reference

| Setting | Default | Rule |
|---|---|---|
| `AGREEMENT_METHOD` | `stance` | 1 |
| `SEMANTIC_CONSENSUS_ENABLED` | `false` | 1 (diagnostic / semantic method) |
| `SEMANTIC_CONSENSUS_WEIGHT` | 0.5 | 1 (semantic method) |
| `CONSENSUS_POSITION_WEIGHT` | 0.3 | 1 (lexical method) |
| `POSITION_OVERLAP_FLOOR` / `CEILING` | 0.08 / 0.19 | 1 (lexical method) |
| mode `consensus_threshold` | 0.60 / 0.75 / 0.85 | 1 |
| mode `min_rounds` | 1 / 2 / 3 | 2 |
| `MAX_DISSENTERS_FOR_CONSENSUS` | 1 | 3 |
| `MINORITY_REPORT_BAND` | 0.20 | 3 (fallback only) |
| `MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS` | 2 | 4 |
| `DRIFT_EARLY_STOP_THRESHOLD` | 0.05 | 5 |
| `CONFIDENCE_CONVERGENCE_SPREAD` | 0.15 | 5 |
| `CONVERGENCE_ALLOW_ALL_CONFIDENT` | `false` | 5 |
| `ALL_CONFIDENT_THRESHOLD` | 0.9 | 5 (only with the flag above) |

## Known limitations

- Stance, confidence, and critique replies are self-reported by the LLM.
- Thresholds are round numbers, not yet calibrated against labelled debates.
- Drift uses word overlap, so heavy rephrasing reads as movement.
