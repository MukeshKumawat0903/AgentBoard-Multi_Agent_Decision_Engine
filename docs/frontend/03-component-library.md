# Component Library

All components live in `src/components/` and are **client components** (`"use client"`). Most are presentational with light local state; the ones that call the API are `DebateStreamViewer` (SSE, decision fallback, resume, cancel), `HITLPanel` (approve, cancel), `FinalDecisionPanel` (evaluate, export), `CompareContent` (history), `LLMSettingsPanel` (settings) and `NavBar` (health). Data otherwise flows in via props from pages.

---

## Component Hierarchy

**21 components** in `src/components/` plus **6 primitives** in `src/components/ui/`:

| # | Component | Purpose |
|---|---|---|
| 1 | NavBar | Sticky nav: links, health dot, mobile menu, shortcuts trigger |
| 2 | Toast (ToastProvider + useToast) | Global notifications |
| 3 | KeyboardShortcutsHelp | Shortcuts modal (`?`) |
| 4 | Skeleton (7 exports) | Loading placeholders |
| 5 | ThemeToggle | Light / dark switch |
| 6 | Toggle | Accessible switch (DebateInput options) |
| 7 | Markdown | `react-markdown` + `remark-gfm` renderer |
| 8 | LLMSettingsPanel | Provider/model switch with server-key and admin-token awareness |
| 9 | DebateInput | New-debate form |
| 10 | LoadingState | Spinner while a debate starts |
| 11 | DebateStreamViewer | Live debate: SSE, reconnect, resume, connection-lost view, HITL |
| 12 | AgentCard | One agent's response (+ Veto badge) |
| 13 | AgentRoster | Home right rail: choose agents / show a domain pack's agents |
| 14 | ConfidenceMeter | Colour-coded 0–1 bar |
| 15 | ConfidenceDriftChart | Confidence per agent across rounds |
| 16 | CritiqueView | Severity-badged critiques |
| 17 | FinalDecisionPanel | Decision, reviewer direction, vetoes, disagreements, evaluate, export, copy |
| 18 | HITLPanel | Human-in-the-loop approval modal |
| 19 | TemplateCard | Template card |
| 20 | CompareContent | Side-by-side comparison |
| 21 | SiteFooter | Footer (hidden on `/`) |

**`ui/` primitives:** `AgentAvatar`, `Badge`, `Button` (+ `buttonClasses()`), `Card`, `CollapsibleSection`, `RadialGauge`.

> `DebateRoomWarmup` is an internal sub-component of `DebateStreamViewer` (the "assembling the debate room" state while connecting).

```
layout.tsx (Server Component)
├── ToastProvider
├── NavBar
│   ├── LLMSettingsPanel        ← gear icon + portal modal
│   ├── ThemeToggle
│   └── KeyboardShortcutsHelp   ← ? button + portal modal
├── SiteFooter                  ← null on "/"
└── page.tsx (Home)
    ├── TemplateCard  (per template, in the "Debate templates" region)
    ├── DebateInput   (uses Toggle) / LoadingState
    └── AgentRoster   (right rail, with the domain pack selector)

debate/[threadId]/page.tsx
└── DebateStreamViewer          ← useReducer(debateStreamReducer) + connectToStream
    ├── AgentCard  (per agent per round)
    ├── CritiqueView  (per round)
    ├── CollapsibleSection → ConfidenceDriftChart, transcript
    ├── HITLPanel  (on approval_required)
    └── FinalDecisionPanel
        ├── Markdown, RadialGauge
        └── CollapsibleSection  (disagreements, minority report, trace, …)

history/page.tsx → HistoryCard (inline; View / Compare links)
compare/page.tsx → CompareContent → DebateColumn ×2
```

---

## NavBar

**File:** `src/components/NavBar.tsx`

The sticky top navigation bar. This is the primary navigation component rendered by the root layout.

### Features

- **Skip-to-content link** — Visually hidden, appears on focus for keyboard accessibility
- **Backend health indicator** — Green/red/pulsing dot next to logo. Polls `healthCheck()` every 30s with exponential backoff on failure (30s → 60s → 120s, max 5 min). Recovers immediately on next success.
- **Active route highlighting** — Uses `usePathname()` to underline the current page link
- **Mobile hamburger menu** — Collapsible dropdown for screens below `sm` breakpoint. Closes on route change and Escape key.
- **Global `?` shortcut** — Opens the `KeyboardShortcutsHelp` modal. Ignored when focus is inside input/textarea/select.
- **Desktop nav** — 7 links (New Debate, History, Compare, Simulate, Knowledge, Memory, Analytics) + LLMSettingsPanel + ThemeToggle + `?` button

