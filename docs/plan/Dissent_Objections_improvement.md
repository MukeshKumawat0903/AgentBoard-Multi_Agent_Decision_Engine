# Dissent & Open Objections Improvement Plan

> **Branch:** `feature/AgentBoard_Improvement_01Oct` (or a new branch from it)
> **Depends on:** `Agreement_improvement.md` must be implemented first (this plan uses the `stance` field and its helpers).
> **Scope:** Rule 3 (Dissent), Rule 4 (Open disagreements), a small Rule 5 tweak, and a new reference doc `docs/consensus_engine.md`.
> **Out of scope:** Rule 1 (done in the Agreement plan), Rule 2 (min rounds), Rule 6 (veto). Do not change their logic.

---

## 0. Background (why this change)

### Rule 3: Dissent, today
`services/consensus.py → select_dissenting_agents`:
```python
mean_conf = mean(confidence)
dissenters = [r for r in responses if r.confidence_score < mean_conf - MINORITY_REPORT_BAND]  # 0.20
```

| Problem | Example |
|---|---|
| A **confident opponent** is never a dissenter | Risk opposes at 0.90 → not counted |
| An **unsure ally** is counted as a dissenter | Ethics supports at 0.50 → counted |
| Duplicates Rule 5 | If Rule 5 passes via spread ≤ 0.15 or all ≥ 0.9, nobody can be 0.20 below the mean, so Rule 3 can only fail when Rule 5 passes via drift alone |

### Rule 4: Open disagreements, today
`count_open_disagreements` counts distinct critic→target pairs with severity `high`/`critical` in `round_data.critiques`. (Bullet-point inflation is already fixed.)

| Problem | Example |
|---|---|
| Counts critiques **raised**, not **still open** | Each round runs critiques → revisions → gate. 3 serious critiques that are all fixed in revisions still block consensus |
| No link between a critique and its revision | The revising agent never reports what it did with each critique |

### Rule 5: Confidence converged, today
Passes when `drift < 0.05` OR `spread ≤ 0.15` OR `all ≥ ALL_CONFIDENT_THRESHOLD (0.9)`.

| Problem | Example |
|---|---|
| The "all ≥ 0.9" path is redundant and reads as "overconfidence passes" | If all agents are ≥ 0.90, spread ≤ 0.10, so the spread branch already passes. It is dead code, but it signals the wrong intent to readers |

---

## Part A: Rule 3, Stance-Based Dissent

### A1. New definition
**Dissenter = a voting agent whose stance differs from the majority stance.**
- Voters = agents with `stance` set and not `abstain`.
- Majority = stance group with the largest summed confidence (same weighting as `compute_stance_agreement`).
- Abstainers are never dissenters.

### A2. Shared helper (avoid duplicate logic with Rule 1)
In `services/consensus.py`, extract one helper used by both `compute_stance_agreement` and dissent:

```python
_STANCE_TIE_ORDER = ("oppose", "conditional", "support")  # deterministic tie-break

def stance_weights(responses: list[AgentResponse]) -> tuple[list[AgentResponse], dict[str, float]]:
    """Return (voters, summed confidence per stance)."""
    voters = [r for r in responses if r.stance and r.stance != "abstain"]
    weights: dict[str, float] = defaultdict(float)
    for r in voters:
        weights[r.stance] += r.confidence_score
    return voters, weights


def majority_stance(weights: dict[str, float], voters: list[AgentResponse]) -> str:
    """Largest summed confidence; ties broken by head count, then _STANCE_TIE_ORDER."""
```

Tie-break rationale: a tie must resolve deterministically so the gate and the final report agree. In a true tie (e.g. 2 vs 2, equal weight), the other group becomes dissenters, so Rule 3 fails as well as Rule 1. That is consistent.

