# Architecture Overview

The AgentBoard frontend is a **Next.js 15** application built with **React 18**, **TypeScript 5**, and **Tailwind CSS 3**. It provides the UI for starting multi-agent debates and following them live, and talks to the FastAPI backend through its own `/backend/*` proxy.

---

## Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Framework | Next.js (App Router, standalone output) | 15.1.7 |
| UI Library | React | 18.3.1 |
| Language | TypeScript | 5.5.4 |
| Styling | Tailwind CSS (+ PostCSS, autoprefixer) | 3.4.4 |
| Charts | recharts | ^3.8.0 |
| Icons | lucide-react | ^1.18.0 |
| Markdown | react-markdown + remark-gfm | ^9.1.0 / ^4.0.1 |
| Unit Tests | Vitest + Testing Library + jsdom | ^4.1.8 |
| E2E Tests | Playwright (Chromium) | ^1.60.0 |
| Linting | ESLint + eslint-config-next | 8.57.0 / 15.1.7 |
| Node | 20 (Docker image and CI) | — |

---

## Directory Structure

```
frontend/
├── next.config.js            # output: "standalone" (no rewrites — see the proxy below)
├── tailwind.config.ts
├── tsconfig.json             # @/* → ./src/*
├── postcss.config.js
├── vitest.config.ts          # jsdom env, @/ alias, coverage thresholds
├── playwright.config.ts      # Chromium, starts `npm run dev`, serial, 1 retry in CI
├── Dockerfile                # node:20-alpine multi-stage, npm ci --legacy-peer-deps
├── package.json / package-lock.json
├── .env.local                # NEXT_PUBLIC_API_URL left unset → proxy is used
├── e2e/                      # Playwright specs + fixtures/mock-api.ts
└── src/
    ├── test-setup.ts         # Testing-Library / jest-dom setup
    ├── app/
    │   ├── globals.css
    │   ├── layout.tsx         # Root layout: NavBar, footer, ToastProvider, theme script
    │   ├── page.tsx           # Home: New Debate workspace (form, templates, roster, recent)
    │   ├── error.tsx          # Global error boundary
    │   ├── not-found.tsx      # 404 page
    │   ├── backend/[...path]/route.ts  # Runtime proxy /backend/* → BACKEND_URL
    │   ├── debate/[threadId]/page.tsx  # Live debate viewer (+ error.tsx)
    │   ├── history/page.tsx    # History: server-side search, filter, sort, paging
    │   ├── compare/page.tsx    # Side-by-side comparison
    │   ├── simulate/page.tsx   # Scenario simulation (background job + polling)
    │   ├── knowledge/page.tsx  # Knowledge base management
    │   ├── memory/page.tsx     # Agent memory browser
    │   └── analytics/page.tsx  # Analytics dashboard
    ├── components/
    │   ├── NavBar.tsx              # Nav links, backend health dot, LLM settings, theme, shortcuts
    │   ├── SiteFooter.tsx
    │   ├── Toast.tsx               # ToastProvider + useToast
    │   ├── KeyboardShortcutsHelp.tsx
    │   ├── Skeleton.tsx            # Loading placeholders
    │   ├── ThemeToggle.tsx
    │   ├── Toggle.tsx              # Accessible switch
    │   ├── Markdown.tsx            # react-markdown + remark-gfm renderer
    │   ├── LLMSettingsPanel.tsx    # Provider/model switch (admin token, server keys)
    │   ├── DebateInput.tsx         # Query, mode (default from server), options, template id
    │   ├── LoadingState.tsx
    │   ├── DebateStreamViewer.tsx  # SSE viewer, reconnect, resume, connection-lost view, HITL
    │   ├── AgentCard.tsx           # Agent position (+ Veto badge)
    │   ├── AgentRoster.tsx         # Agent selection (≥ 2 debaters) and domain packs
    │   ├── ConfidenceMeter.tsx
    │   ├── ConfidenceDriftChart.tsx
    │   ├── CritiqueView.tsx
    │   ├── FinalDecisionPanel.tsx  # Decision, reviewer direction, vetoes, disagreements, evaluate, export
    │   ├── HITLPanel.tsx           # Approve / override / add round / cancel
    │   ├── TemplateCard.tsx
    │   ├── CompareContent.tsx
    │   ├── ui/                     # AgentAvatar, Badge, Button (+ buttonClasses), Card,
    │   │                           # CollapsibleSection, RadialGauge
    │   └── __tests__/              # Vitest component, page, reducer and API tests
    ├── lib/
    │   ├── api.ts                  # 35 API functions, SSE client, errors, admin token
    │   ├── types.ts                # API types + SSE event types
    │   ├── debateStreamReducer.ts  # Pure reducer folding SSE events into debate state
    │   └── useCountUp.ts
    └── types/global.d.ts
```

---

## How the browser reaches the backend

All API calls go to **`/backend/*`** on the frontend's own origin (`API_BASE` in `lib/api.ts`). The route handler `src/app/backend/[...path]/route.ts` forwards each request at **runtime** to `process.env.BACKEND_URL` (default `http://localhost:8000`):

