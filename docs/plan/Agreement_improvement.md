# Agreement Improvement Plan

> **Branch:** `feature/AgentBoard_Improvement_01Oct` (or a new branch from it)
> **Scope:** Rule 1 of the consensus gate (the agreement score) + the `SEMANTIC_CONSENSUS_ENABLED` path.
> **Out of scope:** Rules 2–6 (min rounds, dissent, open disagreements, confidence converged, veto). Do not change their logic in this plan.

---

## 0. Background (why this change)

**What the code does today** (`orchestrator/nodes.py` → convergence node, `services/consensus.py`):

```
mean_conf   = mean(agent.confidence_score)
raw_overlap = confidence-weighted pairwise Jaccard of positions
overlap     = clip((raw_overlap - 0.08) / (0.19 - 0.08), 0, 1)
agreement   = 0.7 * mean_conf + 0.3 * overlap                    # default
agreement   = 0.5 * mean_conf + 0.5 * cosine                     # if SEMANTIC_CONSENSUS_ENABLED
```

**Problems found**

| # | Problem | Evidence |
|---|---|---|
| P1 | Word overlap can't see "not" | "should expand" vs "should not expand": raw 0.94 → rescaled 1.0 |
| P2 | Rescale window (0.08–0.19) saturates | Same-topic debates hit 1.0, so agreement ≈ `0.7 × conf + 0.3` → threshold is really a confidence threshold |
| P3 | A 2-vs-2 split passes Thorough | conf 0.80, overlap 1.0 → agreement 0.86 ≥ 0.85 |
| P4 | Embeddings have the same blind spot | MiniLM encodes topic, not verdict; opposite verdicts on one topic still score high cosine |
| P5 | Semantic mode silently replaces the formula | Weight jumps from 0.3 to 0.5, no rescale, thresholds never calibrated for it |
| P6 | `model.encode()` blocks the event loop | Sync call inside an async node, pauses SSE |

**Root cause:** text similarity (words or embeddings) measures **topic**. Agents are role-constrained, so their text differs even when they agree, and matches even when they don't. We need to measure **verdict**.

---

## Part A: Fix `SEMANTIC_CONSENSUS_ENABLED` (do this first)

**Goal:** semantic similarity stops overriding the agreement score. It becomes a **diagnostic** by default and an **optional, explicit** agreement method.

### A1. New meaning of the flag

| Setting | Before | After |
|---|---|---|
| `SEMANTIC_CONSENSUS_ENABLED=false` | Word-overlap blend | No change in behavior (embedder not loaded for consensus) |
| `SEMANTIC_CONSENSUS_ENABLED=true` | **Overrides** agreement with `0.5×conf + 0.5×cosine` | Computes cosine every round, **logs + emits it only**. Also makes the `semantic` agreement method available (see Part B) |

Keep the flag name unchanged (backward compatible with existing `.env` files).

### A2. Make encoding non-blocking

In the convergence node, replace the direct call with:

```python
semantic_agreement = await asyncio.to_thread(
    _semantic_engine.compute_semantic_similarity, round_data.agent_outputs
)
```

### A3. Separate "compute" from "use"

In `nodes.py`, the semantic block must:
1. Compute `semantic_agreement` (when the engine exists and ≥ 2 outputs).
2. **Not** assign to `agreement_score` unless `agreement_method == "semantic"` (Part B).
3. Keep the existing try/except fallback; on failure, `semantic_agreement = None`.

### A4. Expose availability

`SemanticConsensusEngine` raises `ImportError` when `sentence-transformers` is missing. Add a small helper:

```python
def semantic_available() -> bool:
    return settings.SEMANTIC_CONSENSUS_ENABLED and _SEMANTIC_AVAILABLE
```

Return it to the frontend via the existing modes endpoint (`DebateModesResponse`), so the UI can disable the Semantic option (Part C).

### A5. Note the 256-token limit

MiniLM truncates input at 256 tokens. Add a code comment in `compute_semantic_similarity` and a line in docs. No code change needed.

### A6. Tests (Part A)

- Semantic enabled + `agreement_method="stance"` → `agreement_score` does **not** equal the cosine hybrid; `semantic_agreement_score` is still emitted.
- Semantic engine raises → debate continues, `semantic_agreement_score` is `None`.
- `semantic_available()` is `False` when the flag is off or the library is missing.

---

## Part B: New Approach, Stance-Based Agreement

### B1. Idea

Each agent declares its verdict as a structured field. Agreement = **confidence-weighted vote share of the largest stance group**. This follows the same pattern as the existing structured Ethics `veto`.

### B2. Schema changes

**`agents/base_agent.py` → `AgentLLMOutput`** (what the LLM fills):

```python
stance: Literal["support", "oppose", "conditional", "abstain"] = Field(
    description=(
        "Your verdict on the proposal on the table: support, oppose, or "
        "conditional (support only if specific conditions are met). "
        "Use abstain only if your role does not make recommendations."
    ),
)
```