### State

| State | Type | Default | Description |
|---|---|---|---|
| `menuOpen` | `boolean` | `false` | Mobile menu visibility |
| `helpOpen` | `boolean` | `false` | Keyboard shortcuts modal visibility |
| `healthStatus` | `"loading" \| "ok" \| "error"` | `"loading"` | Backend connection status |

---

## SiteFooter

**File:** `src/components/SiteFooter.tsx`

The app footer rendered by the root layout below `<main>`. A lightweight client component that uses `usePathname()` to **return `null` on the home page (`/`)** so the New Debate workspace owns the full viewport, and renders normally on every other route.

Content is a single centered copyright line: `AgentBoard © <year> — Powered by Groq, OpenAI, Anthropic & Gemini via LangChain` (year via `new Date().getFullYear()`). Styled with a top border and muted text; participates in dark mode.

---

## Toast

**File:** `src/components/Toast.tsx`

Global notification system using React Context + `createPortal`.

### Architecture

1. **`ToastProvider`** — Wraps the entire app in `layout.tsx`. Manages toast state and provides the `showToast` function via context.
2. **`useToast()` hook** — Returns `{ showToast(message, variant?) }`. Available in any client component.
3. **`SingleToast`** — Individual notification rendered at bottom-right via portal.

### Configuration

| Constant | Value | Description |
|---|---|---|
| `MAX_TOASTS` | `3` | Maximum visible toasts (oldest dropped) |
| `DISMISS_AFTER_MS` | `5000` | Auto-dismiss delay |

### Variants

| Variant | Colour | Icon |
|---|---|---|
| `success` | Green | ✓ |
| `error` | Red | ✕ |
| `info` | Blue | ℹ |

### Usage

```ts
const { showToast } = useToast();
showToast("Debate started!", "success");
showToast("Backend unreachable", "error");
```

---

## KeyboardShortcutsHelp

**File:** `src/components/KeyboardShortcutsHelp.tsx`

Modal overlay listing all available keyboard shortcuts. Rendered via `createPortal`.

### Props

| Prop | Type | Description |
|---|---|---|
| `open` | `boolean` | Whether the modal is visible |
| `onClose` | `() => void` | Callback to close the modal |

### Features

- **Focus trap** — Tab/Shift+Tab cycles within the modal
- **Escape to close** — Dismisses the modal
- **Body scroll lock** — Prevents scrolling while open
- **Backdrop click** — Closes the modal

### Shortcuts Listed

| Key | Action |
|---|---|
| `?` | Open shortcuts overlay |
| `Esc` | Close modal / cancel action |
| `J` / `K` | Focus next/previous debate in History |
| `N` | Go to New Debate |
| `H` | Go to History |
| `A` | Go to Analytics |
| `M` | Go to Memory |
| `S` | Go to Simulate |

---

## Skeleton

**File:** `src/components/Skeleton.tsx`

Reusable loading placeholder components that replace spinners with content-shaped pulsing rectangles.

### Exports

| Component | Description |
|---|---|
| `SkeletonBlock` | Basic pulsing rectangle. Accepts `className` for sizing. |
| `SkeletonText` | Multiple text-line placeholders. `lines` prop (default 3), last line is 4/5 width. |
| `SkeletonCard` | Card with circular avatar, header lines, body text lines, and progress bar stub. |
| `SkeletonKpi` | KPI card shape: label line + large number line + subtitle line. |
| `SkeletonChart` | Chart area placeholder with configurable `height` (default 220px). |
| `SkeletonList` | Vertical stack of `SkeletonCard` components. `count` prop (default 5). |
| `SkeletonAgentPanel` | Agent panel shape: coloured header strip + body text lines. |

All skeleton components set `aria-hidden="true"` and use the shared base class `animate-pulse rounded bg-gray-200 dark:bg-gray-700`.

---

## DebateStreamViewer

**File:** `src/components/DebateStreamViewer.tsx`

