# Consensus Engine & LLM Client

Two core services power the backend: the **ConsensusEngine** (with optional semantic extension) and hybrid gate for measuring agreement and deciding when a debate ends, and the **LangChainProvider** for all LLM calls across providers.

---

## Consensus Engine

**File:** `app/services/consensus.py`

### ConsensusEngine (V1)

Stateless; one instance can be reused across debates.

#### `compute_agreement_score(responses) → float`

Mean `confidence_score` across agents (`0.0` for an empty list). One component of the measured agreement — see the blend below.

#### `compute_confidence_weighted_score(responses) → float`

**Confidence-weighted pairwise position overlap** (Jaccard):

$$
\text{score} = \frac{\sum_{i < j} w_{ij} \cdot \text{sim}_{ij}}{\sum_{i < j} w_{ij}}
\qquad w_{ij} = \tfrac{\text{conf}_i + \text{conf}_j}{2},\;
\text{sim}_{ij} = \text{Jaccard}(\text{words}(p_i), \text{words}(p_j))
$$

`0.0` for fewer than 2 responses. This is the **raw** overlap; it is rescaled before use (next section).

#### `normalize_position_overlap(raw, floor, ceiling) → float`

Agents write in deliberately different roles, so their raw word overlap stays low even when they agree. The value is mapped linearly onto 0–1:

```
normalized = clamp((raw − floor) / (ceiling − floor), 0, 1)
floor   = POSITION_OVERLAP_FLOOR   = 0.08   # overlap of unrelated positions → 0
ceiling = POSITION_OVERLAP_CEILING = 0.19   # one agent restating the same stance → 1
```

The anchors were measured on stored debates. Without the rescaling the blended score could never reach the mode thresholds. The simulation consistency score uses the same anchors.

#### `detect_position_drift(previous, current) → float`

$$
\text{drift} = \frac{1}{|A|} \sum_{a \in A} \big(1 - \text{Jaccard}(\text{prev}_a, \text{curr}_a)\big)
$$

over agents $A$ present in both rounds (`0.0` = identical, `1.0` = completely new). The function returns `0.0` when nothing matches, so the convergence node only calls it when the two rounds **share at least one agent**; otherwise drift is `None` ("not measurable"), which never counts as "stopped moving".

### Jaccard Similarity (Internal)

```python
def _word_overlap(a: str, b: str) -> float:
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    return len(set_a & set_b) / len(set_a | set_b)   # 1.0 for two empty strings
```

Also used by analytics (pairwise agent agreement) and the finalize node (contribution scores).

### SemanticConsensusEngine (V2 — Optional)

**Enabled by:** `SEMANTIC_CONSENSUS_ENABLED=true`

Extends `ConsensusEngine` with sentence-transformer embeddings:

```python
class SemanticConsensusEngine(ConsensusEngine):
    def compute_semantic_similarity(responses) -> float      # mean pairwise cosine similarity
    def compute_agreement_score(responses, semantic_weight=0.5) -> float
        # (1 − w) · confidence_mean + w · cosine_mean; falls back to V1 on error
```

| Setting | Default | Description |
|---|---|---|
| `SEMANTIC_CONSENSUS_ENABLED` | `false` | Compute and emit the cosine score every round (diagnostic) and allow the `semantic` agreement method |
| `SEMANTIC_MODEL` | `all-MiniLM-L6-v2` | sentence-transformer model |
| `SEMANTIC_CONSENSUS_WEIGHT` | `0.5` | `semantic` method only: cosine vs confidence weight |

The model is lazy-loaded and shares the knowledge base's embedder (`get_shared_embedder`), so the weights load once. `compute_semantic_similarity` is synchronous and CPU-bound, so `convergence_node` calls it through `asyncio.to_thread`. MiniLM truncates each position at 256 word-pieces.

`semantic_available(settings=None) → bool` is true only when `SEMANTIC_CONSENSUS_ENABLED` is set **and** sentence-transformers/numpy import (`semantic_libraries_installed()`). `GET /debate-modes` returns it so the UI can grey out the Semantic option, and request validation rejects `agreement_method="semantic"` (422) when it is false.

### Stance-based agreement (default)

```python
def compute_stance_agreement(responses) -> float | None
def stance_tally(responses) -> dict[str, int]          # e.g. {"support": 2, "oppose": 1, "abstain": 1}
def resolve_agreement_method(*candidates) -> AgreementMethod   # first known method, else "stance"
```

Each `AgentResponse` carries `stance ∈ {support, oppose, conditional, abstain}` (optional on stored responses, required in the LLM output schema). `compute_stance_agreement` ignores abstainers and missing stances, returns `None` with fewer than two voters, and otherwise returns the confidence-weighted vote share of the largest group:

$$
\text{agreement} = \frac{\max_s \sum_{a:\,\text{stance}_a = s} \text{conf}_a}{\sum_{a \in \text{voters}} \text{conf}_a}
$$

