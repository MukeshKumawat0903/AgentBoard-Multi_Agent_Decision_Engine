# Pages & Routing

The frontend uses the **Next.js App Router** with file-system routing: **eight** pages, a runtime API proxy route, a global error boundary, a debate-page error boundary and a 404 page.

---

## Route Map

| Route | File | Component | Type |
|---|---|---|---|
| `/` | `src/app/page.tsx` | `HomePage` — New Debate workspace | Client |
| `/debate/[threadId]` | `src/app/debate/[threadId]/page.tsx` | `DebatePage` | Client |
| `/history` | `src/app/history/page.tsx` | `HistoryPage` | Client |
| `/compare` | `src/app/compare/page.tsx` | `ComparePage` → `CompareContent` in `Suspense` | Server wrapper |
| `/simulate` | `src/app/simulate/page.tsx` | Scenario simulation | Client |
| `/knowledge` | `src/app/knowledge/page.tsx` | Knowledge base management | Client |
| `/memory` | `src/app/memory/page.tsx` | Agent memory browser | Client |
| `/analytics` | `src/app/analytics/page.tsx` | Analytics dashboard | Client |
| `/backend/*` | `src/app/backend/[...path]/route.ts` | API proxy route handler (all methods, `force-dynamic`) | Server |
| (error) | `src/app/error.tsx`, `src/app/debate/[threadId]/error.tsx` | Error boundaries | Client |
| (404) | `src/app/not-found.tsx` | Not-found page | Server |

---

## Root Layout (`layout.tsx`)

**Type:** Server Component.

- **Metadata** — title "AgentBoard — Multi-Agent Decision Engine" and a description.
- **Font** — Inter via `next/font/google`.
- **Flash-free theme** — an inline `<head>` script reads `localStorage.theme` (or `prefers-color-scheme`) and sets the `dark` class before paint.
- **NavBar** — sticky header: logo, backend health dot (`healthCheck()` every 30 s with backoff), 7 links (New Debate, History, Compare, Simulate, Knowledge, Memory, Analytics) with active-route highlight, `LLMSettingsPanel`, `ThemeToggle`, `?` for keyboard shortcuts, and a mobile menu that closes on navigation and Escape.
- **ToastProvider** — global notifications via `useToast().showToast()`.
- **Main** — `max-w-6xl`, centred.
- **SiteFooter** — copyright line; hidden on `/` so the workspace owns the viewport.

---

## Home Page (`/`)

**File:** `src/app/page.tsx` — the **New Debate workspace**: a compact header, a collapsible template gallery, and a two-column workspace (configuration form on the left, context rail on the right).

### State

| State | Type | Description |
|---|---|---|
| `isLoading` | `boolean` | `startDebateAsync()` in flight |
| `templates` | `DebateTemplate[]` | Built-in templates |
| `showTemplates` | `boolean` | Gallery expanded |
| `prefillQuery` / `prefillMode` / `prefillTemplateId` | — | Set when a template is picked |
| `prefillKey` | `number` | Remounts `DebateInput` on a new template |
| `defaultMode` | `"quick" \| "standard" \| "thorough" \| undefined` | Server default from `GET /debate-modes` |
| `domainPacks` / `selectedDomainPack` | — | Domain packs and the active one |
| `templateSearch` / `activeCategory` | `string` | Gallery search and category |
| `agents` / `selectedAgents` | — | Roster (from `getAgents()`, falls back to 5 defaults) |
| `recentDebates` / `recentLoaded` | — | Last 3 debates; whether the fetch succeeded |

### Layout

| Area | Content |
|---|---|
| Header | "Five AI agents. One decision." + a **Templates** toggle with a count badge (`aria-controls` → gallery) |
| Template gallery | Labelled region "Debate templates": search, category tabs (All, Business, Technology, Strategy, Personal, Finance), `TemplateCard` grid |
| Left: configuration | `DebateInput` form, or `LoadingState` while starting |
| Right: context rail | Domain pack selector + agent roster in one card; Recent debates (hidden if the fetch failed) |

### DebateInput

Props: `onSubmit`, `onCancel`, `isLoading`, `agents`, `selectedAgents`, `prefillQuery`, `prefillMode`, `prefillTemplateId`, `defaultMode`, `selectedDomainPack`, `samples`.

