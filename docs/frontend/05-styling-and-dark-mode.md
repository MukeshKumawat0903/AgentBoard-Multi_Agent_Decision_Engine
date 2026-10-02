# Styling & Dark Mode

The frontend uses **Tailwind CSS 3.4** for all styling — no separate CSS modules, styled-components, or CSS-in-JS. Dark mode is implemented via Tailwind's class-based strategy with `localStorage` persistence.

---

## Tailwind Configuration

**File:** `tailwind.config.ts`

```ts
import colors from "tailwindcss/colors";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Brand accent ramp — indigo, used for primary actions and highlights
        accent: colors.indigo,
        // Surface hierarchy driven by CSS variables (see globals.css)
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          raised:  "rgb(var(--surface-raised) / <alpha-value>)",
          overlay: "rgb(var(--surface-overlay) / <alpha-value>)",
        },
        // Border tokens — use as border-line / border-line-strong
        line: {
          DEFAULT: "rgb(var(--line) / <alpha-value>)",
          strong:  "rgb(var(--line-strong) / <alpha-value>)",
        },
        analyst:   { DEFAULT: "#3B82F6", light: "#DBEAFE" },
        risk:      { DEFAULT: "#EF4444", light: "#FEE2E2" },
        strategy:  { DEFAULT: "#22C55E", light: "#DCFCE7" },
        ethics:    { DEFAULT: "#A855F7", light: "#F3E8FF" },
        moderator: { DEFAULT: "#EAB308", light: "#FEF9C3" },
      },
      boxShadow: {
        card:        "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 4px 12px -4px rgb(0 0 0 / 0.08)",
        "card-hover":"0 2px 4px 0 rgb(0 0 0 / 0.05), 0 12px 24px -8px rgb(0 0 0 / 0.12)",
      },
      keyframes: { fadeIn, shake, slideUpIn, scaleIn, thinking /* … */ },
      animation: {
        fadeIn:    "fadeIn 0.2s ease-out both",
        shake:     "shake 0.3s ease-in-out",
        slideUpIn: "slideUpIn 0.35s cubic-bezier(0.21,1.02,0.73,1) both",
        scaleIn:   "scaleIn 0.3s cubic-bezier(0.21,1.02,0.73,1) both",
        thinking:  "thinking 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
```

Key settings:
- **`darkMode: "class"`** — Dark mode is toggled by adding/removing the `dark` class on `<html>`
- **Content paths** — Only scans `src/app/` and `src/components/` for Tailwind class usage (tree-shaking)
- **Semantic surface/line tokens** — The June UI refactor introduced theme-agnostic tokens driven by CSS variables: `bg-surface` / `bg-surface-raised` / `bg-surface-overlay` and `border-line` / `border-line-strong`. Components use these instead of hard-coded `bg-white dark:bg-gray-900`, so light/dark values live in one place (`globals.css`).
- **Accent ramp** — `accent` aliases Tailwind's indigo scale (`bg-accent-600`, `text-accent-500`, …) for primary actions.
- **Card shadows** — `shadow-card` / `shadow-card-hover` give a consistent elevated-card look.
- **Agent colours** — 5 custom colour scales registered as first-class Tailwind colours, usable as `bg-analyst`, `text-risk`, `border-ethics-light`, etc.
- **Custom animations** — `animate-fadeIn`, `animate-shake` (invalid-submit shake on `DebateInput`), `animate-slideUpIn` & `animate-scaleIn` (modals/cards), and `animate-thinking` (pulsing dots while agents work).

---

## PostCSS Pipeline

**File:** `postcss.config.js`

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

PostCSS processes Tailwind directives and adds vendor prefixes via autoprefixer.

---

## Global Styles

**File:** `src/app/globals.css`

### Tailwind Directives

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

### CSS Custom Properties

```css
:root {
  --agent-analyst:   #3b82f6;
  --agent-risk:      #ef4444;
  --agent-strategy:  #22c55e;
  --agent-ethics:    #a855f7;
  --agent-moderator: #eab308;

  /* Surface hierarchy (RGB triplets so Tailwind alpha works) */
  --surface:         248 250 252;  /* slate-50  — page    */
  --surface-raised:  255 255 255;  /* white     — cards   */
  --surface-overlay: 255 255 255;  /* white     — modals  */
  --line:            226 232 240;  /* slate-200 — borders */
  --line-strong:     203 213 225;  /* slate-300           */
}

.dark {
  --surface:         2 6 23;       /* slate-950 — page    */
  --surface-raised:  15 23 42;     /* slate-900 — cards   */
  --surface-overlay: 30 41 59;     /* slate-800 — modals  */
  --line:            30 41 59;     /* slate-800           */
  --line-strong:     51 65 85;     /* slate-700           */
}
```

The `--surface*` / `--line*` triplets back the `surface` and `line` Tailwind tokens (`bg-surface`, `border-line`, …). Keeping both light and dark values here means a component writes `bg-surface-raised border-line` once and gets the right colour in either theme — the elevation hierarchy (page → card → overlay) lives in one place. The `--agent-*` variables provide matching agent colours for inline-style contexts.