`conditional` is its own group. In `BaseAgent._to_response`, a `veto=true` output with stance `support` or `conditional` is coerced to `oppose` (`stance_coerced_by_veto` is logged).

### Choosing the agreement score

`convergence_node` computes every candidate and picks one with `resolve_agreement_method(ds.agreement_method, AGREEMENT_METHOD)`:

```
position_agreement = normalize_position_overlap(confidence_weighted_overlap, 0.08, 0.19)
lexical            = (1 − w)·mean_confidence + w·position_agreement     # w = CONSENSUS_POSITION_WEIGHT (0.3)
stance             = compute_stance_agreement(outputs)                  # None if < 2 voters
semantic           = (1 − sw)·mean_confidence + sw·cosine              # sw = SEMANTIC_CONSENSUS_WEIGHT; needs the engine

agreement_score = {"stance": stance, "lexical": lexical, "semantic": semantic}[method]
if agreement_score is None: agreement_score = lexical; method_used = "lexical"
```

With one agent, the lexical score is `mean_confidence`. `SemanticConsensusEngine.compute_agreement_score` still exists but the node no longer calls it; with the flag on and another method chosen, the cosine score is only reported. The `synthesis` SSE event carries the chosen score, `agreement_method_used`, and every component (`confidence_agreement_score`, `position_agreement_score`, `semantic_agreement_score`, `stance_agreement_score`, `stance_tally`). The moderator's self-reported agreement is only logged.

---

## Hybrid Consensus Gate

`consensus.py` holds the signals and predicate that decide termination; `finalize_node` reuses the helpers so the live gate and the final report agree.

### Helpers

| Function | Purpose |
|---|---|
| `select_dissenting_agents(responses, band)` | Agents whose confidence is more than `band` below the mean — the single definition of "dissenter" |
| `count_dissenting_agents(responses, band)` | Count of the above |
| `count_open_disagreements(critiques, severities=HIGH_SEVERITIES)` | Distinct **critic → target** critiques with `high`/`critical` severity — one objection per critique, however many bullet points it lists |
| `normalize_position_overlap(raw, floor, ceiling)` | See above |

`HIGH_SEVERITIES = frozenset({"critical", "high"})`.

### `ConsensusSignals` + `is_consensus_reached`

```python
@dataclass(frozen=True)
class ConsensusSignals:
    position_agreement: float     # Rule 1 agreement score [0,1] (stance / lexical / semantic)
    rounds_completed: int         # ds.current_round
    dissenting_agents: int
    open_disagreements: int
    confidence_converged: bool    # drift low, or spread tight, or all highly confident
    active_vetoes: int = 0        # Ethics-class vetoes standing this round

def is_consensus_reached(signals, *, threshold, min_rounds,
                         max_dissent, max_open_disagreements) -> bool:
    return (
        signals.active_vetoes == 0
        and signals.position_agreement >= threshold
        and signals.rounds_completed >= min_rounds
        and signals.dissenting_agents <= max_dissent
        and signals.open_disagreements <= max_open_disagreements
        and signals.confidence_converged
    )
```

**Every** criterion must hold; otherwise the debate continues until `max_rounds`. Thresholds (`MIN_DEBATE_ROUNDS`, `MAX_DISSENTERS_FOR_CONSENSUS`, `MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS`, `DRIFT_EARLY_STOP_THRESHOLD`, `CONFIDENCE_CONVERGENCE_SPREAD`, `ALL_CONFIDENT_THRESHOLD`) are in `Settings`; per-debate `consensus_threshold` / `min_rounds` come from the mode preset.

`confidence_converged` is true when drift (if measurable) < `DRIFT_EARLY_STOP_THRESHOLD`, **or** max − min confidence ≤ `CONFIDENCE_CONVERGENCE_SPREAD`, **or** every agent ≥ `ALL_CONFIDENT_THRESHOLD`. Confidence values come from the **current round only**.

---

## LLM Client — LangChainProvider

**File:** `app/services/llm_client.py`

Multi-provider adapter on **LangChain** for GROQ, OpenAI, Anthropic and Gemini. `GroqClient` remains as an alias for older imports.

```python
class LangChainProvider:
    def __init__(
        provider: str = "groq",       # "groq" | "openai" | "anthropic" | "gemini"
        api_key: str = "",
        model: str = "",
        base_url: str | None = None,
    )
```

The key is passed to LangChain as a `SecretStr` and not stored on the instance.

### Provider Factory

`_build_llm()` (also exposed as the static `get_llm()`) creates the chat model:

| Provider | LangChain Class | Default Model (`*_MODEL`) |
|---|---|---|
| `groq` | `ChatGroq` | `llama-3.3-70b-versatile` |
| `openai` | `ChatOpenAI` | `gpt-5.5` |
| `anthropic` | `ChatAnthropic` | `claude-opus-4-8` |
| `gemini` | `ChatGoogleGenerativeAI` | `gemini-3.5-flash` |

#### Sampling-parameter guard