- **Query** — textarea (10–5000 chars, auto-height, inline validation, shake on invalid submit). While empty, **starter chips** offer template questions.
- **Mode** — Quick / Standard / Thorough cards plus **Custom** (rounds 2–6, default 4; threshold, default 0.75). Initial mode: a template's mode → the server default → Quick. A server default that arrives late never overrides a mode the user already picked.
- **Options** — `use_knowledge_base`, `enable_agent_memory`, `supervised` toggles.
- **Template id** — kept while the query started from a template (card or chip), dropped when the box is cleared; sent as `template_id` for per-template analytics.

### Agent roster

Agents are toggled in `AgentRoster`. The Moderator is always included, and at least **two debating agents** must stay selected (the backend enforces the same rule). All selected → `agents` is omitted (all enabled agents).

### Flow

1. On mount: templates, domain packs, 3 recent debates, agents and the default mode load in parallel (each retried briefly while the dev servers warm up).
2. Submit → `startDebateAsync({ query, mode, template_id, max_rounds?, consensus_threshold?, agents?, … })` → `{ thread_id }`.
3. `router.push(/debate/{thread_id})`. Errors show a toast; cancelling during the start request cancels the debate server-side if it was already created.

---

## Debate Page (`/debate/[threadId]`)

**File:** `src/app/debate/[threadId]/page.tsx` — a thin shell: breadcrumb (`Home / {query}`, filled in via `onQuery`) and `<DebateStreamViewer threadId=… />`. A route-level `error.tsx` catches rendering errors.

### Flow (DebateStreamViewer)

```
mount
  ├─ getHistoryItem(threadId) — if the debate already finished, show the stored decision
  └─ connectToStream(threadId) — EventSource on /debate/{id}/stream
       debate_started → query banner, agents
       round_started / phase_started → round progress ("Round N of M") and phase badge
       agent_output → AgentCard (Veto badge when vetoing)
       critique_completed → CritiqueView
       tool_called → tool activity
       synthesis → moderator synthesis (measured agreement)
       agent_timeout → missing agent marked
       approval_required → HITLPanel (approve / override / add round / cancel)
       debate_resumed → continuing after resume / approval
       final_decision → FinalDecisionPanel
       cancelled → cancelled view
       error → "Debate failed" view (with "Resume debate" if resumable)
```

**Connection:** a badge shows Connected / Reconnecting… / Disconnected. Drops reconnect with exponential backoff (1 s → 30 s), resuming after the last event id. After 10 failed attempts the page shows **"Connection lost"** — the debate may still be running — with an in-place **Reconnect** (no page reload).

### Actions

- **Stop debate** (while running) → `cancelDebate()`.
- **Resume debate** (failed, checkpoint available) → `resumeDebateAsync()`; the stream picks up again.
- **HITL panel** (supervised) → `approveDebate()`; override requires feedback; "add round" only below the round limit; "Cancel this debate".
- **Decision panel** → evaluate (`evaluateDecision()`), copy, export Markdown / PDF / JSON (`exportDecision()`).

---

## History Page (`/history`)

**File:** `src/app/history/page.tsx`

### State

| State | Default | Description |
|---|---|---|
| `data` | `null` | `HistoryListResponse` |
| `page` | `1` | Current page |
| `query` / `inputValue` | `""` | Committed search / search box |
| `terminationFilter` | `"all"` | `all`, `consensus_reached`, `human_override`, `max_rounds_reached` |
| `sortOrder` | `"newest"` | `newest`, `oldest`, `highest_agreement` |
| `loading` / `error` | — | Loading and error state |

### Flow

1. Whenever page, query, filter or sort changes: `getHistory({ page, limit: 15, q, sort, termination_reason })`. **Filtering and sorting happen on the server** over the whole history, before paging — the page shows the server's order as is.
2. A request counter drops responses that arrive after a newer request (no stale results).
3. Search input is debounced (300 ms); changing search, filter or sort returns to page 1.
4. Each `HistoryCard`: query, date/time, rounds, KB/Memory badges, termination badge (Consensus / Human Override / Max Rounds), agreement bar, and **View** / **Compare** — real links (`/debate/{id}`, `/compare?a={id}`), so they can be opened in a new tab.
5. Pagination "Page X of Y (N total)"; skeleton while loading; empty and error states; **Reset** clears search, filter and sort.