Required in the LLM schema, so structured output always fills it (existing `with_retry` handles parse failures).

**`schemas/agent_response.py` → `AgentResponse`** (stored + API):

```python
stance: Literal["support", "oppose", "conditional", "abstain"] | None = Field(
    default=None,
    description="Agent's verdict on the proposal on the table. None for debates stored before this field existed.",
)
```

Optional here so old `state_json` rows still load.

**`BaseAgent._to_response`**: map `stance=getattr(raw, "stance", None)`.

**Veto consistency rule:** if `veto is True` and stance is `support` or `conditional`, coerce stance to `oppose` and log `stance_coerced_by_veto`.

### B3. What the stance is *about* (the anchor)

- **Round 1:** stance toward the decision implied by the user's question ("Should we expand into SE Asia?" → support = yes).
- **Round 2+:** stance toward the Moderator's `leading_proposal` from the previous round.

**`agents/moderator_agent.py` → `ModeratorSynthesis`**, add:

```python
leading_proposal: str | None = Field(
    default=None,
    description="One sentence: the recommendation most agents are converging on. Agents give their stance toward this next round.",
)
```

Store it on the round (`DebateRound`, `schemas/state.py`, optional field). Inject it into the next round's proposal/revision prompts as:

```
Proposal on the table: <leading_proposal>
Set `stance` toward this proposal.
```

If `leading_proposal` is missing, fall back to the round-1 anchor.

### B4. Prompt changes

- **Shared output instructions (BaseAgent):** one line about `stance` (use the B2 field description).
- **Analyst:** "You do not make recommendations: set stance to `abstain`." (matches its existing role constraint)
- **Ethics-class agents:** "If you set veto=true, your stance must be `oppose`."
- **Risk / Strategy:** no extra text needed.

### B5. Agreement function

**`services/consensus.py`**:

```python
from collections import defaultdict

def compute_stance_agreement(responses: list[AgentResponse]) -> float | None:
    """Confidence-weighted vote share of the largest stance group.

    Abstainers and agents with no stance are excluded.
    Returns None when fewer than 2 agents voted, so the caller can fall back.
    """
    voters = [r for r in responses if r.stance and r.stance != "abstain"]
    if len(voters) < 2:
        return None
    weight: dict[str, float] = defaultdict(float)
    for r in voters:
        weight[r.stance] += r.confidence_score
    total = sum(weight.values())
    return max(weight.values()) / total if total else 0.0


def stance_tally(responses: list[AgentResponse]) -> dict[str, int]:
    """Counts per stance, for logs/UI (e.g. {'support': 2, 'oppose': 1, 'abstain': 1})."""
```

`conditional` is its own group (conservative: "yes, if X" is not counted as plain "yes").

### B6. Agreement method selection

**`core/config.py`**:

```python
AGREEMENT_METHOD: Literal["stance", "lexical", "semantic"] = "stance"
```

| Method | Formula | Use |
|---|---|---|
| `stance` (**default**) | `compute_stance_agreement` | Main method |
| `lexical` | Current blend `0.7×conf + 0.3×rescaled overlap` | Legacy + fallback |
| `semantic` | `0.5×conf + 0.5×cosine` | Experiment only; requires `semantic_available()` |

**Per-debate override:** add `agreement_method: Literal["stance","lexical","semantic"] | None = None` to `DebateStartRequest` (and `SimulateRequest`), store it on `DebateState`, resolve `request → settings.AGREEMENT_METHOD`. If `semantic` is requested but unavailable → 422 with a clear message.

**Resolution in the convergence node:**

```python
method = ds.agreement_method or settings.AGREEMENT_METHOD
agreement_score, method_used = None, method

if method == "stance":
    agreement_score = compute_stance_agreement(round_data.agent_outputs)
elif method == "semantic" and semantic_agreement is not None:
    agreement_score = 0.5 * confidence_agreement + 0.5 * semantic_agreement

if agreement_score is None:                       # fallback (missing stances, semantic failure, < 2 voters)
    agreement_score = lexical_blend               # existing formula, unchanged
    method_used = "lexical"
    if method != "lexical":
        logger.warning("agreement_fallback_to_lexical", extra={"requested": method})
```

Always compute and emit all available scores (confidence, lexical, semantic, stance), regardless of which one drives the gate.

### B7. Events + persistence

**`synthesis` SSE event**, add:
- `stance_agreement_score: float | None`
- `stance_tally: dict[str, int]`
- `agreement_method_used: str`

**Agent output events** (proposal/revision): include `stance`.

**`FinalDecision`** (optional, small): `agreement_method: str | None`, `stance_tally: dict[str, int] | None`.

Frontend types (`frontend/src/lib/types.ts`): add the new optional fields.

### B8. Thresholds: keep the numbers, document the meaning

Keep 0.60 / 0.75 / 0.85. With the default panel (Analyst abstains → **3 voters**: Risk, Strategy, Ethics):