The live debate view. It first asks the REST API for a stored decision (`getHistoryItem`) — a finished debate loads straight away — and otherwise follows the SSE stream via `connectToStream()`, folding events into state with a `useReducer` (the pure reducer is `lib/debateStreamReducer.ts`, unit-tested).

### Props

| Prop | Type | Description |
|---|---|---|
| `threadId` | `string` | The debate to show |
| `onQuery` | `(query: string) => void` (optional) | Reports the query to the page (breadcrumb) |

### State (via `useReducer`)

| Field | Type | Default | Description |
|---|---|---|---|
| `status` | `"connecting" \| "streaming" \| "done" \| "error" \| "cancelled"` | `"connecting"` | Lifecycle |
| `query` | `string` | `""` | From `debate_started` |
| `maxRounds` / `currentRound` | `number` | `4` / `0` | Round progress |
| `currentPhase` | `DebatePhase \| ""` | `""` | Active phase |
| `rounds` | `DebateRound[]` | `[]` | Outputs, critiques, tool calls per round |
| `syntheses` | `Record<number, SynthesisEvent>` | `{}` | Moderator summary per round |
| `agents` / `agentStatus` | — | — | Participants and `waiting / working / done / timeout` |
| `approvalRequired` | `ApprovalRequiredEvent \| null` | `null` | Pending HITL request |
| `finalDecision` | `FinalDecision \| null` | `null` | The decision |
| `error` | `string \| null` | `null` | Error text |
| `resumable` | `boolean` | `false` | The backend reported the debate failed (so it can be resumed), as opposed to the browser losing the stream |