### Smooth Scrolling

```css
html {
  scroll-behavior: smooth;
}
```

Enables smooth scroll for anchor navigation and the auto-scroll feature in `DebateStreamViewer` (which uses `scrollIntoView({ behavior: "smooth" })`).

### Global Body Style

```css
body {
  @apply bg-surface text-gray-900 dark:text-gray-100 antialiased;
  font-feature-settings: "cv02", "cv03", "cv04", "cv11";
}
```

- **Background**: now uses the semantic `bg-surface` token (resolves to slate-50 in light, slate-950 in dark) rather than hard-coded `bg-gray-*`
- **Text**: `text-gray-900` / `dark:text-gray-100`
- **Font features**: Enables Inter's stylistic alternates for improved readability

### Accessibility & Motion

- **Focus-visible rings** — A global `:focus-visible` rule draws a 2px blue ring (lighter blue in dark mode) on keyboard focus for links, buttons, inputs, selects, textareas, and `[tabindex]` elements — visible on keyboard navigation but not mouse clicks.
- **Reduced motion** — Under `@media (prefers-reduced-motion: reduce)`, all animation/transition durations collapse to ~0 and smooth scrolling is disabled.
- **Print styles** — `@media print` hides nav/footer/`.no-print`, expands `main` to full width, forces a white background, strips shadows, keeps decision `section`s from breaking across pages, and labels charts as unavailable.
- **Confetti** — A `confetti-burst` keyframe powers a one-shot celebratory particle burst at the consensus moment (direction from per-particle `--dx`/`--dy`).

### Custom Scrollbar

```css
.custom-scroll::-webkit-scrollbar { width: 6px; }
.custom-scroll::-webkit-scrollbar-thumb {
  @apply bg-gray-300 dark:bg-gray-600 rounded-full;
}
.custom-scroll::-webkit-scrollbar-track { background: transparent; }
```

A utility class for slim scrollbars that adapt to the current theme. WebKit-only (Chrome, Edge, Safari).

---

## Dark Mode Implementation

### Architecture

The dark mode system has three layers:

1. **Inline Script** (layout.tsx `<head>`) — Runs before first paint, sets `dark` class on `<html>` based on `localStorage.theme` or system preference
2. **ThemeToggle Component** — User-facing toggle button; toggles the class and persists the choice
3. **Tailwind `dark:` Variants** — Every component uses `dark:` prefixed utility classes for dark theme styling

### Flash Prevention

```js
(function(){
  try {
    var t = localStorage.getItem('theme');
    if (t === 'dark' || (t === null && window.matchMedia('(prefers-color-scheme:dark)').matches)) {
      document.documentElement.classList.add('dark');
    }
  } catch(e) {}
})();
```

This inline script is injected via `dangerouslySetInnerHTML` in the `<head>` element and executes synchronously before the browser paints. The `suppressHydrationWarning` attribute on `<html>` prevents React hydration warnings since the server-rendered HTML may not have the `dark` class.

### Theme Persistence

| Storage | Key | Values |
|---|---|---|
| `localStorage` | `theme` | `"dark"` \| `"light"` \| absent |

When absent, the system falls back to `prefers-color-scheme: dark` media query.

### Toggle Behaviour

```
ThemeToggle.toggle()
  ├─ document.documentElement.classList.toggle("dark")
  ├─ localStorage.setItem("theme", isDark ? "dark" : "light")
  └─ setDark(isDark)  // update local React state for icon swap
```

---

## Dark Mode Colour Mapping

Every component applies `dark:` variants. Below is the comprehensive colour mapping used across the application:

### Backgrounds

| Element | Light | Dark |
|---|---|---|
| Page body | `bg-gray-50` | `dark:bg-gray-950` |
| Cards / Panels | `bg-white` | `dark:bg-gray-900` |
| Header | `bg-white/80` | `dark:bg-gray-900/80` |
| Agent cards | `bg-surface-raised` + a 4px accent rail in the agent colour | same tokens (theme-aware) |
| Input fields | `bg-white` | `dark:bg-gray-800` |
| Disabled inputs | `bg-gray-50` | `dark:bg-gray-700` |
| Error banner | `bg-red-50` | `dark:bg-red-900/30` |
| Query banner | `bg-blue-50` | (no dark override) |
| Debate trace section | `bg-gray-50` | (inherits) |

### Text

| Element | Light | Dark |
|---|---|---|
| Body text | `text-gray-900` | `dark:text-gray-100` |
| Headings | `text-gray-800` | `dark:text-gray-100` |
| Subheadings | `text-gray-700` | `dark:text-gray-300` |
| Body copy | `text-gray-600` | `dark:text-gray-400` |
| Muted text | `text-gray-400` / `text-gray-500` | `dark:text-gray-500` / `dark:text-gray-600` |
| Placeholders | `placeholder:text-gray-400` | `dark:placeholder:text-gray-500` |
| Links | `text-blue-500` | `dark:text-blue-400` |
| Error text | `text-red-700` | `dark:text-red-400` |

### Borders