| Vote (similar confidence) | Score | Quick 0.60 | Standard 0.75 | Thorough 0.85 |
|---|---|---|---|---|
| 3 of 3 | 1.00 | ✅ | ✅ | ✅ |
| 2 of 3, dissenter unsure (0.85, 0.85 vs 0.40) | 0.81 | ✅ | ✅ | ❌ |
| 2 of 3, dissenter confident | ~0.67 | ✅ | ❌ | ❌ |
| 2 vs 2 (4 voters) | ~0.50 | ❌ | ❌ | ❌ |

Domain packs change the voter count; the formula adapts automatically. Calibrating thresholds against real debates is a follow-up, not part of this plan.

### B9. Tests (Part B), in `backend/tests/test_consensus.py` + node tests

| Test | Expected |
|---|---|
| 2 support (0.85, 0.80) vs 2 oppose (0.80, 0.75) | 1.65 / 3.20 ≈ **0.52** |
| 4 support | **1.0** |
| 3 support (0.9) vs 1 oppose (0.9) | **0.75** |
| 3 support (0.9) vs 1 oppose (0.4) | ≈ **0.87** |
| All abstain / one voter | `None` → node falls back to lexical, `agreement_method_used == "lexical"` |
| `conditional` + `support` | separate groups |
| veto=true with stance=support | coerced to `oppose` |
| Old stored debate (no `stance` key) loads | `stance is None`, no error |
| `agreement_method="semantic"` with semantic unavailable | 422 |
| Gate (Rules 2–6) unchanged | existing tests pass without edits |

### B10. Acceptance criteria

- [ ] Default run uses `stance`; a 2-vs-2 split never reaches consensus.
- [ ] `SEMANTIC_CONSENSUS_ENABLED=true` no longer changes the gate unless `agreement_method="semantic"`.
- [ ] No blocking `encode()` in async code.
- [ ] Synthesis event shows all scores + `agreement_method_used`.
- [ ] Old debates in SQLite still load and render.
- [ ] All existing backend + frontend tests pass.

---

## Part C: UI (minimal, no heavy text)

### C1. Start form (`frontend/src/components/DebateInput.tsx`)

Add **one compact row** inside the existing "Intelligence options" box:

```
Agreement   [ Vote ] [ Text ] [ Semantic ]
```

- Segmented control, 3 short labels, **no description text**.
- Explanations live in `title` tooltips only:
  - Vote: "Agents vote support / oppose. Recommended."
  - Text: "Legacy: confidence + word overlap."
  - Semantic: "Confidence + embedding similarity (experimental)."
- `Semantic` is disabled when the modes endpoint reports it unavailable (tooltip: "Enable SEMANTIC_CONSENSUS_ENABLED on the server").
- Default selection = server default (`AGREEMENT_METHOD`), same pattern as debate mode.
- Sends `agreement_method` in the start request.

### C2. Debate view (optional, tiny)

- Agent card: small stance chip next to the confidence value: `✓` support · `✗` oppose · `~` conditional · `–` abstain (with `title` tooltip).
- Synthesis bar: keep "78% agreement"; append a muted `· 2/3 vote` when method is `stance`.

No new panels, no new pages.

---

## Defaults (final)

| Setting | Default | Notes |
|---|---|---|
| `AGREEMENT_METHOD` | **`stance`** | Drives the gate |
| `SEMANTIC_CONSENSUS_ENABLED` | **`false`** | When true: diagnostic score + enables the `semantic` option |
| Lexical blend | — | Automatic fallback + selectable "Text" option |
| UI selector | Vote | Mirrors server default |

---

## Implementation order (one commit each)

1. **A2 + A3 + A4:** semantic non-blocking, observe-only, availability helper (+ A6 tests).
2. **B2 + B4:** `stance` field in schemas and prompts, veto coercion.
3. **B5 + B6:** `compute_stance_agreement`, `AGREEMENT_METHOD`, request/state plumbing, fallback.
4. **B3:** `leading_proposal` on `ModeratorSynthesis` + `DebateRound`, prompt injection.
5. **B7:** events, `FinalDecision`, frontend types.
6. **B9:** remaining tests.
7. **C1 (+ C2 optional):** UI.
8. **Docs** (below).

---

## Docs to update after implementation

- `04-ml-algorithms-logic.md` §3–4: stance as Rule 1; semantic as diagnostic/optional.
- `07-evaluation-metrics.md`: "Displayed score" and V2 sections.
- `06-challenges-edge-cases.md`: False Consensus mitigation.
- `00-SUMMARY-INTERVIEW-NOTES.md`, `agent_board_storyline.md`, `agentboard_interview_qa.md`: replace "embeddings detect opposite positions" with the V1 → V2 → stance story.
- `consensus.py` header comment: "six signals"; describe stance.

---

## Do NOT

- Change Rules 2–6 logic (dissent and open-disagreement redesign is a separate plan).
- Rename `SEMANTIC_CONSENSUS_ENABLED`.
- Make `stance` required on `AgentResponse` (breaks stored debates).
- Remove the lexical blend (it is the fallback).
- Add long explanatory text to the UI.