Some models reject `temperature`/`top_p` (Anthropic Opus 4.7+ and the Fable/Mythos 5 family; OpenAI's `gpt-5*` reasoning family). `_sampling_kwargs(model)` omits them at construction, and `_supports_temperature()` / `_bind_call_params()` only bind a per-call `temperature` for models that accept it.

### Public Methods

#### `ainvoke_structured(schema, system_prompt, user_prompt, temperature=0.3, max_retries=2) → T`

Primary method (used by all agents through `BaseAgent._call_structured`). Uses `with_structured_output()` to return a validated Pydantic model.

- Retries via `with_retry(stop_after_attempt=1 + max(0, max_retries), wait_exponential_jitter=True)` — i.e. one attempt plus `max_retries` retries, from each agent's `AgentConfig`.
- Provider rate limits (HTTP 429, rate-limit exception classes, or a wrapped cause) raise **`LLMRateLimitError`**; other failures raise `LLMResponseError`.

#### `chat(system_prompt, user_prompt, temperature=0.7, max_tokens=2048) → str`

Plain-text completion. `LLMRateLimitError` on rate limits, `LLMConnectionError` on transport failures.

#### `chat_json(system_prompt, user_prompt, temperature=0.3) → dict`

Legacy: `chat()` + JSON parsing (`LLMResponseError` on bad JSON).

#### `close() → None`

No-op (LangChain manages connections).

### Concurrency slot — `llm_call_slot(provider)`

An async context manager that caps LLM calls in flight **per provider** at `LLM_MAX_CONCURRENCY` (default 4; `0` disables the cap):

- Semaphores are kept per event loop (`WeakKeyDictionary`) and per provider.
- A `ContextVar` makes the slot re-entrant: code already holding a slot (e.g. an agent call that runs a tool or nested call) doesn't take a second one, so it can't deadlock.
- The debate nodes take the slot **before** an agent's timeout starts, so queueing for a slot never times an agent out.

This keeps the critique burst (12 parallel calls) under the provider's rate limit.

### Server keys, defaults and the singleton

```python
def server_api_key(provider) -> str        # key from .env / environment for that provider
def server_default_model(provider) -> str  # *_MODEL for that provider

def get_llm_client() -> LangChainProvider  # lazy singleton for LLM_PROVIDER, built from the two maps
```

The same `server_api_key()` map is used by per-agent overrides in `AgentRegistry`, so every provider — Gemini included — gets its key the same way.

### Runtime Provider Switching

```python
def reset_llm_client(provider, api_key, model, custom_key=None) -> LangChainProvider
def get_active_provider_info() -> dict   # {"provider", "model", "using_custom_key"}
def llm_status() -> dict                 # {"provider", "model", "configured"} without creating the client
```

`POST /llm-settings` (admin-only) uses the caller's `api_key` if given, else the server key for that provider (400 if neither exists), then calls `reset_llm_client()`; a caller-supplied key is held in memory only (`using_custom_key`). `/health` reports `llm_status()`.

### Startup validation

`Settings` require the key of the **active** provider (`{LLM_PROVIDER}_API_KEY`) and fail at startup without it; other providers' keys are optional. Settings validation errors never echo input values (`hide_input_in_errors`), so a startup failure can't print API keys.

### Available Models per Provider (`PROVIDER_MODELS`)

Defined in `app/schemas/api_models.py` (first entry = UI default):

| Provider | Models |
|---|---|
| `groq` | llama-3.3-70b-versatile, llama-3.1-8b-instant, openai/gpt-oss-120b, openai/gpt-oss-20b, moonshotai/kimi-k2-instruct-0905, qwen/qwen3-32b |
| `openai` | gpt-5.5, gpt-5.5-pro, gpt-5.4-mini |
| `anthropic` | claude-opus-4-8, claude-sonnet-4-6, claude-haiku-4-5, claude-fable-5 |
| `gemini` | gemini-3.5-flash, gemini-3.1-pro-preview, gemini-2.5-pro, gemini-2.5-flash |

Used by the backend (`LLMSettingsUpdate` validation) and the frontend (dropdowns).

---

## Token Cost Estimation

`estimate_cost_usd(usage_by_model)` converts per-model token counts to a best-effort USD figure using `_MODEL_PRICES_PER_1M` (approximate input/output prices per 1M tokens). It returns `None` when no model has a listed price, so the UI hides the figure instead of showing `$0.00`. `DebateGraph` attaches it, with whole-debate `token_usage`, to the `FinalDecision`.

---

## Custom Exceptions

**File:** `app/utils/exceptions.py`

```
AgentBoardError (base)
  ├── LLMResponseError     → 502 Bad Gateway
  ├── LLMConnectionError   → 503 Service Unavailable
  ├── LLMRateLimitError    → 429 Too Many Requests
  └── DebateError          → 500 Internal Server Error
```

Mapped to HTTP responses by handlers in `app/main.py`. `public_error_message(exc)` gives a safe, user-facing message for each exception type (used for `resume_failed` and SSE `error` events), so internal details never reach the client.