Besides events, the reducer accepts `stream_error` (connection lost; ignored once a decision arrived), `reset` (start over before resuming) and `clear_approval` (with the answered round number, so a newer approval request isn't cleared by an older answer).

### Event Handling

| Event | Action |
|---|---|
| `debate_started` | `status = "streaming"`; query, max rounds, agents |
| `round_started` / `phase_started` | Round counter, phase, agent "working" status |
| `agent_output` | Add or replace the agent's output (incl. `veto`, `veto_reason`) |
| `tool_called` | Record tool activity on the round |
| `critique_completed` | Append the critique (deduplicated on replay) |
| `synthesis` | Store the round's synthesis (measured agreement, summary, areas) |
| `agent_timeout` | Mark the agent timed out |
| `approval_required` | Store the request → `HITLPanel` |
| `debate_resumed` | Back to streaming after a resume or approval |
| `debate_completed` | No-op (the decision follows) |
| `final_decision` | `finalDecision`, `status = "done"` |
| `cancelled` | `status = "cancelled"` |
| `error` | `status = "error"`; message by `error_type` / code; sets `resumable` for engine failures |
| `ping` | Handled in `connectToStream` (keep-alive), never dispatched |

### Visual States

| Status | Display |
|---|---|
| `connecting` | `DebateRoomWarmup`: agents "taking their seats", cycling status line, connection badge |
| `streaming` | Query banner with connection badge and **Stop debate**, round progress ("Round N of M" + phase), agent strip, round cards. While paused for HITL: "Paused — waiting for your review." |
| `done` | Completion banner (consensus / max rounds / human override), `FinalDecisionPanel`, collapsible transcript |
| `cancelled` | Cancelled message with links |
| `error` (debate failed) | "Debate failed" + message, **Resume debate** (when `resumable`), Retry stream, Start new debate |
| `error` (connection lost) | "Connection lost" — the debate may still be running — with an in-place **Reconnect** (resets state and reconnects; no page reload) |

### Live Round Rendering

Each round card: number, phase, agreement (once synthesised); `AgentCard` grid; up to 6 `CritiqueView`s with "+N more"; the moderator synthesis with agreement/disagreement areas. J / K keys move between rounds.

### Connection Status Indicator

`connectToStream()` reports `connected` (on open), `reconnecting` (after a drop) and `disconnected`:

| State | Badge |
|---|---|
| `connected` | Green "Connected" |
| `reconnecting` | Amber "Reconnecting…" (spinning) |
| `disconnected` | Red "Disconnected" |

Reconnects use exponential backoff (1, 2, 4, 8, 16, then 30 s) and resume after the last event id. A 60 s silence (no event or `ping`) counts as a dropped connection. After 10 failed attempts the viewer shows the connection-lost view.

### Auto-Scroll

While streaming, the view follows the newest round; when the decision arrives it scrolls to it once.

### DebateRoomWarmup (internal)

While `status === "connecting"`: the five default agents as `AgentAvatar`s taking their seats, "Assembling the debate room…", an `aria-live` line cycling warm-up messages every 2.2 s, and the connection badge. Not exported.

---

## CompareContent

**File:** `src/components/CompareContent.tsx`

Side-by-side comparison of two debate decisions. Fetches debates by thread ID and renders them in a two-column layout with comparative highlighting.

### Props

None — reads URL search params (`?a=<id>&b=<id>`) via `window.location.search`.

### State

| State | Type | Default | Description |
|---|---|---|---|
| `inputA` / `inputB` | `string` | `""` | Thread ID inputs |
| `debateA` / `debateB` | `FinalDecision \| null` | `null` | Loaded debate data |
| `errorA` / `errorB` | `string \| null` | `null` | Per-slot error |
| `loadingA` / `loadingB` | `boolean` | `false` | Per-slot loading |
| `recentItems` | `HistoryItem[]` | `[]` | Recent debates for quick-pick |

### Sections

| Section | Description |
|---|---|
| Header | "Compare Debates" title + description |
| Input Panel | Two thread-ID inputs + Compare button + recent-debate quick-pick buttons |
| Results Grid | Two-column `DebateColumn` layout (query, decision, confidence/agreement, meta badges with comparison highlighting) |

### Comparison Highlighting

Meta badges (round count, agreement, risk flags) are highlighted with `better` / `worse` / `equal` / `neutral` variants when both debates are loaded, providing visual cues about which debate performed better on each metric.

---

## DebateInput

**File:** `src/components/DebateInput.tsx`

The form for starting a debate. State comes from the home page via props.

### Props

| Prop | Type | Description |
|---|---|---|
| `onSubmit` | `(query: string, options: DebateOptions) => void` | Called with the query and settings |
| `onCancel` | `() => void` (optional) | Cancel while starting |
| `isLoading` | `boolean` | Disables controls |
| `agents` / `selectedAgents` | `AgentOption[]` / `Set<string>` | Roster from the page |
| `prefillQuery` | `string` (optional) | Template query |
| `prefillMode` | `ModeSelection` (optional) | Template's recommended mode |
| `prefillTemplateId` | `string` (optional) | Template the query came from |
| `defaultMode` | `"quick" \| "standard" \| "thorough"` (optional) | Server default (`GET /debate-modes`) |
| `selectedDomainPack` | `string \| null` (optional) | Active domain pack |
| `samples` | `SampleQuestion[]` (optional) | Starter chips (`label`, `query`, optional `templateId`) |

### Exported Types

```ts
interface DebateOptions {
  mode: ModeSelection;           // "quick" | "standard" | "thorough" | "custom"
  template_id?: string;
  max_rounds?: number;           // Custom only
  consensus_threshold?: number;  // Custom only
  agents?: string[];             // omitted when every agent is selected
  use_knowledge_base?: boolean;
  enable_agent_memory?: boolean;
  supervised?: boolean;
  domain_pack?: string | null;
}
```

### Form Controls

| Control | Details |
|---|---|
| **Query** | `maxLength={5000}` with a counter; min 10 characters; auto-height; red glow and shake on invalid submit. While empty, **starter chips** (template questions) fill it in |
| **Mode** | Cards for Quick (Zap · 2 rounds · no critiques · 0.60), Standard (SlidersHorizontal · 2 rounds · full critique · 0.75), Thorough (Microscope · 6 rounds · 0.85), and **Custom** (Settings2 · rounds 2–6, default 4 · threshold, default 0.75). Custom is sent as `mode: "custom"` with explicit `max_rounds` / `consensus_threshold` |
| **Options** | `use_knowledge_base` (links to `/knowledge`), `enable_agent_memory`, `supervised` (HITL) toggles |
| **Submit** | "Start Debate"; disabled while loading or with fewer than 10 characters |

### Initial mode

`prefillMode` (a template's suggestion) → `defaultMode` (server) → `"quick"`. The server default is fetched after the first render; it is applied only if the user hasn't picked a mode yet.

### Template tracking

`template_id` is kept while the query started from a template (card or chip) — editing the text keeps it — and dropped once the box is cleared. It's only used for per-template analytics.

### Submit Flow

`onSubmit(query, options)`; the home page calls `startDebateAsync()` and navigates to the debate on success.

---

## LoadingState

**File:** `src/components/LoadingState.tsx`

Animated spinner shown while the backend processes a debate.

### Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `message` | `string` (optional) | `"Agents are debating…"` | Primary message text |

### Visual Elements

| Element | Details |
|---|---|
| **Spinner** | 16×16 CSS-only spinner — gray ring with a blue `border-t-transparent` arc, `animate-spin` |
| **Primary Text** | Customisable message in medium weight |
| **Secondary Text** | `animate-pulse` hint: "This may take 30–90 seconds…" |
| **Phase Dots** | Four animated dots labelled "Proposals", "Critiques", "Revisions", "Convergence" — each with a staggered `animationDelay` (0ms, 200ms, 400ms, 600ms) |

---

## AgentCard

**File:** `src/components/AgentCard.tsx`

One agent's response, with an accent rail in the agent's colour.

### Props

| Prop | Type | Description |
|---|---|---|
| `response` | `AgentResponse` | The agent's output for a round |

### Behaviour

1. Looks up `AGENT_META` / `DOMAIN_AGENT_META` for name and role (generic fallback for unknown agents).
2. Header: `AgentAvatar`, name, role, round — and a red **Veto** badge when `response.veto` is true.
3. Body: a veto notice ("Veto — consensus is blocked while it stands" + `veto_reason`) when vetoing, then **Position** and **Reasoning** (Markdown), **Assumptions**, and a `ConfidenceMeter`.

### Layout

```
┌──────────────────────────────────┐
│ 🤝 Ethics        [VETO] Round 2  │
│    Ethics and compliance guardian│
├──────────────────────────────────┤
│ Veto — consensus is blocked …    │
│ No user consent.                 │
│ Position / Reasoning / …         │
│ Confidence  ████████░░  82%      │
└──────────────────────────────────┘
```

---

## ConfidenceMeter

**File:** `src/components/ConfidenceMeter.tsx`

A colour-coded horizontal progress bar for 0–1 scores.

### Props

| Prop | Type | Default | Description |
|---|---|---|---|
| `score` | `number` | — | Value between 0 and 1 |
| `label` | `string` (optional) | — | Text displayed above the bar |
| `size` | `"sm" \| "md"` | `"md"` | Bar height: `h-2` (sm) or `h-3` (md) |

### Colour Bands

| Range | Colour | CSS Class |
|---|---|---|
| 0.0 – 0.3 | Red | `bg-red-500` |
| 0.3 – 0.6 | Yellow | `bg-yellow-400` |
| 0.6 – 0.8 | Light Green | `bg-lime-400` |
| 0.8 – 1.0 | Green | `bg-green-500` |

The bar width is animated with `transition-all duration-500` for smooth updates.

---

## CritiqueView

**File:** `src/components/CritiqueView.tsx`

Displays critiques targeting a specific agent, with severity-coloured badges.

### Props

| Prop | Type | Description |
|---|---|---|
| `critiques` | `CritiqueResponse[]` | Critiques to display (pre-filtered by caller) |

### Severity Styles

| Severity | Light Mode | Dark Mode |
|---|---|---|
| `low` | Gray background | `dark:bg-gray-700` |
| `medium` | Yellow background | `dark:bg-yellow-900/40` |
| `high` | Orange background | `dark:bg-orange-900/40` |
| `critical` | Red background | `dark:bg-red-900/40` |

### Content per Critique

- **Header row** — Critic agent name (colour-coded) + severity badge (pill)
- **Critique points** — Bulleted list
- **Suggested revision** — Italic text (conditional, only if non-null)

---

## AgentRoster

**File:** `src/components/AgentRoster.tsx`

The home page's right-rail panel listing the agents that will debate, together with the domain pack selector.

- **No domain pack** — the enabled core agents are toggles. The Moderator is always included (disabled toggle, `*`); the page keeps at least **two debating agents** selected.
- **Domain pack selected** — the pack defines the roster (the backend uses the pack's agents), so they're shown read-only, with a core / domain breakdown.

---

## Toggle

**File:** `src/components/Toggle.tsx`

An accessible switch/checkbox control used by `DebateInput` for the intelligence options (knowledge base, agent memory, supervised mode). Keyboard- and screen-reader-friendly with proper `role`/`aria-checked` semantics.

---

## Markdown

**File:** `src/components/Markdown.tsx`

A thin wrapper around `react-markdown` with the `remark-gfm` plugin and Tailwind-styled element overrides. Used by `FinalDecisionPanel` (and elsewhere) to render LLM-generated decision and rationale text — GitHub-flavoured markdown (lists, tables, bold, links) renders correctly instead of showing raw syntax.

---

## `ui/` Design-System Primitives

**Folder:** `src/components/ui/`

| Component | Purpose |
|---|---|
| `AgentAvatar` | Colour-coded agent avatar (`AGENT_META` / `DOMAIN_AGENT_META`); `agentColor()` helper |
| `Badge` | Pill with tone variants (success, warning, danger, info, violet, neutral) |
| `Button` | Button with variants (primary, secondary, outline, ghost, danger), sizes, loading spinner. `buttonClasses(variant, size)` gives the same styling to non-buttons, e.g. the History page's View / Compare **links** |
| `Card` | Standard rounded container |
| `CollapsibleSection` | Accessible expand/collapse section |
| `RadialGauge` | SVG gauge for 0–1 scores |

---

## FinalDecisionPanel

**File:** `src/components/FinalDecisionPanel.tsx`

The decision and everything supporting it.

### Props

| Prop | Type | Description |
|---|---|---|
| `decision` | `FinalDecision` | The decision |

### Sections (in order)

| Section | Content | Condition |
|---|---|---|
| **Degraded banner** | Expected agents missing from the final round | `degraded` |
| **Decision** | `decision` (Markdown) | Always |
| **Human reviewer direction** | The HITL override the decision was told to follow | `human_feedback` |
| **Standing veto(es)** | Each Ethics-class veto still standing: agent and reason | `vetoes.length > 0` |
| **Rationale** | `rationale_summary` (Markdown) | Always |
| **Scores** | Agreement and confidence (`RadialGauge`) | Always |
| **Meta** | Rounds, termination reason, token usage and estimated cost | Always / when present |
| **Risk flags**, **Alternatives** | Lists | When present |
| **Structured disagreements** | Contested topics, agent vs agent | When present |
| **Dissenting opinions**, **Minority report**, **Key disagreements** | Dissent details | When present |
| **Agent contribution** | Alignment × confidence per agent | When present |
| **Evaluate** | `evaluateDecision()` → four scores + reasoning | Button |
| **Copy** | Markdown summary (decision, reviewer direction, standing vetoes, rationale, risks, alternatives, scores) to the clipboard | Button |
| **Export** | Markdown / PDF / JSON via `exportDecision()` | Menu |
| **Debate trace** | Round-by-round trace (agent cards, critiques) | `debate_trace.length > 0` |

Expanded/collapsed sections are remembered in `localStorage`.

### Evaluate Feature

`evaluateDecision(threadId)` (cached on the server after the first call) returns completeness, consistency, actionability and risk awareness (0–1), their mean as `overall`, and the judge's reasoning.

### Export & Copy

Exports download the returned `Blob` (`markdown`, `pdf`, `json`); the Markdown and PDF include the reviewer direction and standing vetoes. Copy writes the summary to the clipboard and confirms with a toast.

---

## Inline Debate Trace

The saved round-by-round trace (formerly the standalone `DebateTimeline` + `RoundView` components, now **removed**) renders inline:

- **Live** — `DebateStreamViewer` shows each round as it streams (agent cards, critiques, synthesis banner).
- **After completion** — `FinalDecisionPanel` renders the persisted `debate_trace` inside a `CollapsibleSection`: per round, the agent cards (`AgentCard` + `ConfidenceMeter`) and their critiques (`CritiqueView`), with the latest round expanded by default.

There is no separate timeline component anymore — keeping the trace inside the two contexts where it's read avoids duplicate rendering logic.

---

## ThemeToggle

**File:** `src/components/ThemeToggle.tsx`

Toggle button for switching between light and dark mode.

### Behaviour

1. On mount: syncs local `dark` state with `document.documentElement.classList.contains("dark")` (already applied by the inline script in layout.tsx)
2. On click: toggles the `dark` class on `<html>`, persists `"dark"` or `"light"` to `localStorage.theme`, updates local state
3. Renders a **sun** SVG icon in dark mode (indicating "switch to light") or a **moon** SVG icon in light mode (indicating "switch to dark")

### Accessibility

- `aria-label="Toggle dark mode"`
- Dynamic `title` attribute: "Switch to light mode" / "Switch to dark mode"

---

## HITLPanel

**File:** `src/components/HITLPanel.tsx`

Modal shown during a supervised debate when an `approval_required` event arrives.

### Props

| Prop | Type | Description |
|---|---|---|
| `event` | `ApprovalRequiredEvent` | Round, agreement, termination reason, synthesis summary, allowed `options` |
| `threadId` | `string` | Debate id |
| `onDone` | `(roundNumber: number) => void` | Called with the round of the request that was answered (so a newer request isn't cleared) |

### Behaviour

- Shows the round, agreement and the moderator's summary.
- **✓ Approve** → `approveDebate(threadId, "approve")`.
- **✎ Override** → opens a feedback box; **Submit Override** is disabled until feedback is entered → `approveDebate(threadId, "override", feedback)`. The decision will follow this direction.
- **Add round** → `approveDebate(threadId, "add_round")`; only shown when the event's `options` include it (below the round limit).
- **Cancel this debate** → `cancelDebate(threadId)`.
- Approvals return **202**; the debate continues on the same stream (the viewer shows "Paused — waiting for your review." until then). Errors (e.g. a 409 because the debate is already continuing) are shown in the panel.

---

## ConfidenceDriftChart

**File:** `src/components/ConfidenceDriftChart.tsx`

A **recharts** `LineChart` showing how each agent's confidence score evolves across debate rounds.

### Props

| Prop | Type | Description |
|---|---|---|
| `rounds` | `DebateRound[]` | Debate rounds (agent outputs with confidence) |
| `consensusThreshold` | `number` (optional) | Threshold drawn as a `ReferenceLine` |

### Internals

- Uses `useMemo` to extract unique agent names and transform round data into chart-friendly format
- One `Line` per agent, coloured by an agent colour map
- `ReferenceLine` at the consensus threshold (dashed, labelled "Consensus")
- Wrapped in `ResponsiveContainer` (height 260)
- Legend and tooltip enabled

---

## TemplateCard

**File:** `src/components/TemplateCard.tsx`

A clickable card representing a debate template, shown on the home page template browser.

### Props

| Prop | Type | Description |
|---|---|---|
| `template` | `DebateTemplate` | Template data: title, query, category, tags, icon |
| `onSelect` | `(template: DebateTemplate) => void` | Callback when user clicks the card |

### Behaviour

- Card background uses a category-specific colour from `CATEGORY_COLORS` map (5 categories: `Business`, `Technology`, `Strategy`, `Personal`, `Finance`)
- Displays: category icon, title, query preview (truncated with `line-clamp-2`), and up to 3 tags
- On click calls `onSelect(template)` which pre-fills the `DebateInput` form

---

## LLMSettingsPanel

**File:** `src/components/LLMSettingsPanel.tsx`

A gear button in the nav that opens a modal for switching the active LLM provider and model at runtime — for **all** users, so it's an admin action on the server.

### Rendering Strategy

Rendered via `createPortal(modal, document.body)` to escape the header's stacking context; a `mounted` guard avoids SSR hydration mismatches.

### Local State

| State | Description |
|---|---|
| `open` / `mounted` | Modal visibility / client guard |
| `current` | `LLMSettingsResponse` (provider, model, `server_keys`, `admin_token_required`) |
| `provider` / `model` | Selection |
| `apiKey` | Optional key for the selected provider (this tab's `sessionStorage`) |
| `adminToken` | Admin token (this tab's `sessionStorage`) |
| `saving` / `error` / `success` | Request state |

### Behaviour

1. On open: `getLLMSettings()`; the gear shows the active provider as a pill.
2. Provider tabs (Groq, OpenAI, Anthropic, Gemini) and a model dropdown from `available_models`.
3. **API key** — required only when the server has no key for that provider (`keyRequired`); otherwise shown as "optional — the server has one". Keys live in `sessionStorage` (this tab only), never `localStorage`; keys saved by older versions in `localStorage` are moved over and removed.
4. **Admin token** — shown when `admin_token_required`; saved with `setAdminToken()` and sent as `X-Admin-Token` on admin calls (settings, KB delete, memory clear).
5. **Apply** — `setLLMSettings({ provider, model, api_key? })`; disabled while a required key or token is missing. Error messages from the API (401 / 403 / 400 `api_key_required`) are shown in the modal.
6. **Cancel** resets and closes.