---

## Compare Page (`/compare`)

**Files:** `src/app/compare/page.tsx` (server wrapper with `Suspense`) → `CompareContent`.

- Reads `?a=` / `?b=` and loads both decisions with `getHistoryItem()`.
- Fetches 8 recent debates for quick picks.
- Two `DebateColumn`s: query, decision, confidence/agreement meters, comparative badges (better / worse / equal), risk flags, alternatives, dissent.

---

## Simulate Page (`/simulate`)

**File:** `src/app/simulate/page.tsx` — runs one question several times to measure how stable the decision is.

### State

| State | Description |
|---|---|
| `query` | Question (pre-filled from `?query=`) |
| `runs` | 2–5 |
| `maxRounds` | `null` = the mode's preset ("Mode default" placeholder) |
| `mode` | Quick / Standard / Thorough — starts at the server default (`GET /debate-modes`) unless the user already chose |
| `loading` / `error` / `result` | Job state and `SimulationResult` |

All fields have associated `<label>`s (`htmlFor`/`id`).

### Flow

1. `startSimulation({ query, runs, mode, max_rounds? })` → `POST /debate/simulate-async` → job id.
2. Poll `getSimulationJob(id)` every 2 s until `completed`, `failed` or `cancelled`.
3. **Cancel** → `cancelSimulationJob(id)`; leaving the page cancels a running job too.
4. Results: stability rating, consistency score (calibrated — see the API reference), confidence variance, average agreement, `runs_completed` of `runs`, stable risk flags (same risk in any wording in ≥ 70 % of runs), per-run results.

---

## Knowledge Page (`/knowledge`)

**File:** `src/app/knowledge/page.tsx` — upload, list and delete knowledge-base documents.

| State | Description |
|---|---|
| `docs` | `KnowledgeDocument[]` (`name`, `chunks`) |
| `loading` / `fetchError` | Initial list load |
| `uploading` / `uploadError` | Upload in progress / validation or server error |
| `deleteTarget` | Document being deleted |
| `dragOver` | Drag-and-drop highlight |

- Click or drag a file: `.pdf`, `.txt`, `.md`, max 10 MB (checked in the browser and on the server).
- Delete → `deleteKnowledgeDocument(name)` (an **admin** action: sends the admin token when one is set).

---

## Memory Page (`/memory`)

**File:** `src/app/memory/page.tsx` — lessons agents learned from past debates.

- The agent list comes from `getAgents()` (registry names such as "Analyst", including domain agents), so new agents appear automatically.
- For each agent: `getAgentMemory(name, 20)`; entries show relative time and the lesson.
- **Clear Memory** per agent → `clearAgentMemory(name)` (**admin** action).

Per-agent state: `{ entries, loading, clearing, error }`.

---

## Analytics Page (`/analytics`)

**File:** `src/app/analytics/page.tsx` — recharts dashboard with a range filter (All time / 7 / 30 / 90 days).

| Tab | Data | Content |
|---|---|---|
| Overview | `getAnalyticsOverview(days)`, `getAnalyticsConvergence(days)` | KPIs (total debates; **avg rounds** with "N when consensus is reached"; avg agreement; consensus rate), completed debates per day (labelled with the range it covers), terminations pie, agreement by round, mode and domain-pack breakdowns |
| Agents | `getAnalyticsAgents(days)` | Confidence & contribution bars; **pairwise agreement** matrix (how alike two agents' final positions were; "—" for pairs that never met) |
| Quality | `getAnalyticsQuality(days)` (loaded when the tab opens) | Average quality, scores by mode and domain pack, best/worst templates (only debates started from a template) |

---

## Error Boundaries & 404

- `src/app/error.tsx` — global boundary: **Try Again** (`reset()`) and **Go Home**; logs the error.
- `src/app/debate/[threadId]/error.tsx` — the same for the debate page.
- `src/app/not-found.tsx` — "Start a new debate" → `/`, "View history" → `/history`.