| Element | Light | Dark |
|---|---|---|
| Cards | `border-gray-200` (default) | `dark:border-gray-800` |
| Header / Footer | `border-gray-200` | `dark:border-gray-800` |
| Inputs | `border-gray-300` | `dark:border-gray-600` |
| Critiques | `border-gray-200` | `dark:border-gray-700` |
| Error banner | `border-red-200` | `dark:border-red-800` |

### Badges / Pills

| Badge Type | Light | Dark |
|---|---|---|
| Round count | `bg-blue-100 text-blue-700` | `dark:bg-blue-900/40 dark:text-blue-300` |
| Termination reason | `bg-gray-100 text-gray-700` | `dark:bg-gray-700 dark:text-gray-300` |
| Risk flags | `bg-red-100 text-red-700` | `dark:bg-red-900/40 dark:text-red-300` |
| Severity: low | `bg-gray-100 text-gray-600` | `dark:bg-gray-700 dark:text-gray-300` |
| Severity: medium | `bg-yellow-100 text-yellow-800` | `dark:bg-yellow-900/40 dark:text-yellow-300` |
| Severity: high | `bg-orange-100 text-orange-800` | `dark:bg-orange-900/40 dark:text-orange-300` |
| Severity: critical | `bg-red-100 text-red-800` | `dark:bg-red-900/40 dark:text-red-300` |
| Veto badge (AgentCard) | `bg-red-600 text-white` | same |
| Veto notice / standing vetoes | `bg-red-50 ring-red-200 text-red-700` | `dark:bg-red-900/20 dark:ring-red-800 dark:text-red-300` |
| Human reviewer direction | `bg-violet-50 ring-violet-200` | `dark:bg-violet-900/20 dark:ring-violet-800` |

### Interactive Elements

| Element | Light | Dark |
|---|---|---|
| Theme toggle hover | `hover:bg-gray-100` | `dark:hover:bg-gray-800` |
| Buttons (secondary) | `hover:bg-gray-50` | `dark:hover:bg-gray-800` |
| Spinner track | `border-gray-200` | `dark:border-gray-700` |
| ConfidenceMeter track | `bg-gray-200` | `dark:bg-gray-700` |
| Scrollbar thumb | `bg-gray-300` | `dark:bg-gray-600` |

> Newer components increasingly use the semantic `bg-surface*` / `border-line*` tokens (one value per theme) instead of the hard-coded `bg-white dark:bg-gray-900` pairs listed above; both patterns currently coexist in the codebase.

---

## Agent Colour System

Each agent has a dedicated colour used consistently across components:

| Agent | Primary | Light | Usage |
|---|---|---|---|
| Analyst | `#3B82F6` (Blue) | `#DBEAFE` | Card accent rail, avatar, charts |
| Risk | `#EF4444` (Red) | `#FEE2E2` | Card accent rail, avatar, charts |
| Strategy | `#22C55E` (Green) | `#DCFCE7` | Card accent rail, avatar, charts |
| Ethics | `#A855F7` (Purple) | `#F3E8FF` | Card accent rail, avatar, charts |
| Moderator | `#EAB308` (Yellow) | `#FEF9C3` | Card accent rail, avatar, charts |
| FinancialEthics | `#F59E0B` (Amber) | `#FEF3C7` | Domain agent rail, avatar, charts |
| Security | `#6366F1` (Indigo) | `#EEF2FF` | Domain agent rail, avatar, charts |
| Compliance | `#0891B2` (Cyan) | `#CFFAFE` | Domain agent rail, avatar, charts |
| PatientSafety | `#EC4899` (Pink) | `#FCE7F3` | Domain agent rail, avatar, charts |

> Domain-agent metadata lives in `DOMAIN_AGENT_META` (keyed without spaces); the 5 core agents are in `AGENT_META`.

These colours are applied via:
1. **`agentColor(name)`** (`ui/AgentAvatar.tsx`) — inline colour for the `AgentCard` accent rail, `AgentAvatar` and critique accents (core agents from `AGENT_META`, domain agents from `DOMAIN_AGENT_META`, grey fallback)
2. **Tailwind custom colours** in `tailwind.config.ts` (available as `bg-analyst`, `text-risk`, etc.)
3. **CSS custom properties** in `globals.css` (available as `var(--agent-analyst)`, etc.)
4. **recharts colour arrays** — `AGENT_COLORS` and `PIE_COLORS` in the Analytics page supply consistent agent colours to `LineChart`, `BarChart`, and `PieChart` components. The `heatColor()` helper maps the 0–1 agreement of each agent pair to a blue (low) → green (high) ramp in the pairwise agreement matrix; pairs that never debated together get a grey "—" cell

---

## Font

The application uses **Inter** loaded via `next/font/google`:

```ts
const inter = Inter({ subsets: ["latin"] });
```

Applied to `<body className={inter.className}>`. Next.js automatically optimises font loading with self-hosting and preloading.

The `font-feature-settings` in the global CSS enables stylistic alternates (`cv02`, `cv03`, `cv04`, `cv11`) for improved character disambiguation.