### A3. New `select_dissenting_agents`
Keep the same function name and signature (it is shared with `finalize_node`'s minority report):

```python
def select_dissenting_agents(responses: list[AgentResponse], band: float) -> list[AgentResponse]:
    voters, weights = stance_weights(responses)
    if len(voters) < 2:
        return _confidence_gap_dissenters(responses, band)   # old rule, renamed, as fallback
    majority = majority_stance(weights, voters)
    return [r for r in voters if r.stance != majority]
```

- Rename the current body to `_confidence_gap_dissenters` (private fallback for old debates / missing stances).
- `count_dissenting_agents` stays unchanged (it calls `select_dissenting_agents`).
- `MAX_DISSENTERS_FOR_CONSENSUS = 1` stays.

### A4. Minority report text (`orchestrator/nodes.py → finalize_node`, ~L750–770)
The `dissent_reason` is currently built as "X below the group mean". Update it:
- Stance path: `"Voted {stance} while the majority voted {majority}."`
- Fallback path: keep the existing confidence-gap wording.

### A5. Tests (Part A)

| Test | Expected |
|---|---|
| Strategy support 0.85, Risk **oppose 0.90**, Ethics support 0.50 | Dissenters = **[Risk]** (old rule returned [Ethics]) |
| 4 voters all support, confidences 0.9 / 0.9 / 0.9 / 0.5 | **No** dissenters |
| Analyst abstain + 3 support | No dissenters; Analyst never listed |
| 2 support (0.9, 0.9) vs 1 oppose (0.2) + 1 conditional (0.2) | 2 dissenters → Rule 3 fails (Rule 1 share = 0.82 would pass) |
| Exact tie 2 vs 2 equal weight | Deterministic result across repeated calls |
| < 2 voters (old debate, no stance) | Falls back to confidence-gap rule |
| Minority report wording | Stance wording when stances exist |

---

## Part B: Rule 4, Open Objections After Revision

### B1. New definition
**Open objection = a `high`/`critical` critique this round that the target agent did not resolve in its revision.**

The revising agent replies to each critique it received:

| Status | Meaning | Open if `high` | Open if `critical` |
|---|---|---|---|
| `addressed` | Changed the position because of it | No | No |
| `rebutted` | Disagrees, gives a reason | No | **Yes** |
| `unaddressed` | Did not deal with it | Yes | Yes |
| *(no reply)* | Revision missing, failed, or timed out | Yes | Yes |

Why a rebuttal can't close a `critical` critique: otherwise an agent could rebut everything to pass the gate. Critical issues need a real change.

### B2. Schema changes

**`schemas/agent_response.py`**, new model + field:
```python
class CritiqueReply(BaseModel):
    critic_agent: str = Field(description="Name of the agent whose critique this answers.")
    status: Literal["addressed", "rebutted", "unaddressed"] = Field(
        description="addressed = position changed; rebutted = critique is wrong, reason in note; unaddressed = not handled.",
    )
    note: str = Field(default="", description="One line: what changed, or why the critique is wrong.")

class AgentResponse(BaseModel):
    ...
    critique_replies: list[CritiqueReply] = Field(
        default_factory=list,
        description="Revisions only: how each received critique was handled. Empty for proposals and old debates.",
    )
```

**`agents/base_agent.py → AgentLLMOutput`**: add the same `critique_replies` field with `default_factory=list` (proposals leave it empty; one schema keeps Ethics' `EthicsLLMOutput` subclass working unchanged).

**`BaseAgent._to_response`**: map `critique_replies`, then sanitize:
- Drop replies whose `critic_agent` is not among the critiques this agent received.
- If a critic appears twice, keep the last.

Sanitizing needs the received critiques, so pass them in: `revise()` already has `critiques`; add an optional `received_critiques` argument to `_to_response` (default `None` = no filtering, used by proposals).

### B3. Prompt changes (revision templates)
Revision prompts already list critiques via `_format_critiques`. Make sure each item shows the critic's name and severity, then add one instruction to every revision template (`analyst_agent.py`, `risk_agent.py`, `strategy_agent.py`, `ethics_agent.py`, and domain-pack agents that override `_build_revision_prompt`):

> "For each critique above, add one entry to `critique_replies` with the critic's name and a status: `addressed` (you changed your position), `rebutted` (it's wrong, say why in one line), or `unaddressed`. A `critical` critique needs a real change, not only a rebuttal."

Ideally put the sentence in one shared constant in `base_agent.py` and append it in each template, so the wording lives in one place.

### B4. New counting
**`services/consensus.py`**:
```python
def build_reply_index(outputs: list[AgentResponse]) -> dict[str, dict[str, str]]:
    """{target_agent: {critic_agent: status}} from this round's revised outputs."""

def count_open_disagreements(
    critiques: list[CritiqueResponse],
    replies: dict[str, dict[str, str]] | None = None,
    severities: frozenset[str] = HIGH_SEVERITIES,
) -> int:
    """High/critical critic→target pairs not resolved by the target's revision.

    replies=None keeps the old behaviour (count every high/critical critique),
    so existing callers and tests work unchanged.
    """
    open_pairs: set[tuple[str, str]] = set()
    for c in critiques:
        if c.severity not in severities:
            continue
        if replies is None:
            open_pairs.add((c.critic_agent, c.target_agent))
            continue
        status = replies.get(c.target_agent, {}).get(c.critic_agent, "unaddressed")
        if status == "unaddressed" or (status == "rebutted" and c.severity == "critical"):
            open_pairs.add((c.critic_agent, c.target_agent))
    return len(open_pairs)
```

Also add `select_open_disagreements(...)` returning the pairs (for logs and the final decision).

**Convergence node** (`orchestrator/nodes.py`, ~L540):
```python
replies = build_reply_index(round_data.agent_outputs)   # revisions replaced proposals in place
open_disagreements = count_open_disagreements(round_data.critiques, replies)
```

`MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS = 2` stays.

### B5. Why self-reporting is acceptable
The loop self-corrects: next round the critic sees the revised position and re-raises the critique if it isn't really fixed. A false `addressed` buys one round at most, and `min_rounds ≥ 2` (Standard/Thorough) means it can't slip through on round 1.

### B6. Finalize
`finalize_node` builds the structured disagreements from `ds.rounds[-1].critiques` (~L777). Keep it, but skip critiques whose reply is `addressed` so the final decision doesn't list already-fixed issues as disagreements. Rebutted critiques stay listed (they're real, argued disagreements).

### B7. Tests (Part B)

| Test | Expected |
|---|---|
| 3 high critiques, all replied `addressed` | open = **0** |
| 1 high `rebutted` | open = **0** |
| 1 critical `rebutted` | open = **1** |
| 1 high, target revision timed out (no reply) | open = **1** |
| Reply names a critic that never critiqued | ignored |
| Same critic replied twice | last reply wins |
| `replies=None` | old behaviour; existing tests pass unchanged |
| Quick mode (no critiques) | open = 0 |
| Old stored debate (no `critique_replies` key) | loads, empty list |
| Final decision | `addressed` critiques not listed as disagreements |

---

## Part C: Rule 5 Tweak, Drop the Overconfidence Shortcut

### C1. Change
In the convergence node (~L533):
```python
confidence_converged = bool(_confidences) and (
    (drift is not None and drift < settings.DRIFT_EARLY_STOP_THRESHOLD)
    or (max(_confidences) - min(_confidences) <= settings.CONFIDENCE_CONVERGENCE_SPREAD)
    or (settings.CONVERGENCE_ALLOW_ALL_CONFIDENT
        and all(s >= settings.ALL_CONFIDENT_THRESHOLD for s in _confidences))
)
```

**`core/config.py`**: add `CONVERGENCE_ALLOW_ALL_CONFIDENT: bool = False`. Keep `ALL_CONFIDENT_THRESHOLD` (tests set it; flag makes the change reversible).

### C2. Tests (Part C)
- All agents 0.95 → still passes (via spread ≤ 0.15).
- Flag off → the `all ≥` branch is never evaluated (mock/inspect).
- Flag on → old behaviour.

> **Note for implementer:** if every agent is ≥ 0.90, the spread is at most 0.10, so the `spread ≤ 0.15` branch already passes. The "all ≥ 0.9" branch is therefore **dead code** with current defaults. Disabling it is a clarity fix, not a behaviour change. It only matters if someone later lowers `ALL_CONFIDENT_THRESHOLD` below 0.85 or tightens the spread; the flag keeps that explicit.

---

## Part D: Events, Logs, UI

### D1. Logs + events
In the convergence node's gate log (~L570) and the `synthesis` SSE event, add:
- `dissenting_agents: list[str]` (names)
- `open_disagreements: list[{critic, target, severity, status}]`

Frontend types (`frontend/src/lib/types.ts`): add both as optional.

### D2. UI (minimal, optional)
- No new controls.
- Minority report wording changes automatically (A4).
- Optional: in the round view, show a muted line under the synthesis bar: `Open: Risk → Strategy` (only when open > 0). No explanatory text.

---

## Implementation Order (one commit each)

1. **A2 + A3 + A4:** stance helpers, new `select_dissenting_agents`, minority wording (+ A5 tests).
2. **B2:** `CritiqueReply`, `critique_replies` on `AgentResponse` and `AgentLLMOutput`, sanitizing in `_to_response`.
3. **B3:** revision prompt instruction (shared constant).
4. **B4 + B6:** reply index, new counting, gate wiring, finalize filter (+ B7 tests).
5. **C1:** Rule 5 flag (+ C2 tests).
6. **D1 (+ D2 optional).**
7. **Part E:** write `docs/consensus_engine.md`.
8. Update the interview docs (list at the end).

## Acceptance Criteria

- [ ] A confident opponent is counted as a dissenter; an unsure ally is not.
- [ ] Gate and minority report always name the same dissenters.
- [ ] Critiques fixed in revision no longer block consensus.
- [ ] `critical` critiques need `addressed`; `rebutted` keeps them open.
- [ ] Missing replies count as open (safe default).
- [ ] `all ≥ 0.9` shortcut off by default via `CONVERGENCE_ALLOW_ALL_CONFIDENT`.
- [ ] Old debates in SQLite still load and render.
- [ ] All existing backend + frontend tests pass (only tests asserting the old dissent definition may be updated, with a comment).

## Do NOT

- Rename `select_dissenting_agents`, `count_open_disagreements`, or change their existing call sites' meaning without the fallback.
- Change Rules 1, 2, 6.
- Make `critique_replies` required (breaks stored debates).
- Add UI text or new panels.

---

## Part E: Create `docs/consensus_engine.md` (final step)

Create a new file `docs/consensus_engine.md` in the repo (the repo has no `docs/` folder yet; create it). It must describe the gate **as it is after both plans are implemented**. Use the content below as the draft; adjust names/numbers only if the implementation differs, and keep it in sync with `config.py`.

````markdown
# Consensus Engine

The consensus engine decides when a debate may stop with a **consensus** label.
It is plain, deterministic Python (no LLM). The Moderator's own
`should_continue` opinion is logged for comparison but never used.

Every round, after revisions, the convergence node computes six signals.
A debate reaches consensus only when **all six pass**:

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
the legacy formula and automatic fallback) and `semantic` (0.5 × confidence +
0.5 × embedding cosine, experimental, needs `SEMANTIC_CONSENSUS_ENABLED`).
All available scores are always logged for comparison.

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
the majority stance. Abstainers never dissent. (Fallback for debates without
stances: agents more than `MINORITY_REPORT_BAND` (0.20) below mean confidence.)

