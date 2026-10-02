# AgentBoard — Bug Review & Fix Plan

**Review date:** 1 Oct 2026  
**Branch / commit:** `feature/AgentBoard_Improvement_01Oct` @ `f6f2258`  
**Scope:** whole repo: backend (FastAPI, LangGraph, services, DB), frontend (Next.js), Docker/CI/config  
**Code changed in this review:** none. All experiments ran on a throw-away copy in a temp folder, so your dev database was not touched.

---

## Fix progress

Legend: ✅ fixed and verified · 🟨 fixed, partly verified (see note) · ⏳ not started.  
Verification gate after every fix: full backend suite (`pytest`, isolated DB) + frontend unit tests / typecheck / lint where the frontend changed.

| ID | Status | What changed | Verification |
|---|---|---|---|
| AB-07 | ✅ | `tests/conftest.py`: dummy `GROQ_API_KEY`; session-scoped migrated template DB; autouse fixture gives every test its own DB, checkpoint file and KB dir under `tmp_path`. New `tests/test_test_isolation.py`. | Clean copy: 298 passed (was 10 failed). Repo run: SHA-1 of `agentboard.db` and `agentboard_checkpoints.db` identical before/after. Polluted-row cleanup (Appendix A.4) still needs your OK — it deletes data. |
| AB-01 | ✅ | `alembic/env.py`: `fileConfig(..., disable_existing_loggers=False)` and skipped entirely when `configure_logger` is False; `run_migrations()` sets that flag. New `tests/test_migrations_logging.py`. | Real app lifespan on a scratch copy now logs `Database migrations applied`, `AgentBoard starting up`, `http_request_completed`, `cleanup_complete`, … (all missing before). Suite green. |
| AB-09 | 🟨 | `backend/Dockerfile` and `docker-compose.yml`: `CHECKPOINT_DATABASE_URL=/data/agentboard_checkpoints.db` (on the volume). | `docker compose config` shows the variable on the backend service. Image not built: the Docker daemon is not running on this machine. |
| AB-41 | ✅ | `backend/.env.example` rewritten: every setting with its real default; comments on their own lines (so `run_all.bat`, which copies raw lines into env vars, can't pick up comment text). | Script check: no missing/unknown keys vs `Settings`; parsing via dotenv and via raw env vars gives identical settings equal to the code defaults. |
| AB-42 | ✅ | `run_all.sh`: resolves the repo-root venv (`venv/Scripts` or `venv/bin`), fails with a clear message if missing; absolute `cd`s. | `bash -n` OK; the resolved interpreter imports `uvicorn` and `app.main` from `backend/`. Servers not launched on purpose (startup runs TTL cleanup on your real DB). |
| AB-02 | ✅ | Calibrated from your real debates (read-only): unrelated positions overlap ~0.08, the same agent restating its stance ~0.19. New `normalize_position_overlap()` maps raw word-overlap onto 0–1 with those anchors (new settings `POSITION_OVERLAP_FLOOR/CEILING`) before the 0.7/0.3 blend. `count_open_disagreements()` now counts distinct critic→target critiques, not bullet points. Synthesis event also carries `position_agreement_score`. Thresholds and the other gate criteria unchanged. | Replaying the gate on 29 real final rounds: standard consensus 6/29 (was 0/29) — reachable, still demanding. New tests: anchors/clamping, per-critique counting, verbose single critique doesn't block, three real-settings gate tests (typical agreeing overlap 0.16 → consensus; unrelated 0.08 → max rounds; low confidence blocks). The 0.16 test fails with the old formula (proved by patching it back). Suite: 307 passed. |
| AB-03 | ✅ | Moderator finalize prompt now carries a "Human reviewer override — MUST follow" block when `human_feedback` is set; new `FinalDecision.human_feedback` field; `ApproveRequest` rejects an override with empty feedback; Markdown/PDF exports and the decision panel (plus copy-summary) show the reviewer direction; HITL panel won't submit an empty override. | New `tests/test_hitl_override.py` (prompt with/without feedback, braces safe, decision records it, validation, **real LangGraph pause → override run** whose captured finalize prompt contains the feedback, exports escape HTML). New FE tests for the panel block. Backend 318 passed; FE tsc OK, 68 tests passed, lint clean. |
| AB-05 | ✅ | `POST /debate/{id}/resume`: 409 `debate_awaiting_approval` (pointing to `/approve`) when the debate is paused for review; if a resumed run pauses again, persist the state and return **202** with the status instead of caching/returning `None`. (Resuming a *cancelled* debate is still allowed — that is a legitimate restart.) | New API tests: paused debate → 409, graph never called, nothing cached; resume that pauses again → 202, no `None` in `decision_store`, `GET /decision` still 409. Suite: 320 passed. |
| AB-06 | ✅ | `retriever.py`: new `_document_name()` uses the uploader's name from `metadata["source"]` (directory parts of either separator style stripped, length capped), falling back to the file's own name; used for the `source` metadata, the stale-chunk purge and logs. Chunk IDs now include a hash of the document name, so identical text under two names no longer overwrites the other's chunks. | New tests: temp-named upload is purged/indexed under `report.txt`; identical content under two names → disjoint IDs; name sanitising; the upload route passes the original file name while ingesting a temp path. Suite: 326 passed. Documents already indexed under `tmp*.pdf` names must be re-uploaded once (then delete the `tmp*` entries). |
| AB-08 | ✅ | `llm_client.py`: new `_bind_call_params()` used by `ainvoke_structured()` and `chat()` — binds `temperature` only for models that accept it (`max_tokens` still bound). Retry count fixed: `max_retries=N` now means 1 attempt + N retries (`stop_after_attempt=1+N`; before, N attempts, so 0 and 1 both meant one call). | **Real library payloads** (langchain-openai 1.1.12 / langchain-anthropic 1.4.0 on a clean Python 3.11): old code sent `temperature=0.3` to `gpt-5.5`, `gpt-5.4-mini`, `claude-opus-4-8`, `claude-fable-5`; new code sends none to those and still sends 0.3 to `gpt-4o` / `claude-sonnet-4-6`. New unit tests for both paths + retry semantics. Suite: 332 passed. |
| AB-24 | ✅ | `crud.get_history()`: `total_rounds` = rounds actually run (`current_round`); when the debates row is missing, rounds/reason/agreement come from the stored decision JSON and the status is derived from the reason — no more invented `converged` / `consensus_reached` / `4`. History page: "Human Override" filter chip and violet badge (was shown as "Max Rounds"). `GET /debate/{id}` keeps `total_rounds = max_rounds` because its schema documents it as the maximum. | New `tests/test_history_items.py` (rounds run vs max, override reported, missing-row fallback). On a copy of your dev DB the "quantum computing" debates now show 1 round (was 4). Backend 335 passed; FE tsc OK, 68 passed, lint clean. |
| AB-48 | ✅ | Convergence node: `confidence_scores` rebuilt from the current round only (a timed-out agent's old score no longer feeds the gate); drift is computed only when the previous round shares agents with this one, otherwise it is "unknown" instead of 0.0 ("stopped moving"). | New tests: empty previous round no longer yields consensus via fake zero drift; dropped agent's stale 0.3 confidence no longer blocks a clean consensus. Analytics' per-agent average now reflects the final round, matching the field's documented meaning. Suite: 337 passed. |
| AB-04 | ✅ | **Backend:** `POST /debate/{id}/approve` validates synchronously (404 / 409 already running / 409 not awaiting approval), then runs the continuation as a background task through the same `_run_debate_background` lifecycle as `start-async` (event writer, SSE, terminal frames, cleanup) and returns **202**. `on_state_change` now also keeps `debate_store` current (`_track_state_changes`), and the error/cancel paths use the newest snapshot — continuations run on a checkpoint *copy*, so they used to persist a stale state over the new round. **Frontend:** `clear_approval` carries the answered round and leaves a newer request alone; HITL panel passes its round; "Paused — waiting for your review." replaces the spinner while paused. | New `tests/test_hitl_async_approve.py` (real LangGraph + HTTP API: start supervised → pause → add_round 202 → duplicate 409 → paused at round 2 with 2 `approval_required` events → approve → decision; not-paused 409; unknown 404; failure inside the extra round persists round 2 — this test fails with the old persist-only callback). New Playwright `e2e/hitl.spec.ts` replays the exact race with id-based resume; it **fails with the old unconditional clear** and passes with the fix. New reducer tests. Backend 341 passed; FE 70 unit passed, tsc/lint clean; full e2e: same 16 pre-existing failures as the untouched baseline (see AB-49), 0 new. |
| AB-17 | ✅ | In-flight guard for approve and resume: a running background task (checked with `done()`) or an in-request resume → 409, checked before any `await` so it can't be raced. Task done-callbacks (`_forget_task`) only unregister their own task, so an old run's callback can't drop a newer one. | Duplicate-approve 409 covered end-to-end above; resume-while-running test updated to use a realistic running task. Cancel now also works for approval continuations (they are registered background tasks). |
| AB-12 | ✅ | Backend: quiet SSE connections now get a named `event: ping` (every `_SSE_KEEPALIVE_SECONDS` = 20 s) instead of a `: keep-alive` comment that `EventSource` never surfaces. Frontend `connectToStream`: a `ping` resets the stale timer and the reconnect counter and is not forwarded to the reducer; the abort listener is registered once (it was added again on every reconnect). Deliberately *not* resetting attempts on `onopen`, so a server that accepts-then-closes can't cause endless reconnects. | Backend test drives the real stream generator: a paused debate yields `event: ping` frames. New FE tests with a fake EventSource + fake timers: 15 min of pings → still 1 connection, no error; silent connection → reconnect after 60 s; pings not forwarded; abort closes the current source and stops reconnects. Backend 345 passed; FE 74 passed, tsc/lint clean; stream-related e2e specs: only the baseline failures. |
| AB-33 | ✅ | Stream generator returns right after replaying a terminal frame; a finished (`converged`/`max_rounds_reached`) debate whose decision can't be loaded now gets an `error: decision_unavailable` frame instead of an endless ping loop; on disconnect the subscriber list is dropped only for terminal debates (running/paused debates keep it — their writer broadcasts to that exact list). | New generator tests: terminal replay → exactly 1 frame and no leftover `all_queues` entry (old code idled with pings); finished-without-decision → error frame; paused → stays open and keeps its list. |
| AB-13 | ✅ | FE `api.ts`: new `extractErrorMessage()` understands `{detail: str}`, nested ErrorResponse `{detail: {error, detail}}`, FastAPI validation lists and the rate limiter's `{error}`; `ApiError` gains `code`; LLM failure codes (`llm_response_error`, `llm_connection_error`, `llm_rate_limit`) get their own messages instead of "Backend unavailable"; a proxy 502 without a code still says the backend is unavailable. | New `apiError.test.ts` (nested detail → real text, not `[object Object]`; validation list joined; rate-limiter text; LLM codes; unreachable cases). FE 82 passed, tsc/lint clean; error/compare/HITL e2e specs 18/18. |
| AB-14 | ✅ | BE: new `public_error_message()` (`app/utils/exceptions.py`); SSE error events now carry a safe message plus `error_type`, the full exception stays in the (now working) server log; `resume_failed` responses no longer embed `str(exc)` and the failure branch keeps the newest checkpoint state. FE reducer maps on `error_type` / error code (`debate_recovery_required`, `decision_unavailable`), keeping the old text scan only for events stored before this change. The synchronous `LLM*` exception handlers still return their detail — two existing tests document that for API consumers, and the UI now shows its own wording for those codes. | New `tests/test_error_messages.py`: public messages never contain the provider org ID; a failing background debate persists an `error` event with `error_type=LLMResponseError` and the safe text. New FE reducer tests. Backend 350 passed. |
| AB-15 | 🟨 | (1) 429s are classified as `LLMRateLimitError` (status code / class name / cause chain) in `ainvoke_structured()` and `chat()`. (2) New `llm_call_slot()` caps calls in flight per provider (`LLM_MAX_CONCURRENCY`, default 4, 0 = off). Debate nodes take the slot *before* starting an agent's timeout, and the slot is re-entrant via a context variable, so queueing never times an agent out. (3) Moderator `synthesize`/`finalize` wait 10 s then 20 s and retry on rate limits. (4) A failed per-round synthesis no longer kills a round that has agent output (placeholder summary; the gate uses agent outputs). With zero agent output it still fails, so e.g. a bad API key still stops early. | Evidence from your logs: 63 of 228 LLM calls failed, 45 of them 429s, mostly in the critique burst. New `tests/test_rate_limits.py` (12): classification incl. wrapped causes; peak concurrency == limit; per-provider + re-entrant (no deadlock); 0 disables; three 0.3 s calls through 1 slot all succeed under 0.5 s timeouts — **with a client-only limiter just 1 of 3 survives** (proved by patching); moderator retry/give-up/no-retry-for-other-errors; synthesis fallback both ways. Backend 362 passed. 🟨 because the effect on a real provider's rate limit was not measured (no live key used). |
| AB-35 | ✅ | `MAX_DEBATE_ROUNDS_LIMIT = 8` in `schemas/state.py` drives the schema bounds; the HITL payload only offers `add_round` below the limit; `POST /approve` with `add_round` at the limit → 409 `round_limit_reached`; the HITL node refuses to exceed the limit (finalises instead). FE panel hides "+ Add Round" when it isn't offered. | New `tests/test_round_limit.py` (options at/below limit; node at limit keeps 8 and the state still validates; API 409 leaves the debate paused). New `HITLPanel.test.tsx` (button hidden at limit, answered round reported, empty override can't be submitted). Backend 365 passed; FE 86 passed, tsc/lint clean. |
| AB-16 | ✅ | Long work no longer rides on one HTTP request: **approve** is a background task (AB-04); new **`POST /debate/{id}/resume-async`** (checkpoint pre-checked → clean 400; 409 when finished/running/paused) streams over SSE, and both the stream generator and the reducer treat only events after the latest `debate_resumed` as the current run (a resumed debate's history still contains the old error); **simulation** is a job: `POST /debate/simulate-async` (same 2/hour cap) → `GET /debate/simulate/{job_id}` → `POST …/cancel`, finished jobs pruned after an hour, failures reported with the safe message; the simulate page polls it, has a Cancel button and cancels the job when you leave. The proxy forwards `req.signal` and stays quiet on client aborts. The synchronous `/debate/start`, `/debate/simulate` and `/debate/{id}/resume` remain for API callers. | New `tests/test_background_jobs.py` (7): a real failed debate resumed via resume-async finishes (decision exists, `debate_resumed` after `error`); resume-async 404/400/409; resumed-debate stream stays open past the old error frame (old logic ended it); simulation job completes / fails safely / cancels. **Live stack** (scratch uvicorn + Next dev proxy): SSE ping still arrives through the proxy; after the client disconnects the proxy→backend sockets drop 2 → 0 (old proxy: stay at 2); simulate-async/poll, cancel and resume-async all answer correctly; no tracebacks in the server log. Backend 372 passed. |
| AB-34 | ✅ | `POST /cancel` cancels a debate **paused for review** directly (status `cancelled`, persisted + broadcast `cancelled` frame, stream closed). HITL panel: "Cancel this debate". Debate page: **"Resume debate"** button on backend-reported failures (calls resume-async, resets the view and re-streams); "Stop debate" re-enables if the cancel request fails. Home "Cancel" no longer aborts the start request blindly — if the server already created the debate, it is cancelled via its thread id (and an unmounted page no longer navigates). | Paused-cancel test (subscriber gets `cancelled` + close, DB status `cancelled`, entry cleaned up) in `test_background_jobs.py`; live check: cancelling the seeded paused debate through the proxy → `cancelled`. FE 86 passed, tsc/lint clean. |
| AB-11 | ✅ | New `client_ip()` key function (`core/rate_limiter.py`): when the TCP peer is in `TRUSTED_PROXY_IPS` (IPs/CIDRs, default loopback) the client is the **right-most** valid `X-Forwarded-For` hop (the one the nearest proxy added; client-supplied left-most entries are ignored), otherwise the peer itself. Used by the limiter, request logs and audit logs. Proxy: dropped the `"unknown"` fallback (measured: the Next server already fills `x-forwarded-for` with the client's socket address, or keeps an edge proxy's value). docker-compose trusts the compose network (`172.16.0.0/12`) with a note not to publish port 8000 publicly. | New `tests/test_client_ip.py` (trusted/CIDR, right-most hop, untrusted peer can't spoof, invalid value → peer; two clients behind the proxy get separate 2/hour buckets — **fails with the old `get_remote_address`**). **Live stack:** through the Next proxy Alice's 3rd simulate-async → 429 while Bob's → 202; backend logs show the real client IPs. Backend 377 passed; FE tsc/lint clean. |
| AB-10 | ✅ | New `ADMIN_API_TOKEN` + `core/security.require_admin`: switching the global LLM provider, clearing agent memory and deleting KB documents need `X-Admin-Token` when a token is set (constant-time compare); with no token they are **refused in production** and open in development. `/llm-settings` uses the server's key for the chosen provider unless the caller supplies one (400 `api_key_required` if neither); `GET /llm-settings` reports `server_keys` and `admin_token_required`. FE: keys move from localStorage to **sessionStorage** (older saved keys are migrated off disk), key field optional when the server has one, admin-token field when required, `apiFetch` now *merges* headers (passing any header used to drop `Content-Type`), settings errors use the parsed message (a 422 list used to crash rendering). KB uploads stay open (core feature, rate-limited). | New `tests/test_admin_security.py` (8): server key used / missing key 400 / custom key flagged; token required (none/wrong → 401, right → 200); production without token → 403; memory-clear and KB-delete guarded; settings report flags. New `LLMSettingsPanel.test.tsx` (legacy key migrated, optional key with server key, token sent with Content-Type preserved). Backend 385 passed; FE 89 passed, tsc/lint clean. Per-debate provider selection (true multi-tenant BYOK) stays a feature idea in section 4. |
| AB-31 | ✅ | New `UploadSizeLimitMiddleware` (pure ASGI, inside the request-ID layer so its 413 is logged) refuses `POST /knowledge/upload` when `Content-Length` exceeds the limit + 64 KB framing, before the multipart body is parsed. The route checks the parsed `file.size` and copies the upload to the temp file in 1 MB chunks with a hard cap (the whole file is never held in memory); the temp file is always removed. | New `tests/test_upload_limits.py`: 2 MB upload over a 1 MB limit → 413, ingest not called; a declared 50 MB body is refused without being read; a file just over the limit (within the framing allowance) is caught by the route; a normal file is ingested with its original name. Backend 389 passed. |
| AB-21 | ✅ | `run_migrations()` switches the main DB to **WAL** (persists in the file; skipped for `:memory:`). The per-debate event writer retries a "database is locked" failure twice (0.25 s, 0.5 s), rolling back the half-finished transaction first so a commit-time failure can't leave a duplicate; any other failure is logged once as before and the event is still broadcast live. | Measured in a scratch contention test (8 writers + 4 readers, 0.5 s busy timeout): rollback journal 15 lock errors / 5.2 s vs WAL 5 / 1.6 s. New `tests/test_sqlite_concurrency.py`: migrated DB reports `wal`; two transient locks (with a partial insert each) → exactly one stored event, same `_event_id` live and persisted; a persistent lock still broadcasts. Backend 392 passed. Note: your dev DB switches to WAL on the next server start (reversible with `PRAGMA journal_mode=DELETE`). |
| AB-38 | ✅ | `Settings` field validator: relative `DATABASE_URL`, `CHECKPOINT_DATABASE_URL`, `KNOWLEDGE_BASE_DIR` resolve against `backend/` (new `BACKEND_DIR`), and `sqlite:///…` / `sqlite+aiosqlite:///…` become plain paths, so Alembic, aiosqlite and the checkpointer all open the same file. Absolute paths (Docker `/data/...`) and `:memory:` unchanged. `.env.example` comment updated. | Resolving from `backend/` and from the repo root now gives the same `backend/agentboard.db`. New `tests/test_config_paths.py` (chdir elsewhere → still backend/; URL prefixes stripped; absolute/`:memory:` untouched; migrations through a `sqlite:///` URL create the tables in that exact file and no file literally named `sqlite:…`). Backend 397 passed. The stale empty root `agentboard.db` is yours to delete. |
| AB-20 | ✅ | `debate_graph.py`: checkpoints now use a `JsonPlusSerializer` with an explicit allow-list of the app's checkpointed models (`DebateState`, `DebateRound`, `AgentResponse`, `CritiqueResponse`, `FinalDecision`, `MinorityReportEntry`, `StructuredDisagreement`, `AgentStance`) via a new `_open_checkpointer()` (same as `from_conn_string`, plus the serializer). | Real-LangGraph HITL / resume / approve tests run under the strict allow-list with **0** "unregistered"/"blocked" warnings (was a warning per load). Backend 397 passed. Versions are now pinned by `requirements.lock` (AB-28): langgraph 1.1.3, langgraph-checkpoint 4.0.1, langgraph-checkpoint-sqlite 3.0.3, langchain-core 1.4.7, and `requirements.txt` keeps LangGraph/LangChain below their next major, so an upgrade can only happen by regenerating and re-testing the lock. |
| AB-22 | ✅ | PDF export renders with `asyncio.to_thread`. `KnowledgeBase.is_available` is now a cheap check (initialised, or packages installed and no failure in the last 5 min) that never loads anything; the heavy Chroma/model load happens in `ensure_ready()` on a worker thread, which records and logs the real exception once and retries after 5 minutes (it used to retry — synchronously — on every call). `retrieve`/`list`/`delete` degrade gracefully; `ingest` raises a typed `KnowledgeBaseUnavailable` → upload returns 501. Startup warms the KB as a background task. | New `tests/test_blocking_work.py` (6): `is_available` never initialises; failed init logged with its cause, not retried immediately, retried after the window; ingest raises typed error → upload 501; **app startup with a 2 s model load is ready in < 1.5 s** (old code awaited it synchronously); PDF rendering runs on a non-loop thread. Backend 404 passed. |
| AB-39 | ✅ | `setup_logging(level, log_dir)`: one fixed base name `agentboard.log` rotated nightly to `agentboard.log.YYYY-MM-DD`, so `backupCount=30` prunes across restarts; new `LOG_DIR` setting (anchored to `backend/`); old handlers are closed on re-setup. Tests point `LOG_DIR` at `tmp_path` and release file handlers at teardown — found while adding a lifespan test, which had written test logs into your real `backend/logs/` (that file was deleted; your older logs are untouched). | New rotation test: with 35 rotated days present the handler schedules exactly the 5 oldest for deletion. A full test run no longer creates anything in `backend/logs/`. Your old `agentboard_YYYY-MM-DD.log` files are not auto-pruned by the new scheme — delete them when no longer needed. |
| AB-27 | 🟨 | `Dockerfile`: `HF_HOME=/data/hf-cache` and `XDG_CACHE_HOME=/data/.cache` on the app-owned data volume (the non-root user's home is `/nonexistent`). The KB now logs the real initialisation error (`knowledge_base_unavailable`) instead of silently reporting "unavailable". | Config reviewed (`/data` is created and chowned before `USER appuser`). Image not built — Docker daemon not running here. |
| AB-18 | ✅ | `debate_store` / `decision_store` are now `BoundedStore`s (200 entries): past capacity they evict their oldest **finished** debates only (running/paused ones stay, since recovering an in-progress run from the DB would mark it orphaned); evicted entries are re-read from SQLite on next use. The KB retrieval cache is a 256-entry LRU. | New `tests/test_resource_hygiene.py`: eviction order, live debates never dropped even over capacity, an evicted decision is still served from the DB, retrieve cache stays bounded. Backend 411 passed. |
| AB-19 | ✅ | A debate's checkpoints are deleted once its decision is **successfully** stored (async/approve/resume runner, sync start, sync resume via new `_finish_debate`); failed/cancelled/paused debates keep theirs so they stay resumable. Simulation runs delete their own. Startup runs `prune_finished_checkpoints()` (decided or unknown threads) and `VACUUM`s. | Tests: startup prune keeps only the failed debate; a completed async debate has no checkpoints while a failed one keeps them; a 2-run simulation leaves none. **On copies of your real DBs:** 52 → 18 threads, 12.9 MB → 1.9 MB, kept threads are all `error`/`cancelled`/`in_progress`/`initialized`. Your real checkpoint DB will be pruned the same way on the next server start. |
| AB-29 | ✅ | Agent-memory save tasks are kept in a module-level set until they finish (the event loop only holds weak references). `AgentMemoryStore` resolves the *currently active* LLM client at save time unless one is pinned, so a provider switched via `/llm-settings` also applies to memory summaries (startup no longer captures the client). | New tests: tasks stay referenced while running and are released when done; the store follows the active client and honours a pinned one. |
| AB-30 | ✅ | `DebateState.token_usage_by_model` accumulates usage across segments; `run`/`resume`/`approve` merge the segment's usage with the prior total (`_merge_usage`, integer counters only) and attach the cumulative total to the decision. Routes pass the stored total into approve, resume-async and sync resume (checkpoints don't carry usage merged after a segment). | New tests: merge maths; **HITL end-to-end through the API** with 110 tokens per segment → decision reports 200 input / 20 output / 220 total and a cost (old code: only the last segment). Backend 415 passed. |
| AB-50 | ✅ | `_ensure_checkpoint_schema()` creates the checkpoint tables once per DB path under a process-wide lock (LangGraph's own `SqliteSaver.setup()`, run in a worker thread) before any saver connection is used. | Experiment: concurrent runs on fresh checkpoint DBs 12/60 failed → **0/100** with the fix. New regression test (5 fresh DBs × 4 concurrent debates) **fails 3/3 without the fix**, passes with it; the full suite ran 6× in a row green (it had been flaky). Backend 416 passed. |
| AB-23 | ✅ | (a) `SimulateRequest.max_rounds` is optional — omitted, the mode's preset applies (it used to default to 3 and always override the mode); the simulate page leaves it empty ("Mode default") unless set. (b) Consistency = mean pairwise decision overlap rescaled with the consensus-gate anchors (measured on your DB: repeat runs of one question overlap ~0.205, unrelated ~0.075), so "High/Medium/Low" can actually vary. (c) Stable risk flags match paraphrases (content words, light stemming, overlap ≥ 0.6 of the shorter flag with ≥ 2 shared words; single-word flags must match exactly) and are reported once each. `confidence_variance` keeps its name for API compatibility (its description already says it's a standard deviation). | New `tests/test_simulation_metrics.py`: a **real pair of stored decisions** (overlap 0.205) → High (old formula: Low, 0.47); unrelated → Low; paraphrased "industry disruption" flags recognised across 3 runs; generic "…challenges" flags not glued together; existing exact single-word case still works; thorough mode → 6 rounds when `max_rounds` omitted. Backend 422 passed; FE 89 passed, tsc/lint clean. |
| AB-40 | 🟨 | Startup no longer waits for the embedding model (AB-22 background warm), so `/health` answers within the existing `start_period`. | Covered by the startup-time test in AB-22. Container healthcheck itself not exercised (no Docker daemon). |
| AB-25 | ✅ | `GET /history` takes whitelisted `sort` (`newest` / `oldest` / `highest_agreement`) and `termination_reason` (`consensus_reached` / `human_override` / `max_rounds_reached`) query params (anything else → 422); `crud.get_history()` filters and orders in SQL before `LIMIT/OFFSET`, using the same debates-row → decision-JSON fallbacks as the list items, so the count matches the filter. History page drops its per-page `filter`/`sort`, sends both to the server, resets to page 1 on change, and ignores any response that isn't from the latest request. | New `tests/test_history_query.py` (25 debates: best agreement and overrides live past page 1 by date; filter-then-page; combined search+filter+sort; route params + 422 on injection-style values) — **all 6 fail** with the old SQL. New `HistoryPage.test.tsx` (server params, server order kept, slow-then-fast responses) — **all 3 fail** with the old page logic. On a copy of the dev DB the three filters partition the 210 decisions exactly (201 + 0 + 9). Backend 431 passed, ruff clean except the pre-existing `llm_client.py:178`; FE 92 unit passed, tsc/lint clean; history e2e 7/8 (the 1 failure is the pre-existing AB-49 "View" link). |
| AB-47 | ✅ | (a) History search escapes `\`, `%` and `_` and uses `LIKE … ESCAPE '\'`, so they match literally. (b) `save_decision`'s upsert no longer overwrites `created_at`, so a re-save keeps the debate's place in history (cached `evaluation_json` was already kept). (c) New Alembic revision `c3e7a9f1b2d4` replaces the `(agent_name, created_at)` index with `(agent_name COLLATE NOCASE, created_at)`, which the existing case-insensitive memory queries can use — no stored names are rewritten. | (a) `test_search_wildcards_match_literally` (`50%`, `user_id`, `C:\temp`, bare `%`). (b)+(c) new `tests/test_crud_details.py`: re-save ordering and `EXPLAIN QUERY PLAN` (was `SCAN agent_memory` + `TEMP B-TREE`, now the index, also for `DELETE`) — both **fail without the fix**; lookups stay case-insensitive. Migration upgrade → downgrade → upgrade on a copy of the dev DB: row counts unchanged, indexes swapped each way; dev DB SHA-1 unchanged. |
| AB-26 | 🟨 | (a) The analytics cache is cleared when a debate is stored (`_persist_debate`) or a decision is evaluated. (b) Overview returns `avg_rounds` (all completed) and a real `avg_rounds_to_consensus` (consensus-only, `null` if none); termination reasons for older debates rows fall back to the stored decision, as in history (AB-24). (c) The agreement matrix is built from each pair's final-round positions on the consensus gate's 0–1 scale: symmetric, `null` for pairs that never met (was co-confidence > 0.7 divided asymmetrically). (d) `custom` is a real `DebateMode` (Standard's settings plus the caller's rounds/threshold) and the UI sends it. (e) `template_id` is sent by the home page (template card or template chip; dropped when the box is cleared), stored on `DebateState`, and template stats only count those debates, by title (unknown ids are dropped, not fatal). (g) Trend shows completed debates over the selected range (`trend_days`), labelled accordingly. **(f) not changed:** every endpoint takes ≤ 18 ms on the real 269-debate DB and results are cached, so moving aggregates into columns is deferred. | New `tests/test_analytics_accuracy.py` (11, real DB): 7 data tests **all fail** with the old crud/routes; the 2 obsolete fake-DB overview tests were replaced. New `DebateInput.test.tsx` (custom mode, template tracking — 3/5 fail with the old mapping) and `AnalyticsPage.test.tsx` (3/3 fail with the old page). On a copy of the dev DB: consensus rate 95.7% (was 10/210 ≈ 4.8%, 191 "unknown"), matrix symmetric, template stats empty instead of domain packs. Backend 440 passed, ruff baseline; FE 100 unit passed, tsc/lint clean; full e2e 15 failed / 56 passed — all 15 in the AB-49 pre-existing list, 0 new. |
| AB-28 | 🟨 | **CI:** `docker-publish.yml` gets `test-backend` (Python 3.11, `pip install -r requirements-dev.lock`, `ruff check .`, `mypy app`, `pytest -q`) and `test-frontend` (Node 20, `npm ci --legacy-peer-deps` as in the frontend Dockerfile, `npm run verify`); both image builds `needs:` them, so nothing is built or pushed when a test fails. **Locks:** `requirements.txt` now lists direct dependencies as ranges (LangGraph/LangChain below the next major); `requirements.lock` / `requirements-dev.lock` are universal uv locks (Linux, Windows, macOS 14+) pinned to the versions the suite was verified on: fastapi 0.135.2, pydantic 2.13.4, langgraph 1.1.3, langchain-core 1.4.7 and so on; numpy 2.4.6 is the newest for Python 3.11. torch comes from the CPU-only index (`2.11.0+cpu`, no nvidia/triton packages). **Docker** installs `requirements.lock`. **Docs:** README / command.md recreate the venv from the lock; `requirements-dev.txt` has the regeneration commands. To make the gates pass: wrapped the over-long import in `llm_client.py` (ruff), and fixed all 28 mypy errors, the real one being that `run`/`resume`/`approve` return no decision when a supervised debate pauses; they are now typed `FinalDecision | None`, and the three callers that need a decision use `require_decision()`, raising a clear error instead of an `AttributeError`. | Clean Linux (WSL Ubuntu 24.04) Python 3.11 venv from `requirements-dev.lock` with plain pip: installs in 289 s, `pip check` clean, 0 CUDA packages, 1.9 GB site-packages; `langchain_openai`, `langchain_anthropic`, `tiktoken`, `jiter`, `chromadb`, `sentence_transformers`, `weasyprint` import (several fail in the old local venv). On that install: **mypy clean (was 28 errors), ruff clean, pytest 482 passed**. The lock's Linux/3.11 pins equal the tested Linux-only resolution; `uv` resolves every pin for Windows, Linux and macOS 14+. `npm ci --legacy-peer-deps` dry run OK (plain `npm ci` fails with ERESOLVE, as the Dockerfile already knew). Windows: backend 467 passed + 1 skipped, FE 101 passed. 🟨 because GitHub Actions and `docker build` were not run here (no runner, no Docker daemon). |
| AB-46 | ✅ | `_safe_calc` evaluates with explicit namespaces (`local_dict` = only `pi`/`e`, `global_dict={}`), so numexpr can no longer read names from the calling frame or module; any name other than a whitelisted math function or constant is refused up front (literal exponents like `1e5` are allowed); input capped at 200 characters. | New `tests/test_calculator_tool.py` (15). On the clean Linux install: 15 passed; with the old function 9 fail. The old code really did resolve its own local `expression`: *NumExpr 2 does not support Unicode as a dtype*. Locally the module is skipped because the old venv's numexpr can't import (AB-28). |
| AB-37 | ✅ | Per-agent overrides take the key from `server_api_key()` (now including Gemini) instead of a private three-provider map; `get_llm_client()` uses the same `server_api_key()` plus a new `server_default_model()`, so there is one provider→key/model map. | New `tests/test_provider_keys.py`: overrides for gemini/openai/anthropic build the client with that provider's key (the **gemini case fails with the old map**), a missing key still raises clearly, and the global client uses the same map for all four providers. |
| AB-32 | ✅ | `DebateStartRequest` and `SimulateRequest` reject an explicit agent list with fewer than 2 agents besides the Moderator (422 with a clear message; a domain pack still replaces the list; `None`/`[]` keep meaning all agents). Also found: `["Moderator"]` used to fall back silently to all agents, and `["Moderator", "Analyst"]` ran a one-agent debate. The home page now counts debaters, not set size, when you deselect agents. | New `tests/test_agent_selection.py` (19, models + HTTP 422): **9 fail without the validator**. New `HomePage.test.tsx` deselects down to Ethics + Moderator and checks the request still carries Strategy + Ethics; **fails with the old `size <= 2` rule**. |
| AB-36 | ✅ | `GROQ_API_KEY` is optional; Settings fail at startup only when the *active* provider's key is empty; `Settings` sets `hide_input_in_errors` (a validation error was echoing the start of a real API key). `/health` adds `llm: {provider, model, configured}` for the live provider without creating the client; `groq_configured` kept. | New `tests/test_provider_config.py` (8): **all fail on the old config**. |
| AB-45 | ✅ | Removed unused `SECRET_KEY` (and its docs) and the unused `_DRIFT_EARLY_STOP_THRESHOLD`; node timeout defaults now mirror the Settings defaults (were 15 s vs 45 s); `domain_focus` no longer claims to be injected into prompts; frontend Dockerfile comment describes the route-handler proxy. | New `tests/test_config_consistency.py` (3): **all fail on the old code**. |
| AB-43 | ✅ | The moderator's own `should_continue` is no longer sent in the `synthesis` event (the gate decides; logged as `moderator_recommends_continue`); its prompt drops the hard-coded 0.75 stop rule; schema fields described as advisory. Moderator LLM calls go through `_call_structured` (logging + configured temperature/retries), keeping the rate-limit backoff. | New `tests/test_moderator_signals.py` (5): **all fail on the old code**. |
| AB-44 | ✅ | Structured Ethics veto: `EthicsLLMOutput` (veto, veto_reason) for Ethics, FinancialEthics, PatientSafety; `AgentResponse.veto/veto_reason`; `ConsensusSignals.active_vetoes` blocks consensus; moderator finalize prompt lists standing vetoes and `FinalDecision.vetoes` carries them; SSE `agent_output`, Markdown/HTML export, AgentCard badge, FinalDecisionPanel block; `VetoEntry` added to the checkpoint allow-list. | New `tests/test_ethics_veto.py` (12) and 5 FE tests; targeted mutations (gate check / decision vetoes / UI) are caught. Gates: Windows 495 passed + 1 skipped; Linux clean install mypy clean, ruff clean, **510 passed**; FE 106 passed, tsc/lint clean. |
| AB-49 | ✅ | **Tests updated to the current UI:** home (new heading, Templates toggle, gallery scoped as a labelled region because titles also appear as starter chips), debate (query banner scoped, new consensus/max-rounds headlines, round progress tested on a stream that stays open via a new `serveOpenStream` fixture), history, simulation (mock moved to the job API: simulate-async → poll; fields found by label). **Real bugs the stale tests exposed, fixed:** (1) `connectToStream` registered a listener for the server's named `error` event, which also received the browser's data-less connection-error event and reset the retry counter, so a dropped stream retried every 1 s forever, never backed off and never gave up; such events are now ignored there. (2) After a successful reconnect the status stayed "Reconnecting…"; `onopen` now reports connected. (3) A lost connection showed "Debate failed" and a full page reload, although the debate usually keeps running; it now shows "Connection lost" with an in-place Reconnect, and the unreachable "Connection lost" banner was removed. (4) History View/Compare were buttons calling `router.push`; they are now links (open in new tab, announced as links), using a new `buttonClasses()` helper. (5) Simulation form labels weren't associated with their inputs. Home template gallery gets `aria-controls` + a labelled region. **CI:** the frontend job installs Chromium and runs `npm run e2e`, uploading the report on failure; Playwright output is git-ignored. | Full Playwright suite: **71 passed, 0 failed** (was 56/15), 1.1 min (was 6 min). New unit tests: backoff gives up after 10 failures even when the native error event reaches the named listener (**fails without the fix**), server `error` events still delivered, status returns to connected after a reconnect (**fails without the fix**). The connection-lost e2e test uses Playwright's fake clock to skip the ~3 min backoff and then reconnects to the full decision. FE 109 unit passed, tsc/lint clean. |

---

## 0. How to read this document

| Field | Meaning |
|---|---|
| **Severity** | **High** = wrong results, data loss, broken feature, or security exposure. **Medium** = reliability or UX problem with a clear failure mode. **Low** = edge case, cleanup, or polish. |
| **Evidence: Confirmed** | Reproduced in an isolated experiment, or visible in your real log files / database. |
| **Evidence: Code-verified** | Follows directly from the code (and library source where noted); no runtime needed to be sure. |
| **Evidence: Likely** | Depends on environment, timing, or version. Reproduce it first, then fix. |
| **Effort** | S = under 2 h, M = half to 1 day, L = more than 1 day. |

**Convention for fixes:** keep the `AB-xx` IDs and dates out of code comments. Use plain, descriptive comments in code, and put the IDs in commit messages and PR descriptions.

---

## 1. Executive summary

**Test baseline (backend):** 293 tests. On a clean checkout **283 pass and 10 fail** with `sqlite3.OperationalError: no such table: decisions`. They pass on your machine only because they reuse, and write into, your real `backend/agentboard.db` (see AB-07).

**The 10 fixes that matter most:**

1. **AB-01:** Alembic's `fileConfig()` disables every application logger at startup. Your production logs contain no API, DB, audit, or error logs. *(Confirmed)*
2. **AB-02:** The consensus gate can almost never pass in **Standard** or **Thorough** mode. Every recent standard-mode debate in your DB ended `max_rounds_reached`. *(Confirmed)*
3. **AB-03:** HITL **Override** feedback is stored but never sent to the moderator, so the human's direction has no effect on the decision. *(Code-verified)*
4. **AB-04:** HITL **Add Round** makes the approval panel disappear when the next pause arrives, and the debate hangs. *(Code-verified ordering)*
5. **AB-05:** `POST /debate/{id}/resume` on a HITL-paused debate stores `None` as the decision, which causes 500s. *(Confirmed at graph level)*
6. **AB-06:** Knowledge-base uploads are indexed under the **temp file name** (`tmpab12.pdf`), not the user's file name. *(Code-verified)*
7. **AB-07:** The tests are not hermetic. They pollute the dev DB (232 fixture rows found) and fail on a clean machine or in CI. *(Confirmed)*
8. **AB-08:** The default **OpenAI** (`gpt-5.5`) and **Anthropic** (`claude-opus-4-8`) models get a per-call `temperature` that the code's own comment says those APIs reject. *(Code-verified against langchain-openai source)*
9. **AB-09:** In Docker the LangGraph checkpoint DB is not on the volume, so HITL approve and resume break after a redeploy. *(Code-verified)*
10. **AB-10 / AB-11:** `/llm-settings` is global and unauthenticated (one user's API key gets used for everyone), and rate limits are shared by all users behind the Next.js proxy. *(Code-verified)*

---

## 2. Bug summary table

| ID | Sev | Area | Title | Evidence | Effort |
|---|---|---|---|---|---|
| AB-01 ✅ | High | Observability | Alembic `fileConfig()` disables all app loggers (incl. audit) | Confirmed | S |
| AB-02 ✅ | High | Consensus | Standard/Thorough consensus is practically unreachable | Confirmed | M–L |
| AB-03 ✅ | High | HITL | Override feedback never reaches the moderator | Code-verified | S |
| AB-04 ✅ | High | HITL / FE | "Add Round" clears the next approval request, so the debate hangs | Code-verified | M |
| AB-05 ✅ | High | HITL / API | `/resume` on a paused debate returns `None` decision, causing 500s and a poisoned cache | Confirmed | S |
| AB-06 ✅ | High | Knowledge base | Uploaded docs indexed under temp-file name | Code-verified | S |
| AB-07 ✅ | High | Tests | Tests use the real DB: they pollute it and fail on a clean checkout | Confirmed | S |
| AB-08 ✅ | High | LLM client | Per-call `temperature` sent to models that reject it | Code-verified | S |
| AB-09 🟨 | High | Docker | Checkpoint DB not on the persistent volume | Code-verified | S |
| AB-10 ✅ | High* | Security | Global, unauthenticated LLM switching; user keys shared server-wide | Code-verified | M |
| AB-11 ✅ | High* | Deploy | Rate limits keyed on the proxy IP, so all users share one bucket | Code-verified | M |
| AB-12 ✅ | Med | SSE / FE | Client heartbeat ignores server keep-alives; HITL waits disconnect | Code-verified | S |
| AB-13 ✅ | Med | FE errors | Structured errors render as `[object Object]`; LLM errors shown as "Backend unavailable" | Code-verified | S |
| AB-14 ✅ | Med | Errors | Raw provider errors (org id, JSON) shown to users; friendly mapping is dead code | Code-verified | S |
| AB-15 🟨 | Med | Reliability | Unbounded parallel LLM calls cause provider 429s; a moderator failure kills the debate | Confirmed | M |
| AB-16 ✅ | Med | API / proxy | Long synchronous endpoints exceed the proxy's 300 s timeout; no cancellation | Code-verified | L |
| AB-17 ✅ | Med | Concurrency | No guard against concurrent approve/resume; thread locks protect nothing | Code-verified | S |
| AB-18 ✅ | Med | Memory | In-memory debate/decision stores and KB cache grow forever | Code-verified | S |
| AB-19 ✅ | Med | Storage | Checkpoint DB never pruned (13 MB locally vs 3 MB main DB) | Confirmed | S |
| AB-20 ✅ | Med | Upgrades | Checkpoint deserialization of `DebateState` will be blocked by LangGraph; deps unpinned | Confirmed (warning) | S |
| AB-21 ✅ | Med | DB | SQLite without WAL / busy_timeout; event writer silently drops events on lock | Likely | S |
| AB-22 ✅ | Med | Performance | Blocking work on the event loop (PDF export, KB model load) | Code-verified | S |
| AB-23 ✅ | Med | Simulation | Mode's round count ignored; stability metrics always "Low"; risk-flag match exact | Code-verified | M |
| AB-24 ✅ | Med | History | Wrong round count, fake default status/reason, override shown as "Max Rounds" | Code-verified | S |
| AB-25 ✅ | Med | History FE | Filters/sorting apply only to the current page | Code-verified | S |
| AB-26 🟨 | Med | Analytics | Stale cache, mislabeled metrics, Custom counted as Standard, fake "template" stats | Code-verified | M |
| AB-27 🟨 | Med | Docker | Non-root user has `HOME=/nonexistent`, so the HF model cache fails and KB is off | Likely | S |
| AB-28 🟨 | Med | CI / deps | CI never runs tests; dependency drift; broken local venv | Confirmed | M |
| AB-29 ✅ | Med | Memory svc | Fire-and-forget memory tasks can be GC'd; memory uses a stale LLM client | Code-verified | S |
| AB-30 ✅ | Med | Cost | Token usage / cost undercounted after HITL approve or resume | Code-verified | S |
| AB-31 ✅ | Med | Security | KB upload reads the whole file into RAM before the size check | Code-verified | S |
| AB-32 ✅ | Low | FE | "At least 2 agents" counts the Moderator, so 1-agent debates are possible | Code-verified | S |
| AB-33 ✅ | Low | SSE | Stream stays open after replaying a terminal event; queue entry leak | Code-verified | S |
| AB-34 ✅ | Low | HITL / FE | Paused debates can't be cancelled; Home "Cancel" doesn't stop the backend run | Code-verified | S |
| AB-35 ✅ | Low | Schema | `add_round` can push `max_rounds` above the schema max (8), so the state can't be reloaded | Code-verified | S |
| AB-36 ✅ | Low | Config | `GROQ_API_KEY` mandatory even for other providers; health reports Groq only | Code-verified | S |
| AB-37 ✅ | Low | Registry | Per-agent Gemini override always fails (no key mapping) | Code-verified | S |
| AB-38 ✅ | Low | Config | DB paths relative to CWD (stale root `agentboard.db` exists) | Confirmed | S |
| AB-39 ✅ | Low | Logging | Log file naming/rotation: old files never pruned across restarts | Code-verified | S |
| AB-40 🟨 | Low | Docker | Healthcheck `start_period` too short for first-start model download | Likely | S |
| AB-41 ✅ | Low | Config | `.env.example` outdated (`MAX_DEBATE_ROUNDS=4`, missing vars) | Code-verified | S |
| AB-42 ✅ | Low | Tooling | `run_all.sh` points to a non-existent venv path | Code-verified | S |
| AB-43 ✅ | Low | Moderator | Moderator's `should_continue`/`agreement_score` ignored but shown; ignores per-agent config | Code-verified | S |
| AB-44 ✅ | Low | Feature gap | Ethics "VETO power" is prompt-only, never enforced or surfaced | Code-verified | M |
| AB-45 ✅ | Low | Dead code | `domain_focus`, `SECRET_KEY`, duplicate timeout constants unused | Code-verified | S |
| AB-46 ✅ | Low | Tools | Calculator `numexpr.evaluate` can resolve caller-frame variables | Code-verified | S |
| AB-47 ✅ | Low | CRUD | History search `LIKE` wildcards unescaped; `save_decision` overwrites `created_at` | Code-verified | S |
| AB-48 ✅ | Low | Consensus | Stale confidences of dropped agents; drift = 0.0 when the previous round is empty | Code-verified | S |
| AB-49 ✅ | Med | Tests (FE) | 16 of 70 Playwright e2e tests already fail on the untouched code (stale selectors/flows) | Confirmed | M |
| AB-50 ✅ | High | Checkpoints | Concurrent debates on a new checkpoint DB fail with "database is locked" | Confirmed | S |

\* High if the app is deployed for more than one user (you have EC2 deployment docs). For local single-user use it is Medium.

---

## 3. Detailed findings

### AB-01: Alembic `fileConfig()` disables every application logger · High · Confirmed

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `backend/alembic/env.py:29` (`fileConfig(config.config_file_name)`), called from `run_migrations()` at `backend/app/main.py:126`, which runs *after* `setup_logging()` at `main.py:112`.
- **Problem:** `logging.config.fileConfig()` defaults to `disable_existing_loggers=True`. Every module-level logger that already exists (`agentboard`, `agentboard.api`, `agentboard.db`, `agentboard.nodes`, `agentboard.audit`, `agentboard.services.llm_client`, `agentboard.memory`, …) is disabled. Only loggers created later (per-debate agent loggers, `agentboard.orchestrator`) still work. `alembic.ini` also re-configures the **root** logger.
- **Evidence:**
  - Experiment: before `run_migrations()` every logger had `disabled=False`; after it, all are `True`.
  - Your `backend/logs/agentboard_2026-08-05.log` and `…06-14.log` contain only `llm_call_*`, `tool_called`, `synthesis_complete`, `debate_started`, and `Logging initialized`. There is no `http_request_completed`, no `AgentBoard starting up`, no `audit_event`, no `background_debate_failed`, and no `db_persist_failed`.
- **Impact:** Production errors (failed debates, DB persist failures, LLM client errors) and all audit records are silently dropped. Request metrics are still collected, but the request log lines are gone.
- **Fix:**
  ```python
  # alembic/env.py
  if config.config_file_name is not None and config.attributes.get("configure_logger", True):
      fileConfig(config.config_file_name, disable_existing_loggers=False)

  # app/db/database.py  (inside run_migrations, before command.upgrade)
  alembic_cfg.attributes["configure_logger"] = False
  ```
- **Test:** After `run_migrations()`, assert `logging.getLogger("agentboard.api").disabled is False` and that a test log line reaches a handler.

### AB-02: Consensus is practically unreachable in Standard / Thorough mode · High · Confirmed

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `backend/app/orchestrator/nodes.py:404-409` (score formula), `backend/app/core/config.py:72` (`CONSENSUS_POSITION_WEIGHT=0.3`), `backend/app/schemas/api_models.py:31-32` (thresholds 0.75 / 0.85), `backend/app/services/consensus.py:203` (`count_open_disagreements`), `config.py:67` (`MAX_OPEN_DISAGREEMENTS_FOR_CONSENSUS=2`).
- **Problem:**
  - `agreement = 0.7 × mean_confidence + 0.3 × Jaccard(word sets)`. The Jaccard overlap between two different LLM paragraphs is typically 0.10–0.25, so even at confidence **1.0** the score tops out around 0.73–0.78.
  - The Standard threshold of 0.75 needs near-perfect confidence. The Thorough threshold of 0.85 is mathematically unreachable unless the overlap is at least 0.5.
  - The open-disagreement cap counts *unique critique points* with severity high or critical. One "high" critique with 3 bullet points (very common) already exceeds the limit of 2.
- **Evidence:** In your DB, all 8 recent `standard` debates (the ones with `mode` persisted) ended `max_rounds_reached`, with agreement 0.55–0.66 even at mean confidence 0.91. Only `quick` mode (threshold 0.60, no critiques) ever reached consensus.
- **Impact:**
  - "Consensus" is almost never reported.
  - Thorough always burns all 6 rounds (cost and time).
  - Analytics on termination reasons, and the HITL "reason", are meaningless.
  - The README promise of a "5-signal hybrid gate" does not hold in practice.
- **Fix (in order):**
  1. Compare each signal to its **own** calibrated threshold instead of blending confidence into "position agreement". For example: position overlap ≥ X, mean confidence ≥ Y, spread ≤ Z.
  2. Use semantic similarity (the `SemanticConsensusEngine`) whenever sentence-transformers is installed, with Jaccard only as a fallback. `SEMANTIC_CONSENSUS_ENABLED` is `False` by default (`config.py:103`).
  3. Count open disagreements per **critique** (critic→target pair) rather than per bullet point, and/or only count critiques the target did not address in its revision. Normalise by the number of agents.
  4. Write a small calibration script over stored `state_json` rows to choose thresholds, and add a regression test: "realistic agreeing positions reach consensus in standard mode; disagreeing positions don't".

### AB-03: HITL "Override" feedback is never used · High · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `nodes.py:606` sets `ds.human_feedback = feedback`. Nothing reads it: `grep human_feedback` finds only the schema, this assignment, and one test. The moderator's `_FINALIZE_TEMPLATE` (`moderator_agent.py:124`) and `_build_finalize_prompt` (`:240`) do not include it.
- **Impact:** The user writes "Use vendor B instead", the decision is generated exactly as before, and it is labelled `human_override`. This is misleading.
- **Fix:**
  - Add a "Human reviewer direction (must be honoured)" block to the finalize prompt when `state.human_feedback` is set.
  - Add a `human_feedback` field to `FinalDecision` and show it in the decision panel, Markdown, and PDF exports.
  - Validate that override feedback is non-empty, both in the UI (HITLPanel currently allows empty) and in `ApproveRequest`.
- **Test:** Spy on `ainvoke_structured` and assert the finalize prompt contains the feedback text.

### AB-04: "Add Round" makes the approval panel vanish, and the debate hangs · High · Code-verified (event ordering)

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `frontend/src/components/HITLPanel.tsx:35-36` (`await approveDebate(...)` then `onDone()`), `DebateStreamViewer.tsx` (`onDone` dispatches `clear_approval`), backend `routes.py` `approve_debate` (≈1183-1268).
- **Problem:**
  1. `POST /approve` runs the extra round **synchronously** inside the request.
  2. When it pauses again, the backend emits `approval_required` and flushes the SSE writer **before** returning the HTTP response.
  3. The browser therefore receives the *new* `approval_required` event first. Then the HTTP response arrives and `onDone()` → `clear_approval` wipes it.
  4. The panel disappears, and the debate sits in `awaiting_approval` with no UI to approve it.
  5. The modal (`fixed inset-0`) also hides the live round while the request is pending, and a long round can exceed the proxy's 300 s timeout (AB-16).
- **Fix:**
  - **Backend:** make approve asynchronous. Return `202 {status: "resuming"}` and run the graph in a background task, reusing the `_run_debate_background` + event-writer pattern from `start-async`. SSE then drives the UI.
  - **Frontend:** clear the approval optimistically when the user clicks, and restore it if the request fails. Or make `clear_approval` carry the `round_number` it answers and ignore stale clears.
  - **Frontend:** stop showing "Agents deliberating…" while `approvalRequired` is set.
- **Test:** Add an e2e test (Playwright mock) where the approve response arrives after a second `approval_required`. The panel must still be visible.

### AB-05: `/debate/{id}/resume` on a HITL-paused debate returns no decision · High · Confirmed

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `routes.py:873` (`final_state, decision = await graph.resume(thread_id)`), `routes.py:904` (`decision_store[thread_id] = decision`).
- **Evidence:** Experiment: running `DebateGraph.resume()` on a paused HITL thread returns `(status="awaiting_approval", decision=None)`.
- **Impact:** The route stores `None` in `decision_store` and calls `_persist_debate(state, None)` (which fails with a warning). It then returns `None` for `response_model=FinalDecision`, which is a 500. Afterwards, `GET /decision/{id}` returns `None` and the stream fast path crashes on `None.model_dump_json()` (`routes.py:569-570`).
- **Fix:**
  - If the state is `awaiting_approval`, reject with **409** (`use /debate/{id}/approve`).
  - Defensively, if `decision is None`, persist only the state and return a status payload.
  - Never put `None` in `decision_store`.
  - Also reject resume for `cancelled` debates unless "restart" is intended.

### AB-06: Knowledge-base documents indexed under the temp file name · High · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** Upload writes to a `NamedTemporaryFile` (`routes.py` ≈1448). `retriever.py:264` sets `doc_name = Path(file_path).name`, and `retriever.py:279` builds `{**metadata, "source": doc_name, ...}`, which **overwrites** the passed `{"source": file.filename}`.
- **Impact:**
  - The KB page lists documents as `tmpk2j3h4.pdf`.
  - Agents cite `[Source: tmpk2j3h4.pdf]`.
  - Re-uploading an edited version never purges the old chunks, because the "stale purge" matches on the temp name, so outdated content stays searchable.
  - Deleting by the real file name deletes 0 chunks.
- **Fix:**
  - Pass the display name explicitly (`kb.ingest(tmp_path, source_name=file.filename)`) and use it for the `source` metadata, the purge, and the IDs.
  - Sanitise the name (strip paths, cap the length).
  - Add a one-off re-index note for existing entries.
- **Test:** Upload `report.md` through the API; `/knowledge/documents` must list `report.md`. Re-upload changed content; the old chunks must be gone.

### AB-07: Tests are not hermetic, pollute the dev DB, and fail on a clean checkout · High · Confirmed

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `backend/tests/test_api.py`, `tests/test_contracts.py` (use the real `app` and `settings.DATABASE_URL="agentboard.db"` relative to CWD); `tests/conftest.py` has no DB fixture.
- **Evidence:**
  - On a fresh copy: **10 failed, 283 passed** with `no such table: decisions`.
  - Your dev DB contains **191** `converged` + **41** `error / no_checkpoint_for_resume` rows with the fixture query *"Should we expand into the Asian market in Q3?"*.
- **Impact:** History, analytics, and the "recent debates" rail show fake data. CI (once added) would fail. Developers get different results depending on the CWD.
- **Fix:**
  ```python
  # tests/conftest.py
  @pytest.fixture(autouse=True)
  def _isolated_db(tmp_path, monkeypatch):
      from app.core.config import settings
      monkeypatch.setattr(settings, "DATABASE_URL", str(tmp_path / "test.db"))
      monkeypatch.setattr(settings, "CHECKPOINT_DATABASE_URL", str(tmp_path / "ckpt.db"))
      from app.db.database import run_migrations
      run_migrations()
  ```
  Then clean the dev DB (see Appendix A.4; back it up first).

### AB-08: Per-call `temperature` is sent to models that reject it · High · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `backend/app/services/llm_client.py:170` (`self._llm.bind(temperature=temperature)` in `ainvoke_structured`), `:203` (`chat()` also binds `temperature` + `max_tokens`).
- **Problem:** `_sampling_kwargs()` carefully omits `temperature` at construction for `gpt-5*`, `claude-opus-4-7/4-8`, `claude-fable`, and `claude-mythos`, because (per the code comment) those APIs return 400. But every structured call re-adds it with `.bind()`. I checked the installed `langchain_openai` source: on the Chat Completions path, bound kwargs go straight into the payload (`{**self._default_params, **kwargs}`). Its gpt-5 temperature stripping only happens in the constructor validator and in the Responses-API builder. So `gpt-5.5` (the default `OPENAI_MODEL`) receives `temperature=0.3` on every agent call.
- **Impact:** Switching to the default OpenAI or Anthropic model likely makes every agent call fail. The agents are silently dropped (logged), then the moderator call fails and the debate errors. Confirm once with a real key.
- **Fix:** Centralise sampling: only bind `temperature` when `not model.startswith(_NO_TEMPERATURE_PREFIXES)`. Apply the same rule in `chat()`. Add a unit test that inspects `_get_request_payload` for these models (no `temperature` key).
- **Related:**
  - `with_retry(stop_after_attempt=max(1, max_retries))` means `max_retries=2` gives 2 attempts total (1 retry). Rename or add +1.
  - Every exception becomes `LLMResponseError`, so the `LLMRateLimitError` (429) handler in `main.py` is never used.

### AB-09: Docker doesn't persist the LangGraph checkpoint DB · High · Code-verified

> **Status: 🟨 Fixed (partly verified)** — see Fix progress table.

- **Where:** `backend/Dockerfile:63` and `docker-compose.yml:26` set only `DATABASE_URL=/data/...`. `CHECKPOINT_DATABASE_URL` keeps its default, the relative path `agentboard_checkpoints.db`, which resolves to `/app/agentboard_checkpoints.db` inside the container (not on the volume).
- **Impact:** After `docker compose up` recreates the container, every HITL-paused debate fails to approve and every resume fails ("No checkpoint found").
- **Fix:** Add `CHECKPOINT_DATABASE_URL=/data/agentboard_checkpoints.db` (and `HF_HOME`, see AB-27) to the Dockerfile and compose file. Better still, make all data paths absolute and derived from one `DATA_DIR` setting (see AB-38).

### AB-10: Global, unauthenticated LLM switching; user API keys shared server-wide · High (shared deploy) · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `routes.py:1608` `update_llm_settings` → `reset_llm_client()` replaces the **process-wide** singleton. `frontend/src/components/LLMSettingsPanel.tsx:90` stores keys in `localStorage`.
- **Impact:**
  - Any visitor can change the provider/model for **all** users.
  - A user's personal OpenAI/Anthropic/Gemini key becomes the key that pays for **everyone's** debates.
  - Keys in `localStorage` are readable by any XSS.
  - Other mutating endpoints (`DELETE /memory/{agent}`, `DELETE /knowledge/documents/...`, `/knowledge/upload`) also have no auth.
  - `SECRET_KEY` exists in settings but is unused (AB-45), which suggests an auth layer that doesn't exist.
- **Fix:**
  - **Short term:** protect admin/mutating endpoints with a server-side admin token (header checked against a setting), and hide the provider switch unless configured.
  - **Proper:** make provider/model a **per-debate** option in `DebateStartRequest`, using server-side keys. If BYOK is required, send the key per request, keep it only in that debate's memory, never make it global, and don't persist it in `localStorage` (use memory or `sessionStorage`).
  - Add a rate limit on `/llm-settings`.

### AB-11: Rate limits are keyed on the proxy IP, so every user shares one bucket · High (shared deploy) · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `backend/app/core/rate_limiter.py` (`key_func=get_remote_address` = `request.client.host`); `frontend/src/app/backend/[...path]/route.ts:54` sets `x-forwarded-for` to the incoming header or `"unknown"`.
- **Impact:** All browser traffic reaches FastAPI from the Next.js server's IP. `simulate`'s **2/hour** and `start`'s **30/minute** limits are therefore global, so one user can lock everyone out.
- **Fix:**
  - Put a reverse proxy (nginx/Caddy/ALB) in front that sets `X-Forwarded-For`, and forward it unchanged from the Next proxy (don't replace it with `"unknown"`).
  - Run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy-ip>`, or use a `key_func` that trusts the left-most XFF only when `request.client.host` is a trusted proxy.
  - Note: Next 15 route handlers no longer expose `req.ip`, so the client IP must come from the edge proxy.

### AB-12: The SSE client heartbeat ignores server keep-alives · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** Backend sends `": keep-alive"` comments every 20 s (`routes.py:677`). The frontend forces a reconnect after 60 s without a *named* event (`frontend/src/lib/api.ts:225`). `EventSource` never surfaces comment lines.
- **Impact:**
  - During a HITL pause (or any quiet phase over 60 s) the client reconnects every ~60 s.
  - `attempts` only resets on a real event, so after 10 tries (~13–15 min) the UI shows **"Stream connection lost"** while the debate is just waiting for approval.
  - Every reconnect also adds another `abort` listener to the same `AbortController` (`api.ts:306`).
- **Fix:**
  - Send a named heartbeat (`event: ping\ndata: {}\n\n`) and add `"ping"` to the listened events.
  - Reset `attempts` in `eventSource.onopen`.
  - Suspend the stale-timer while `approvalRequired` is set.
  - Register the abort listener once, outside `connect()`.

### AB-13: Error messages show `[object Object]`; LLM errors look like "Backend unavailable" · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `frontend/src/lib/api.ts:62-70`.
- **Problem:**
  - Backend 4xx errors are `{"detail": {"error": "...", "detail": "..."}}` (via `HTTPException(detail=ErrorResponse(...).model_dump())`), and `String(body.detail)` gives `"[object Object]"`. FastAPI 422s have `detail: [...]`, which gives the same result.
  - Status 502/503 from `LLMResponseError` / `LLMConnectionError` (backend up, LLM failed) is mapped to "Backend unavailable — please try again shortly."
- **Visible in:** the HITL panel (`approve_failed` 400), toasts on the home page, simulate, and the KB page.
- **Fix:** A single `extractErrorMessage(body)`: string → use it; object → `.detail ?? .error`; array → join `msg`. Branch on `body.error` (`llm_response_error`, `llm_rate_limit`, …) before the generic 5xx text.

### AB-14: Raw provider errors are leaked to the UI; the friendly mapping never matches · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `routes.py` background failure emits `{"error_type": "LLMResponseError", "detail": str(exc)}`. `debateStreamReducer.ts:244-251` searches for the class name **inside `detail`**, but it is in `error_type`.
- **Evidence:** Your logs show messages like `Error code: 429 … Rate limit reached for model openai/gpt-oss-120b in organization org_01kv… on tokens per minute`. This full text (including the org id) is what the user sees.
- **Fix:**
  - Map on `error_type`.
  - Backend: send a sanitised message plus a stable error code to clients, and log the full exception server-side. The same applies to `resume_failed` (`detail=f"Resume failed ({error_type}): {exc}"`) and the global LLM exception handlers in `main.py`.

### AB-15: Unbounded parallel LLM calls trigger provider 429s; a moderator failure kills the debate · Medium · Confirmed

> **Status: 🟨 Fixed (partly verified)** — see Fix progress table.

- **Where:** Critiques fan out N×(N−1) concurrent calls (`nodes.py:230`; 12 calls for 4 agents). Proposals and revisions add N each. Simulation multiplies this by `runs` (up to 5).
- **Evidence:**
  - `logs/agentboard_2026-08-05.log` has 10 `llm_call_failed` events from Groq TPM limits within one debate.
  - The DB has **13** debates ending `error:LLMResponseError`. Agent failures are swallowed, so these errors come from the uncaught moderator `synthesize`/`finalize` calls, which fail after all the spending.
- **Fix:**
  - A per-provider `asyncio.Semaphore` (`LLM_MAX_CONCURRENCY`, e.g. 4).
  - A retry policy that honours `Retry-After` on 429 with a longer max wait.
  - A bigger retry budget for the moderator, plus a deterministic fallback synthesis so one moderator failure doesn't discard the whole debate.
  - Surface "N agents rate-limited" to the UI.

### AB-16: Long synchronous endpoints hit the proxy's 300 s timeout; no cancellation · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `POST /debate/simulate` (2–5 full debates), `POST /debate/{id}/approve` (rest of the debate), `POST /debate/{id}/resume`, `POST /debate/start` (sync). The Next proxy uses `fetch` with default undici timeouts (`headersTimeout` 300 s) and no `signal: req.signal` (`route.ts:80`).
- **Impact:** The user sees a 502 "Backend unavailable" while the backend keeps running and spending tokens. Closing the tab doesn't stop the work.
- **Fix:**
  - Job pattern: return `202 {job_id}` and stream progress over SSE or poll. Simulation results should also be persisted so they're not lost.
  - Forward `req.signal` in the proxy.
  - For SSE responses only, use an undici `Agent` with `bodyTimeout: 0`.

### AB-17: No concurrency guard on approve/resume; thread locks protect nothing · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `routes.py` `approve_debate`/`resume_debate`. `get_thread_lock` (`dependencies.py:26`) is used only around single dict assignments (`routes.py:241, 251`), which are already atomic in asyncio.
- **Impact:** Two approvals (two tabs, or a retry after a proxy timeout) both pass the checkpoint check and both resume the graph. The result is duplicated rounds, two decisions, and double cost.
- **Fix:** Track in-flight threads (a set or a lock held for the whole approve/resume). Return 409 if the debate is already running, and reuse the same guard for cancel.

### AB-18: In-memory stores grow without bound · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `dependencies.py:18-19` (`_debate_store`, `_decision_store` keep every state and decision, with the full trace, for the life of the process). `_cleanup_terminal_thread_state` (`routes.py:202`) only drops queues, replays, and locks. `KnowledgeBase._retrieve_cache` (`retriever.py:313`) caches every query forever.
- **Fix:** After persisting a terminal debate, evict it (the DB is the source of truth), or use a bounded TTL/LRU cache. Bound the retrieve cache with an LRU.

### AB-19: The checkpoint DB is never pruned · Medium · Confirmed

> **Status: ✅ Fixed** — see Fix progress table.

- **Evidence:** `backend/agentboard_checkpoints.db` is **13 MB** vs 3 MB for the main DB. `cleanup_old_debates` (`crud.py`) ignores it. Simulations and test runs also write checkpoints.
- **Fix:**
  - On a terminal status (not `awaiting_approval`), delete the thread's checkpoints (`checkpointer.adelete_thread(thread_id)`).
  - Include checkpoints in the TTL cleanup.
  - Use an in-memory saver for simulations.
  - Run `VACUUM` occasionally.

### AB-20: Checkpoint deserialization will be blocked on upgrade, and deps are unpinned · Medium · Confirmed (warning)

> **Status: ✅ Fixed** — see Fix progress table.

- **Evidence:** Running the graph prints *"Deserializing unregistered type app.schemas.state.DebateState from checkpoint. This will be blocked in a future version. Add to allowed_msgpack_modules…"*. `requirements.txt` has `langgraph>=0.2.0`, `langchain-core>=0.3.0`, `langgraph-checkpoint-sqlite>=3.0.0` (unpinned).
- **Impact:** A future Docker build can silently pick up a LangGraph version that refuses to load checkpoints. HITL approve and resume would then break for every debate.
- **Fix:** Configure the checkpoint serializer's `allowed_msgpack_modules` with the app's Pydantic models (`DebateState`, `DebateRound`, `AgentResponse`, `CritiqueResponse`, `FinalDecision`, …), or keep `debate_state` in graph state as a plain dict. Pin versions with a lock file (AB-28).

### AB-21: SQLite has no WAL / busy_timeout, and events can be lost on lock · Medium · Likely

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** Every request opens a fresh `aiosqlite.connect()` (default rollback journal, 5 s timeout). Each running debate holds a writer connection (`_event_writer_loop`) and writes state snapshots frequently.
- **Impact:** Under several concurrent debates, `database is locked` can occur. The writer logs a warning and **broadcasts the event without persisting it**, so reconnect replay has gaps.
- **Fix:** Run `PRAGMA journal_mode=WAL` once at startup and set `busy_timeout` on every connection (a small connection helper). Consider a single shared writer connection.

### AB-22: Blocking work on the event loop · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:**
  - `routes.py:1138` calls WeasyPrint `render_pdf()` synchronously inside an async route. Every SSE stream freezes during a PDF export.
  - `KnowledgeBase.is_available` (`retriever.py:234`) is a *property that loads Chroma and the sentence-transformer synchronously*. `main.py:147` calls it **before** `await kb.warm()`, so the "background warm" never helps and startup blocks. When the dependencies are missing, every call retries the import.
- **Fix:**
  - `await asyncio.to_thread(render_pdf, decision)`.
  - Make `is_available` a cheap cached flag (checks the import once), keep the heavy init in `warm()`, and start `warm()` as a background task.

### AB-23: Simulation: mode rounds ignored, metrics miscalibrated · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `api_models.py:163` (`max_rounds: int = Field(default=3)`, always set, so it always overrides the mode preset). `simulation.py:223` (stability from word-Jaccard with thresholds 0.80/0.55). `simulation.py:212` (exact-string risk-flag matching).
- **Impact:**
  - "Quick" and "Thorough" simulations both run 3 rounds.
  - Two LLM-written decisions almost never reach a Jaccard of 0.55, so the rating is almost always **Low**.
  - "Stable risk flags" is almost always empty because phrasings differ.
  - `confidence_variance` is actually the standard deviation of agreement scores.
- **Fix:**
  - Make `max_rounds` optional (`None` means use the mode preset).
  - Use embedding cosine similarity for consistency, and semantic clustering or fuzzy matching for flags.
  - Rename the field, or compute the real variance.
  - Expose agents, domain pack, KB, and memory in the simulate UI (the backend already supports them).

### AB-24: History shows the wrong round count and invented defaults · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `crud.py:165-168`: `"total_rounds": r[5] or 4` uses **max_rounds** (`current_round` is selected but unused). It also falls back to `status="converged"` and `termination_reason="consensus_reached"` when the values are missing. `GET /debate/{id}` (`routes.py:737`) and the approve response (`:1243`) also report `total_rounds = max_rounds`.
- **Impact:** A debate that stopped in round 1 shows "2 rounds". HITL `human_override` decisions show a "Max Rounds" badge (`history/page.tsx` only knows two reasons).
- **Fix:** Return `current_round` as rounds run (and `max_rounds` separately), drop the fake defaults, and add a badge for `human_override`.

### AB-25: History filters and sorting apply only to the current page · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `frontend/src/app/history/page.tsx:81-85` filters and sorts the 20 items of the current page, while pagination and ordering are server-side (`created_at DESC`).
- **Impact:** "Oldest first" is not the oldest overall, "Highest agreement" is per-page only, and filtered pages can look empty while "N total" is unchanged. Search requests can also resolve out of order (no abort), so stale results may overwrite fresh ones.
- **Fix:** Add `sort` and `termination_reason` query params to `GET /history` (whitelisted), and abort in-flight requests on new input.

### AB-26: Analytics accuracy · Medium · Code-verified

> **Status: 🟨 Fixed except (f)**, which is deferred with measurements; see Fix progress table.

- **Problems:**
  - **(a)** The 5-minute cache (`api/analytics.py`) is never invalidated when a debate completes or is evaluated.
  - **(b)** `avg_rounds_to_consensus` averages *all* completed debates, including `max_rounds_reached`.
  - **(c)** The "agreement matrix" only counts co-occurring confidence above 0.7 and is asymmetric (`both / a_debates`).
  - **(d)** The UI sends **Custom** as `mode: "standard"` (`DebateInput.tsx:129`), so the mode breakdown is wrong.
  - **(e)** `scores_by_template` reads `state.template_id`, which doesn't exist, so it is really domain-pack stats.
  - **(f)** Every analytics call loads and parses every `state_json` blob (O(N) memory and CPU).
  - **(g)** The "Debates per day (last 30 days)" label ignores the selected range.
- **Fix:**
  - Invalidate the cache in `_persist_debate` and the evaluate endpoint.
  - Rename the metric or filter to `consensus_reached`.
  - Compute agreement from positions (semantic similarity), or rename the matrix to "co-confidence".
  - Send `mode: "custom"` (extend `DebateMode`).
  - Persist `template_id` when a template is used.
  - Store the needed aggregates in columns at write time.
  - Fix the label.

### AB-27: In Docker, the non-root user can't write the model cache, so KB is silently off · Medium · Likely

> **Status: 🟨 Fixed (partly verified)** — see Fix progress table.

- **Where:** `backend/Dockerfile:68` creates `appuser` with `adduser --system` (on Debian, `HOME=/nonexistent`, not created). sentence-transformers / Hugging Face writes to `~/.cache/huggingface`. `KnowledgeBase.is_available` swallows **all** exceptions, so the KB (and semantic consensus) just report "unavailable".
- **Verify:** `docker run --rm <image> python -c "from sentence_transformers import SentenceTransformer as S; S('all-MiniLM-L6-v2')"`.
- **Fix:** Set `ENV HF_HOME=/data/hf-cache` (on the volume) or pre-download the model at build time into a readable path. Log the real exception in `is_available`.

### AB-28: CI never runs tests; dependency drift; broken local venv · Medium · Confirmed

> **Status: 🟨 Fixed (partly verified)** — see Fix progress table.

- **Problems:**
  - `.github/workflows/docker-publish.yml` only builds and pushes images (`latest` on main), so failing code ships.
  - `requirements.txt` pins `fastapi==0.115.0` and `pydantic==2.9.0`, but your venv has fastapi 0.135.2, pydantic 2.13.4, and starlette 1.0.0. LangChain and LangGraph are unpinned.
  - In the local venv, `langchain_openai` and `langchain_anthropic` **cannot be imported** (native modules for `tiktoken` / `jiter` are missing), so switching to OpenAI/Anthropic fails locally.
  - `chromadb` and `sentence-transformers` are not installed locally, so the KB is disabled.
  - `sentence-transformers` pulls in CUDA `torch`, which makes the Docker image several GB.
- **Fix:**
  - Add a `test` job (backend pytest with the isolated DB from AB-07, ruff, mypy; frontend `npm run verify`) as `needs:` for the build jobs.
  - Generate a lock file (pip-tools / uv) and build from it.
  - Install CPU-only torch (`--index-url https://download.pytorch.org/whl/cpu`).
  - Recreate the local venv from the lock file.

### AB-29: Memory-save tasks can be garbage-collected, and memory uses a stale LLM client · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `nodes.py:784` uses `asyncio.create_task(memory_store.save_memory(...))` without keeping a reference (asyncio documents that such tasks can disappear mid-flight). `main.py:153` gives the memory store the **startup** LLM client, so after `/llm-settings` switches provider, memory summaries still use the old provider and key.
- **Fix:** Keep tasks in a module-level set and discard them on completion (or await them in the background runner after the decision). Resolve the LLM client at call time (`get_llm_client()`), not at startup.

### AB-30: Token usage and cost are undercounted after HITL or resume · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `debate_graph.py` `_ainvoke_with_usage` measures only the current `ainvoke`. For `approve()`/`resume()`, `decision.token_usage` and `estimated_cost_usd` cover only the post-pause segment.
- **Fix:** Accumulate usage in `DebateState` (persisted) per segment and attach the total.

### AB-31: KB upload reads the whole file into memory before checking the size · Medium · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `routes.py:1440` (`contents = await file.read()` then compare to `KB_MAX_FILE_MB`).
- **Impact:** A multi-GB upload is fully buffered first, which can exhaust memory.
- **Fix:** Reject on `Content-Length` early, read in chunks with a running cap, and set body limits at the proxy.

### AB-32: "At least 2 agents" counts the Moderator · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `frontend/src/app/page.tsx:142` (`if (next.size <= 2) return prev;`). The set includes `Moderator`.
- **Impact:** A user can run Moderator plus one agent: no critiques, and "agreement" equals one agent's self-confidence.
- **Fix:** Count non-moderator agents (at least 2) in the UI, and validate in `DebateStartRequest` / `_resolve_active_agents`.

### AB-33: The stream stays open after replaying a terminal event · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `routes.py:641-663`. The comment says "don't fall into the live-queue loop", but there is no `return` when `replayed_terminal` is `True`. `all_queues.setdefault()` also re-creates entries for threads that were already cleaned up.
- **Fix:** `if replayed_terminal: return`, and don't register a queue for terminal threads.

### AB-34: Paused debates can't be cancelled; Home "Cancel" doesn't stop the backend · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Problems:**
  - `POST /cancel` returns 409 for `awaiting_approval` (no background task), and the HITL panel has no "Reject/Cancel" option, so paused debates stay pending forever.
  - The Home page "Cancel" only aborts the client `fetch`. If `start-async` already reached the server, the debate runs anyway.
  - The "Stop debate" button stays in "Stopping…" if cancel fails.
- **Fix:**
  - Allow cancelling `awaiting_approval` (set `cancelled`, delete checkpoints) and add a "Reject" action to the panel.
  - On Home cancel, call `/cancel` if a `thread_id` was returned.
  - Reset `cancelling` on failure.
- **Also:** there is no UI for `POST /resume`. Errored debates ("recovery_required_after_restart") have no recovery path. Add a "Resume" button.

### AB-35: `add_round` can exceed the schema max of 8, so the state can't be reloaded · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `nodes.py:609` (`ds.max_rounds += 1`, no validation). `DebateState.max_rounds` has `le=8`.
- **Impact:** After the cap is passed, `DebateState.model_validate_json` (status after restart, recovery) raises, which gives a 500.
- **Fix:** Reject `add_round` at the cap (and hide the button), or validate on assignment.

### AB-36: `GROQ_API_KEY` is mandatory for every provider · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `config.py:21` (`GROQ_API_KEY: str`, required). `/health` reports only `groq_configured`.
- **Fix:** Make it optional and validate the key of the *active* provider at startup. Report `{provider, configured}` in `/health`.

### AB-37: Per-agent Gemini override always fails · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `backend/app/agents/registry.py:155-160` (the `api_key_map` has no `"gemini"`).
- **Fix:** Add Gemini, and share one provider→key map with `llm_client.get_llm_client()`.

### AB-38: DB paths depend on the current working directory · Low · Confirmed

> **Status: ✅ Fixed** — see Fix progress table.

- **Evidence:** A stale, pre-Alembic `agentboard.db` (2 tables, 0 rows) exists at the repo root, next to the real `backend/agentboard.db`.
- **Also:** `aiosqlite.connect(settings.DATABASE_URL)` treats `sqlite:///x.db` as a literal file name, while `alembic/env.py` strips the prefix. The two disagree if the URL form is ever used.
- **Fix:** Resolve relative paths against the backend directory (or one `DATA_DIR`), accept a single format, and delete the stale root DB.

### AB-39: Log rotation naming and retention · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `backend/app/core/logging_config.py:97-106`. The base file name contains the startup date, and `TimedRotatingFileHandler` appends a second date suffix. `backupCount` only prunes files that match the *current* base name, so files from earlier restarts are never deleted.
- **Fix:** Use a fixed base name (`agentboard.log`) with `suffix="%Y-%m-%d"`.

### AB-40: The Docker healthcheck is too short for the first start · Low · Likely

> **Status: 🟨 Fixed (partly verified)** — see Fix progress table.

- **Where:** `backend/Dockerfile:76` and `docker-compose.yml:35` (`start_period: 15s`). The first start downloads the embedding model inside the lifespan (AB-22). The frontend uses `depends_on: condition: service_healthy` (`docker-compose.yml:52`).
- **Fix:** Load the model in the background (AB-22) and/or raise `start_period`.

### AB-41: `.env.example` is outdated · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- `MAX_DEBATE_ROUNDS=4` (line 3) contradicts the code default of 2, which config comments say should match the Standard preset.
- Missing: `LLM_PROVIDER`, `OPENAI_*`, `ANTHROPIC_*`, `GEMINI_*`, `CHECKPOINT_DATABASE_URL`, `CORS_ORIGINS`, `RATE_LIMIT_PER_MINUTE`, `KB_*`, `HITL_ENABLED`, `SEMANTIC_CONSENSUS_ENABLED`, `LANGSMITH_*`.

### AB-42: `run_all.sh` uses the wrong venv path · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `run_all.sh:24` runs `./venv/Scripts/python` from inside `backend/`, but the venv is at the repo root, and `Scripts/` is the Windows layout inside a bash script.

### AB-43: The moderator's per-round outputs are ignored but displayed · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- The synthesis prompt tells the LLM to set `should_continue=false` at ≥ 0.75 and to produce an `agreement_score` (`moderator_agent.py:120`), but the gate uses neither.
- The UI receives `should_continue` in the `synthesis` event, which can contradict the real routing.
- `ModeratorAgent.synthesize`/`finalize` call the LLM directly and ignore the registry's per-agent `temperature`/`max_retries`, and skip `_call_structured` logging.
- **Fix:** Either use the moderator's signal as one gate input, or remove it from the prompt and the event. Route moderator calls through `_call_structured`.

### AB-44: Ethics "VETO power" is prompt-only · Low (feature gap) · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- The README advertises a veto, but no structured `veto` field exists, the gate ignores it, and the decision doesn't surface it.
- **Fix:** Add an optional `veto: bool` and `veto_reason` to the Ethics-class output schema. The gate blocks consensus while a veto stands, and `FinalDecision` carries `vetoes`.

### AB-45: Dead or misleading configuration and code · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- `DomainPack.domain_focus` (documented as "injected into system prompts") is never used.
- `SECRET_KEY` is never used.
- `nodes.py:47-51` defines `_DRIFT_EARLY_STOP_THRESHOLD` and `_PROPOSAL/_CRITIQUE/_REVISION_TIMEOUT`, which duplicate settings.
- The comment in the frontend Dockerfile still mentions "rewrites".

### AB-46: Calculator tool can resolve caller-frame names · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- **Where:** `backend/app/agents/tools.py:44-47`. Letters are allowed, and `numexpr.evaluate()` looks up unknown names in the calling frame. The tool is not enabled for any agent by default.
- **Fix:** `numexpr.evaluate(expr, local_dict={}, global_dict={})` and a tighter character whitelist.

### AB-47: CRUD details · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- History search uses `LIKE '%q%'` without escaping, so `%` and `_` in the search text act as wildcards (`crud.py:126`). Use `ESCAPE`.
- `save_decision` overwrites `created_at` on conflict (`crud.py:79`), so a re-save moves the debate in history ordering. Keep the original.
- The `agent_memory` queries use `COLLATE NOCASE`, so the `(agent_name, created_at)` index isn't used. Normalise the name instead.

### AB-48: Consensus-signal edge cases · Low · Code-verified

> **Status: ✅ Fixed** — see Fix progress table.

- `ds.confidence_scores` keeps the last value of agents that dropped out of later rounds (timeout or 429). Those stale values still feed `confidence_converged`.
- `detect_position_drift` returns **0.0** when the previous round is empty or shares no agents. 0.0 is below 0.05, so "confidence converged" becomes `True` spuriously.
- **Fix:** Rebuild `confidence_scores` from the current round only, and return `None` (not 0.0) when drift can't be measured.

### AB-49: The Playwright e2e suite is stale — 16 tests fail on the original code · Medium · Confirmed

> **Status: ✅ Fixed** — see Fix progress table.

*Found while verifying AB-04 (not part of the original review).*

- **Evidence:** running `npx playwright test` with the frontend source temporarily reverted to `HEAD` gives **16 failed / 54 passed**; the same 16 fail with the fixes applied (plus the new HITL test passing). Failing areas: home page (title, template browser/search/prefill), simulation page (5 tests), debate page banners and query banner (4), SSE reconnect badges (2), history "View" link (1).
- **Impact:** the e2e suite can't act as a regression gate — real UI regressions in those flows would go unnoticed.
- **Fix:** update the stale selectors/expectations to the current UI (or fix the UI where the test reveals a real problem), then add `npm run e2e` to CI.

### AB-50: Concurrent debates on a fresh checkpoint DB fail with "database is locked" · High · Confirmed

> **Status: ✅ Fixed** — see Fix progress table.

*Found while verifying AB-19 (a flaky simulation test), not part of the original review.*

- **Where:** every LangGraph run opens its own connection to the checkpoint file and runs `AsyncSqliteSaver.setup()` (`PRAGMA journal_mode=WAL` + `CREATE TABLE …`).
- **Evidence:** on a brand-new checkpoint file, 12 of 60 concurrent debate runs failed with `OperationalError: database is locked` inside `setup()`'s `executescript`; on an already-initialised file 0 of 60 failed. Reproduced with deletion of checkpoints disabled, so it predates the AB-19 change.
- **Impact:** the parallel runs of a simulation, or the first debates several users start after a fresh deploy / new Docker volume, fail outright.
- **Fix:** create the checkpoint schema once per database path, serialised process-wide, before any connection's own setup.

---

## 4. Improvements (not bugs, but worth planning)

**Architecture and scalability**
- All live debate state lives in process memory (`--workers 1` is mandatory). Move run state to the DB or Redis and use a job queue (arq, Celery, or RQ) for debates, approvals, simulations, and evaluations. That enables multiple workers and safe restarts.
- The orchestrator relies on LangGraph passing the **same** `DebateState` object to nodes and back to the caller (verified: in-place mutation is what keeps `debate_store` live, and what makes the HITL checkpoint show `awaiting_approval`). Treat state as immutable per node (return copies) and read status from `graph.aget_state()` / pending interrupts instead.

**Debate quality**
- Retrieve KB context **once per debate** (or per round) and share it, rather than having every agent re-query the KB in every phase.
- Agent memory injects the 5 most recent lessons regardless of topic. Retrieve memories by **similarity to the current query**, and cap or decay old lessons.
- Delimit untrusted content (KB chunks, web search results) in prompts as quoted data to reduce prompt-injection risk.
- The evaluator uses the same model as the debaters (self-grading bias). Allow a separate judge model.

**Reliability and UX**
- A "Resume" button for errored or interrupted debates. A "Reject/Cancel" action in the HITL panel. Show the human override text in the decision.
- Show which agents were rate-limited or timed out (the `degraded` / `missing_agents` fields already exist).
- Persist simulation results and evaluations, and link them from History.

**Observability**
- Prometheus-style `/metrics` (current metrics are a JSON snapshot in process memory). Alerts on `debate.failed_async`.
- Stable error codes end-to-end (backend → SSE → UI).

**Testing**
- E2E tests for HITL (approve / override / add_round with a second pause), reconnect during a quiet phase, and cancellation.
- Gate calibration tests with realistic agent texts (see AB-02).
- Contract tests that keep `frontend/src/lib/types.ts` in sync with the Pydantic models (e.g. generate TS types from OpenAPI).

---

## 5. Fix plan (phased)

> Each phase ends with: backend `pytest` green (with the isolated DB), frontend `npm run verify` green, and a manual smoke test (start a debate, stream it, finish, view in History, export).

### Phase 0: Stop the bleeding (~½ day)
| Order | ID | Task | Done when |
|---|---|---|---|
| 1 | AB-07 | Autouse isolated-DB fixture; clean polluted rows (Appendix A.4) | Fresh clone: 293/293 pass; dev DB untouched by tests |
| 2 | AB-01 | Stop Alembic from disabling loggers | Startup log shows `Database migrations applied`, `AgentBoard starting up`, and `http_request_completed` |
| 3 | AB-09 | `CHECKPOINT_DATABASE_URL=/data/...` in Dockerfile and compose | HITL pause survives `docker compose up --force-recreate` |
| 4 | AB-41, AB-42 | Refresh `.env.example`; fix `run_all.sh` | New dev can start from the docs alone |
| 5 | AB-28 (part) | CI `test` job gating image builds | PR shows test + lint + typecheck checks |

### Phase 1: Core correctness (~1.5–2 days)
| Order | ID | Task |
|---|---|---|
| 1 | AB-02 | Recalibrate the consensus gate (per-signal thresholds, semantic similarity, critique-level disagreement count) plus a calibration script and regression tests |
| 2 | AB-03 | Feed `human_feedback` into finalize; add `FinalDecision.human_feedback`; show it in the UI and exports |
| 3 | AB-05 | Guard `/resume` against `awaiting_approval`; never store a `None` decision |
| 4 | AB-06 | Use the original file name as the KB `source`; re-index note |
| 5 | AB-08 | Model-aware sampling params (no per-call temperature for gpt-5 / opus-4.7+); fix retry count naming |
| 6 | AB-24, AB-48 | History round count and defaults; consensus edge cases |

### Phase 2: HITL and streaming reliability (~2 days)
| Order | ID | Task |
|---|---|---|
| 1 | AB-04, AB-16 | Async approve (202 + background runner + SSE); optimistic or round-scoped `clear_approval`; job pattern for simulate |
| 2 | AB-17 | In-flight guard for approve / resume / cancel |
| 3 | AB-12, AB-33 | Named heartbeat event and `onopen` reset; close the stream after a replayed terminal event |
| 4 | AB-13, AB-14 | Unified error parsing in the FE; sanitised error codes from the BE |
| 5 | AB-15 | Per-provider concurrency limit, 429-aware retry, moderator fallback |
| 6 | AB-34, AB-35 | Cancel / reject paused debates; "Resume" button; `add_round` cap |

### Phase 3: Security and deployment (~1.5–2 days)
| Order | ID | Task |
|---|---|---|
| 1 | AB-10 | Admin token for mutating/admin endpoints; per-debate provider selection; stop global BYOK and `localStorage` keys |
| 2 | AB-11 | Edge proxy with `X-Forwarded-For`; trusted-proxy key function; forward the header unchanged |
| 3 | AB-31 | Streaming upload size cap |
| 4 | AB-27, AB-40 | `HF_HOME` on the volume / pre-baked model; background warm; healthcheck timing |
| 5 | AB-20, AB-28 | Serializer allow-list; lock file; CPU torch; rebuild venv |
| 6 | AB-21, AB-38 | WAL + busy_timeout; absolute data paths from `DATA_DIR` |

### Phase 4: Resource hygiene and data quality (~1–1.5 days)
| Order | ID | Task |
|---|---|---|
| 1 | AB-18, AB-19 | Evict terminal debates from memory; LRU KB cache; prune checkpoints on terminal status and in TTL cleanup |
| 2 | AB-22 | PDF export in a thread; cheap `is_available` |
| 3 | AB-23 | Simulation: optional `max_rounds`; semantic consistency; fuzzy flags; full options in UI |
| 4 | AB-25, AB-26 | Server-side history sort/filter; analytics cache invalidation and metric fixes; Custom mode persisted |
| 5 | AB-29, AB-30 | Keep memory-task references and use the current LLM client; cumulative token usage |

### Phase 5: Backlog (cleanup and features)
AB-32, AB-36, AB-37, AB-39, AB-43, AB-44, AB-45, AB-46, AB-47, plus the items in section 4.

---

## 6. Regression tests to add (minimum set)

| Test | Covers |
|---|---|
| Loggers stay enabled after `run_migrations()` | AB-01 |
| Gate: realistic agreeing positions → `consensus_reached` in standard mode; disagreeing → `max_rounds_reached` | AB-02 |
| Finalize prompt contains override feedback | AB-03 |
| E2E: add_round → second `approval_required` arrives before the HTTP response → panel still visible | AB-04 |
| `/resume` on `awaiting_approval` → 409; `decision_store` never holds `None` | AB-05 |
| Upload `report.md` → listed as `report.md`; re-upload replaces chunks | AB-06 |
| Test session never touches `backend/agentboard.db` (assert on the file's mtime) | AB-07 |
| `_get_request_payload` for `gpt-5.5` has no `temperature` | AB-08 |
| Client receives `ping` events; no reconnects during a 3-minute idle | AB-12 |
| `ApiError` message for nested `detail` object / 422 list | AB-13 |
| Two concurrent approves → one 200/202, one 409 | AB-17 |
| History item `total_rounds == current_round` | AB-24 |

---

## Appendix A: Evidence and reproduction

### A.1 Logger disabling (AB-01)
```text
before: {'agentboard': False, 'agentboard.api': False, 'agentboard.db': False, 'agentboard.nodes': False, 'agentboard.audit': False, 'agentboard.services.llm_client': False}
after : {'agentboard': True,  'agentboard.api': True,  'agentboard.db': True,  'agentboard.nodes': True,  'agentboard.audit': True,  'agentboard.services.llm_client': True}
```
Log files only contain loggers created *after* startup (`agentboard.agents.*`, `agentboard.orchestrator`) plus `Logging initialized`.

### A.2 Consensus outcomes in `backend/agentboard.db` (AB-02, AB-15)
```text
status / termination_reason            count
converged / None                       191   ← test fixtures (AB-07)
error / no_checkpoint_for_resume        41   ← test fixtures (AB-07)
error / error:LLMResponseError          13   ← moderator failures (AB-15)
converged / consensus_reached           10   ← legacy (mode=None) + 2 quick
max_rounds_reached                       9   ← all 8 'standard' debates + 1 legacy
standard-mode agreement scores: 0.551, 0.561, 0.585, 0.589, 0.590, 0.599, 0.654, 0.656  (threshold 0.75)
```

### A.3 HITL experiment (AB-05, AB-20, AB-03)
Fake LLM, real LangGraph 1.1.3 + AsyncSqliteSaver in a temp dir:
```text
run(hitl_mode=True)              -> status=awaiting_approval, decision=None
checkpoint debate_state.status   =  awaiting_approval
resume() while paused            -> status=awaiting_approval, decision is None: True   ← AB-05
approve(action="override", feedback="Use vendor B instead")
                                 -> converged, human_override, decision: "Proceed"     ← feedback not in prompt (AB-03)
warning: "Deserializing unregistered type app.schemas.state.DebateState from checkpoint.
          This will be blocked in a future version."                                   ← AB-20
```

### A.4 Cleaning the test rows out of the dev DB (AB-07)
Back up `backend/agentboard.db` first, then preview:
```sql
SELECT status, termination_reason, COUNT(*)
FROM debates
WHERE user_query = 'Should we expand into the Asian market in Q3?'
GROUP BY 1, 2;          -- expect 191 converged + 41 error rows
```
If the preview only shows fixture rows, delete:
```sql
DELETE FROM debate_events WHERE thread_id IN (SELECT thread_id FROM debates WHERE user_query = 'Should we expand into the Asian market in Q3?');
DELETE FROM decisions     WHERE thread_id IN (SELECT thread_id FROM debates WHERE user_query = 'Should we expand into the Asian market in Q3?');
DELETE FROM debates       WHERE user_query = 'Should we expand into the Asian market in Q3?';
VACUUM;
```

### A.5 Test run on a clean copy (AB-07)
```text
10 failed, 283 passed
FAILED tests/test_api.py::TestGetDebateStatus::* (2), TestGetDecision::* (2), TestResumeDebate::* (4)
FAILED tests/test_contracts.py::TestHistoryContract::* (2)
→ sqlite3.OperationalError: no such table: decisions
```

### A.6 Library check for AB-08
`venv/Lib/site-packages/langchain_openai/chat_models/base.py`:
- `_get_request_payload` builds `payload = {**self._default_params, **kwargs}`, so bound `temperature` is passed unchanged on the Chat Completions path.
- gpt-5 temperature stripping exists only in the constructor validator (`values.pop("temperature")`) and in `_construct_responses_api_payload`.

---

## Appendix B: Checked and found NOT to be bugs

These were investigated so nobody needs to re-check them:

- **Error/cancel paths overwriting rounds with a stale snapshot.** Not a bug. The graph mutates the same `DebateState` object passed in (`final is initial_state → True`), so `debate_store` and the persisted snapshot are live. This is still fragile (see section 4).
- **KB / memory used after approve even when disabled.** Not a bug. Agents check `state.use_knowledge_base` / `state.enable_agent_memory`, and finalize checks `ds.enable_agent_memory`.
- **Approve losing the selected agents.** Not a bug. `approve()`/`resume()` re-read `selected_agents` from the checkpoint and reconfigure the participants.
- **HITL approve flow.** Works end-to-end with the currently installed LangGraph 1.1.3. The overall flow is still fragile; see AB-04, AB-05, AB-17, and AB-20.
- **Prompt-template brace injection.** Not an issue. User text is substituted as a value into `PromptTemplate` / `ChatPromptTemplate`, not parsed as a template.
- **Markdown XSS.** `react-markdown` is used without `rehype-raw`, so raw HTML is not rendered.

---

*Note: the repository `.gitignore` contains `*docs`, so this file (and everything under `docs/`) is not tracked by git.*