- No CORS, works from any host or IP, and the same Docker image works in any environment (the URL isn't baked in at build time, which `next.config.js` rewrites would do).
- It forwards the client's abort signal, so closing a tab or an SSE stream stops the backend request (returns 499 on client abort).
- It passes on the `X-Forwarded-For` that the Next.js server fills with the real client address (plus `X-Forwarded-Host`); the backend trusts it only from `TRUSTED_PROXY_IPS`, which gives every browser its own rate-limit quota.
- If `NEXT_PUBLIC_API_URL` is set, the browser calls that URL directly instead (then CORS applies).

---

## Application Flow

### Debate (async streaming)

```
Home page (/)
  ├─ Loads templates, domain packs, recent debates, agents and the server's
  │  default mode (GET /debate-modes → pre-selects it; Quick if unavailable)
  ├─ User types a query (or picks a template / starter chip → template_id),
  │  picks a mode, agents (≥ 2 besides the Moderator), KB / memory / supervised
  ├─ startDebateAsync() → POST /debate/start-async → { thread_id, stream_url }
  └─ router.push(`/debate/${thread_id}`)

Debate page (/debate/[threadId]) → DebateStreamViewer
  ├─ REST check first: getHistoryItem(id) — a finished debate loads its stored
  │  decision directly (no live stream needed)
  ├─ connectToStream(): EventSource on /debate/{id}/stream
  │    debate_started · round_started · phase_started · agent_output (veto)
  │    tool_called · critique_completed · synthesis · agent_timeout
  │    approval_required (HITL) · debate_resumed · debate_completed
  │    final_decision · cancelled · error · ping (keep-alive)
  ├─ Reconnects with backoff 1 s → 30 s, resuming after the last event id;
  │  status badge: Connected / Reconnecting… / Disconnected
  ├─ After 10 failed reconnects: "Connection lost" view with an in-place
  │  Reconnect (the debate may still be running on the server)
  ├─ Supervised: HITLPanel → approveDebate() (202), the stream continues
  ├─ Failed but resumable: "Resume debate" → resumeDebateAsync() (202)
  ├─ Stop: cancelDebate() (also ends a paused debate)
  └─ Done: FinalDecisionPanel — reviewer direction, standing vetoes,
     disagreements, evaluate (LLM-as-judge), export Markdown/PDF/JSON, copy
```

### History & Compare

```
History (/history)
  ├─ getHistory({ page, limit, q, sort, termination_reason })
  │  — search, filter and sort run on the server over the whole history
  ├─ Out-of-order responses are ignored (only the latest request updates the page)
  ├─ "View" / "Compare" are links (open in a new tab works)
  └─ Compare → /compare?a={id}

Compare (/compare?a=&b=)
  └─ Fetches both decisions via getHistoryItem() and renders them side by side
```

### Simulation

```
Simulate (/simulate)
  ├─ Pre-selects the server's default mode (Quick until loaded or if unavailable)
  ├─ startSimulation() → POST /debate/simulate-async → job id (202)
  ├─ Polls getSimulationJob(id) every 2 s until completed / failed / cancelled
  ├─ Cancel button → cancelSimulationJob(id); leaving the page also cancels
  └─ Shows stability rating, consistency, variance, stable risk flags, per-run results
```

### Knowledge Base, Memory, Analytics

```
Knowledge (/knowledge)  list · upload (.pdf/.txt/.md, size-limited) · delete (admin)
Memory (/memory)        per-agent lessons for the 9 agents · clear (admin)
Analytics (/analytics)  range filter; Overview (KPIs, completed debates per day, terminations),
                        Agents (confidence, contribution, symmetric position-agreement matrix),
                        Quality (scores by template, mode, domain pack)
```

Admin calls (`setLLMSettings`, `deleteKnowledgeDocument`, `clearAgentMemory`) send the `X-Admin-Token` header from `sessionStorage` when one was entered in the LLM settings panel.

---

## Key Design Decisions

### Next.js App Router

- The root layout (`layout.tsx`) is a Server Component: metadata, fonts, page shell, `NavBar`, footer and `ToastProvider`.
- Pages and interactive components are Client Components (`"use client"`).

### Standalone Output

`output: "standalone"` produces a self-contained server for the Docker image.

### Path Aliases

`@/*` → `./src/*` (`@/components/AgentCard`, `@/lib/api`).

### Real-time streaming

`POST /debate/start-async` returns at once; the page follows the debate through Server-Sent Events. `connectToStream()` handles keep-alive pings, the 60 s stale-connection timer, Last-Event-ID resume and capped exponential backoff.

### State Management

No external state library:
- **`useReducer`** — `DebateStreamViewer` uses the pure `lib/debateStreamReducer.ts` (rounds, outputs, critiques, tool calls, approvals, errors), unit-tested in isolation.
- **`useState` / `useEffect` / `useRef`** — page state, side effects, latest-request guards.
- **`localStorage`** — theme and small UI preferences.
- **`sessionStorage`** — user-supplied LLM API keys and the admin token (this tab only; never `localStorage`).
- **URL search params** — `/compare?a=&b=`, `/simulate?query=`.

---

## Environment Variables

| Variable | Where | Description |
|---|---|---|
| `BACKEND_URL` | Next.js server (runtime) | Where the `/backend/*` proxy forwards (default `http://localhost:8000`; Docker Compose: `http://backend:8000`) |
| `NEXT_PUBLIC_API_URL` | `.env.local` (build time) | Optional: call the backend directly instead of via the proxy. Leave unset normally |

---

## NPM Scripts

| Script | Command | Description |
|---|---|---|
| `dev` | `next dev` | Development server |
| `build` | `next build` | Production build |
| `start` | `next start` | Serve the production build |
| `lint` | `next lint` | ESLint |
| `typecheck` | `tsc --noEmit` | Type check |
| `test` / `test:watch` / `test:coverage` | `vitest …` | Unit / component tests |
| `verify` | `lint && typecheck && test` | Local gate (also run in CI) |
| `e2e` / `e2e:ui` / `e2e:headed` | `playwright test …` | End-to-end tests (also run in CI) |

Install with `npm ci --legacy-peer-deps` (the same flag as the Dockerfile and CI: `@types/node` is older than vite's optional peer range).
