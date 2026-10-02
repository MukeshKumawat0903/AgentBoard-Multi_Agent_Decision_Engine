# Configuration & Project Setup

This document covers the build configuration, TypeScript setup, environment variables, and development workflow for the frontend application.

---

## Next.js Configuration

**File:** `next.config.js`

```js
const nextConfig = {
  output: "standalone",
};
```

### Standalone Output

The `output: "standalone"` setting produces a self-contained build in `.next/standalone/` that includes only the files needed to run the app. This is optimised for Docker deployments — no `node_modules` folder required in the production image. The server runs with `node .next/standalone/server.js`.

### Backend Proxy (runtime route handler)

There are **no `rewrites()`** — they are evaluated at build time, which would bake the backend URL into the image. Instead, `src/app/backend/[...path]/route.ts` handles every `/backend/*` request at **runtime** (`dynamic = "force-dynamic"`, all HTTP methods):

```ts
function backendUrl() {
  return (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
}
// GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS = proxyRequest
```

- Forwards method, body, query and safe headers (hop-by-hop headers are dropped); passes on `X-Forwarded-For` (filled by the Next.js server with the real client) and sets `X-Forwarded-Host`.
- Streams responses back, so SSE works through it.
- Forwards the browser's abort signal: closing a tab or an `EventSource` stops the upstream request (status 499 on client abort).
- Unreachable backend → an error response the client turns into "Backend unreachable. Is the server running?".

The frontend's `API_BASE` defaults to `/backend`, so the browser only ever talks to the Next.js server — no CORS, and it works from other devices on the network without code changes.

| Variable | Scope | Default | Description |
|---|---|---|---|
| `BACKEND_URL` | Server-only, read per request | `http://localhost:8000` | Where the proxy forwards (Docker Compose: `http://backend:8000`) |

The backend trusts the forwarded client address only from `TRUSTED_PROXY_IPS` (localhost by default; Docker Compose adds `172.16.0.0/12`), which gives every browser its own rate-limit quota.

---

## TypeScript Configuration

**File:** `tsconfig.json`

| Option | Value | Purpose |
|---|---|---|
| `target` | `ES2017` | Output syntax level (async/await support) |
| `module` | `esnext` | Modern ES module syntax |
| `moduleResolution` | `bundler` | Next.js-compatible module resolution |
| `jsx` | `preserve` | Leave JSX for Next.js/SWC to transform |
| `strict` | `true` | Full strict type checking |
| `noEmit` | `true` | TypeScript only type-checks; Next.js handles compilation |
| `skipLibCheck` | `true` | Skip type-checking `node_modules` declarations |
| `esModuleInterop` | `true` | Allow default imports from CJS modules |
| `resolveJsonModule` | `true` | Enable importing `.json` files |
| `isolatedModules` | `true` | Required for SWC/Next.js compilation |
| `incremental` | `true` | Faster rebuilds via `.tsbuildinfo` cache |

### Path Aliases

```json
{
  "paths": {
    "@/*": ["./src/*"]
  }
}
```

Enables `@/components/AgentCard`, `@/lib/api`, etc. instead of relative paths like `../../components/AgentCard`.

### Include / Exclude

```json
{
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

---

## Global Type Stubs

**File:** `src/types/global.d.ts`

Provides **fallback type declarations** so the IDE doesn't report errors before `npm install` is run. These are minimal stubs for:

| Module/Namespace | Stubs |
|---|---|
| `JSX` | `Element`, `IntrinsicElements` |
| `React` | `ReactNode`, `FormEvent`, `ChangeEvent<T>`, `useState`, `useEffect` |
| `"react"` | Re-exports React namespace |
| `"next/font/google"` | `Inter()` function |
| `"next/navigation"` | `useRouter()`, `useParams<T>()` |
| `process` | `env: Record<string, string \| undefined>` |
| `"next"` | `Metadata` interface |
| `"tailwindcss"` | `Config` interface |

Once `node_modules` is populated (after `npm install`), the real type declarations from `@types/react`, `@types/node`, etc. take precedence via TypeScript's module resolution.

---

## Environment Variables

| Variable | Location | Required | Default | Description |
|---|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | `.env.local` | No | `/backend` (proxy) | Override to point directly at backend (e.g. `http://localhost:8000`) |
| `BACKEND_URL` | Environment of the Next.js server (or `.env.local`) | No | `http://localhost:8000` | Server-side only — where the `/backend/*` route handler forwards; read on every request |

When `NEXT_PUBLIC_API_URL` is **not set** (the default), all API calls use the `/backend` relative path, which is proxied by Next.js. Set `NEXT_PUBLIC_API_URL` only if you need the browser to call the backend directly (bypassing the proxy).

**`.env.local` example:**