**Passes when:** `dissenting_agents <= MAX_DISSENTERS_FOR_CONSENSUS` (1).

**Why it exists:** Rule 1 measures how strong the majority is; it can look
strong while several agents are overruled. Example: 2 supporters at 0.9 and 2
unsure others with different stances score 0.82 on Rule 1 but have 2
dissenters. Rule 3 caps how many voices can be overridden.

The same function produces the final decision's **minority report**, so the
gate and the report always name the same agents.

---

## Rule 4: Open Objections

**Question:** Are serious critiques still unanswered?

**How it's measured:** each round runs critiques → revisions → gate. In its
revision, each agent replies to every critique it received with
`addressed`, `rebutted`, or `unaddressed`. An objection is open when a
`high`/`critical` critique is `unaddressed` (or has no reply), or when a
`critical` critique was only `rebutted`. Counted per critic→target pair.

**Passes when:** `open_disagreements <= MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS` (2).

**Why it exists:** consensus should not be declared while serious problems are
still on the table. Counting critiques *after* revision (instead of when they
are raised) means a round that raises and fixes issues isn't punished. A
critical issue needs a real change, not just an argument. Self-reported
statuses are checked by the loop itself: if an issue isn't really fixed, the
critic raises it again next round.

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

## Configuration reference

| Setting | Default | Rule |
|---|---|---|
| `AGREEMENT_METHOD` | `stance` | 1 |
| `SEMANTIC_CONSENSUS_ENABLED` | `false` | 1 (diagnostic / semantic method) |
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

## Known limitations

- Stance, confidence, and critique replies are self-reported by the LLM.
- Thresholds are round numbers, not yet calibrated against labelled debates.
- Drift uses word overlap, so heavy rephrasing reads as movement.
````

---

## Interview docs to update afterwards

- `04-ml-algorithms-logic.md` §4: new Rule 3 and Rule 4 definitions; Rule 5 without the shortcut.
- `05-design-decisions-tradeoffs.md` Decision 1: comments in the gate code block.
- `07-evaluation-metrics.md`: "The Hybrid Gate" paragraph.
- `09-end-to-end-walkthrough.md`: gate block comments.
- `00-SUMMARY-INTERVIEW-NOTES.md` §4.5.4: Rules 3–5 descriptions; point to `docs/consensus_engine.md`.
- `consensus.py` header comment: six signals, stance-based dissent, open-after-revision.