```
# Default: proxy mode (recommended)
# NEXT_PUBLIC_API_URL is not set — uses /backend proxy

# Optional: direct mode (bypasses proxy)
# NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Dependencies

### Production

| Package | Version | Purpose |
|---|---|---|
| `next` | 15.1.7 | React framework (App Router, server components, build tooling) |
| `react` | 18.3.1 | UI component library |
| `react-dom` | 18.3.1 | DOM rendering for React |
| `recharts` | ^3.8.0 | Composable charting library (LineChart, BarChart, PieChart) |
| `lucide-react` | ^1.18.0 | Icon set used across the UI |
| `react-markdown` | ^9.1.0 | Markdown renderer for decision/rationale text |
| `remark-gfm` | ^4.0.1 | GitHub-flavoured-markdown plugin for react-markdown |

### Development

| Package | Version | Purpose |
|---|---|---|
| `typescript` | 5.5.4 | Static type checking |
| `@types/node` | 20.17.0 | Node.js type definitions |
| `@types/react` | 18.3.12 | React type definitions |
| `@types/react-dom` | 18.3.4 | ReactDOM type definitions |
| `tailwindcss` | 3.4.4 | Utility-first CSS framework |
| `postcss` | 8.4.38 | CSS transformation pipeline |
| `autoprefixer` | 10.4.19 | Vendor prefix injection |
| `eslint` | 8.57.0 | JavaScript/TypeScript linter |
| `eslint-config-next` | 15.1.7 | Next.js-specific ESLint rules |
| `vitest` + `@vitest/coverage-v8` | ^4.1.8 | Unit/component test runner + coverage |
| `@vitejs/plugin-react` | ^6.0.2 | React transform for Vitest |
| `jsdom` | ^29.1.1 | DOM environment for component tests |
| `@testing-library/{react,dom,jest-dom,user-event}` | ^16 / ^10 / ^6 / ^14 | Component testing utilities |
| `@playwright/test` | ^1.60.0 | End-to-end browser testing |

Production dependencies use `^` (caret) ranges; core framework packages are pinned. Install with `npm ci --legacy-peer-deps` for deterministic installs from `package-lock.json` — plain `npm ci` fails with ERESOLVE because `@types/node` 20.17 is older than vite's optional peer range.

---

## NPM Scripts

| Script | Command | Description |
|---|---|---|
| `dev` | `next dev` | Start dev server with hot reload (default port 3000) |
| `build` | `next build` | Create optimised production build |
| `start` | `next start` | Serve the production build |
| `lint` | `next lint` | Run ESLint with Next.js rules |
| `typecheck` | `tsc --noEmit` | Type-check without emitting output |
| `test` / `test:watch` / `test:coverage` | `vitest [run] [--coverage]` | Vitest unit/component tests |
| `verify` | `npm run lint && npm run typecheck && npm test` | Full local CI gate |
| `e2e` / `e2e:ui` / `e2e:headed` | `playwright test [--ui\|--headed]` | Playwright end-to-end tests |

### Development Workflow

```bash
cd frontend

# Install dependencies (same flag as the Dockerfile and CI)
npm ci --legacy-peer-deps

# Start dev server
npm run dev
# → http://localhost:3000

# Production build
npm run build
npm start

# Quality gates
npm run lint
npm run typecheck
npm test          # Vitest unit/component tests
npm run verify    # lint + typecheck + test
npm run e2e       # Playwright end-to-end (starts `npm run dev` itself; backend calls are mocked)
```

---

## Testing Setup

- **Unit / component tests** — [Vitest](https://vitest.dev) with `@testing-library/react` in `jsdom` (`vitest.config.ts`: `@/` alias, `src/test-setup.ts` for jest-dom matchers, v8 coverage). 14 files / ~114 tests in `src/components/__tests__/`:
  - components: `AgentCard` (incl. veto badge), `CompareContent`, `ConfidenceMeter`, `DebateInput` (custom mode, default mode, template id), `FinalDecisionPanel` (reviewer direction, vetoes), `HITLPanel`, `LLMSettingsPanel`, `ThemeToggle`
  - pages: `HomePage` (agent roster rule, server default mode), `HistoryPage` (server-side sort/filter, stale responses), `AnalyticsPage`
  - logic: `debateStreamReducer`, `connectToStream` (pings, reconnect limit, status after reconnect), `apiError` (error messages)
- **End-to-end tests** — [Playwright](https://playwright.dev) specs in `e2e/` (home, debate, reconnect, HITL, history, compare, simulation, export, dark mode, errors — 71 tests). Every backend call is mocked with `page.route()` (`e2e/fixtures/mock-api.ts`); `serveOpenStream()` swaps in an `EventSource` that stays open to test in-progress UI, and the connection-lost test uses Playwright's fake clock to skip the reconnect backoff. `playwright.config.ts`: Chromium, serial, starts `npm run dev`, 1 retry in CI.
- **CI** — the `test-frontend` job in `.github/workflows/docker-publish.yml` runs `npm ci --legacy-peer-deps`, `npm run verify`, installs Chromium and runs `npm run e2e` (uploading the report on failure). Image builds depend on it.

---

## PostCSS Configuration

**File:** `postcss.config.js`

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

PostCSS runs as part of the Next.js build pipeline. It:
1. Processes `@tailwind` directives in `globals.css` via the `tailwindcss` plugin
2. Adds vendor prefixes (e.g., `-webkit-`, `-moz-`) via `autoprefixer`

---

## Build Output

### Development

`npm run dev` starts the Next.js development server with:
- Hot Module Replacement (HMR) for instant feedback
- Error overlays for compile/runtime errors
- Source maps for debugging

### Production

`npm run build` produces:
- `.next/standalone/` — Self-contained Node.js server
- `.next/static/` — Client-side JavaScript bundles, CSS, and assets
- Automatic code splitting per route
- Tailwind CSS purging (unused utility classes removed)

The standalone server can be started with:

```bash
node .next/standalone/server.js
```

---

## CORS Considerations

With the default proxy setup the browser only talks to the Next.js server (same origin), so CORS never applies. It only matters if you set `NEXT_PUBLIC_API_URL` to call the backend directly — then add the frontend's origin to the backend's `CORS_ORIGINS`:

```
# backend/.env
CORS_ORIGINS=["http://localhost:3000","http://localhost:3001"]
```
