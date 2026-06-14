/**
 * NavBar – sticky top navigation bar (client component).
 *
 * Features:
 * - Skip-to-content accessibility link (Phase 1, item 3)
 * - Active route highlighting via usePathname() (Phase 1, item 2)
 * - Collapsible hamburger menu for mobile (Phase 1, item 1)
 * - Closes mobile menu on route change
 * - `?` global shortcut opens keyboard shortcuts overlay (Phase 6, item 16)
 * - Backend health indicator dot polling every 30s (Phase 7, item 19)
 */

"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, Menu, Network, X } from "lucide-react";
import LLMSettingsPanel from "@/components/LLMSettingsPanel";
import ThemeToggle from "@/components/ThemeToggle";
import KeyboardShortcutsHelp from "@/components/KeyboardShortcutsHelp";
import { healthCheck } from "@/lib/api";

const PRIMARY_LINKS = [
  { href: "/",        label: "New Debate" },
  { href: "/history", label: "History"    },
] as const;

const TOOL_LINKS = [
  { href: "/compare",   label: "Compare"   },
  { href: "/simulate",  label: "Simulate"  },
  { href: "/knowledge", label: "Knowledge" },
  { href: "/memory",    label: "Memory"    },
  { href: "/analytics", label: "Analytics" },
] as const;

// Mobile menu keeps the flat list.
const NAV_LINKS = [...PRIMARY_LINKS, ...TOOL_LINKS];

export default function NavBar() {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const toolsRef = useRef<HTMLDivElement>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [healthStatus, setHealthStatus] = useState<"loading" | "ok" | "error">("loading");

  // Close menus whenever the route changes
  useEffect(() => {
    setMenuOpen(false);
    setToolsOpen(false);
  }, [pathname]);

  // Close the Tools dropdown on outside click
  useEffect(() => {
    if (!toolsOpen) return;
    function onPointerDown(e: PointerEvent) {
      if (toolsRef.current && !toolsRef.current.contains(e.target as Node)) {
        setToolsOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [toolsOpen]);

  // Close menus on Escape key
  useEffect(() => {
    if (!menuOpen && !toolsOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setMenuOpen(false);
        setToolsOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [menuOpen, toolsOpen]);

  // `?` global shortcut — ignored when focus is inside an input/textarea/select
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (document.activeElement?.tagName ?? "").toLowerCase();
      if (["input", "textarea", "select"].includes(tag)) return;
      if (e.key === "?") {
        e.preventDefault();
        setHelpOpen(true);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Backend health check with exponential backoff.
  // On success: poll every 30 s.
  // On failure: back off x2 each time (30 s → 60 s → 120 s … capped at 5 min).
  // Recovers immediately on next success.
  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;

    const BASE_INTERVAL = 30_000;
    const MAX_INTERVAL  = 300_000; // 5 min
    let interval = BASE_INTERVAL;

    async function check() {
      try {
        await healthCheck();
        if (cancelled) return;
        setHealthStatus("ok");
        interval = BASE_INTERVAL; // reset on success
      } catch {
        if (cancelled) return;
        setHealthStatus("error");
        interval = Math.min(interval * 2, MAX_INTERVAL); // back off on failure
      }
      if (!cancelled) {
        timeoutId = setTimeout(check, interval);
      }
    }

    check();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  function isActive(href: string) {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
  }

  const linkBase =
    "text-sm transition px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500";
  const activeClass =
    "text-accent-600 dark:text-accent-400 font-medium underline underline-offset-4";
  const inactiveClass =
    "text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100";

  return (
    <>
      {/* ---------------------------------------------------------------- */}
      {/* Skip-to-content link (visually hidden until focused)              */}
      {/* ---------------------------------------------------------------- */}
      <a
        href="#main-content"
        className="
          sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2
          z-[100] rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300
        "
      >
        Skip to content
      </a>

      {/* ---------------------------------------------------------------- */}
      {/* Sticky header                                                     */}
      {/* ---------------------------------------------------------------- */}
      <header className="sticky top-0 z-50 bg-surface-raised/80 backdrop-blur border-b border-line">
        <div className="max-w-6xl mx-auto px-4 h-12 flex items-center justify-between">
          {/* Logo + health dot */}
          <Link
            href="/"
            className="flex items-center gap-2 font-bold text-gray-800 dark:text-gray-100
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 rounded"
          >
            <span
              aria-hidden="true"
              className="w-7 h-7 rounded-lg bg-gradient-to-br from-accent-500 to-violet-600 flex items-center justify-center text-white shadow-sm"
            >
              <Network className="w-4 h-4" strokeWidth={2.25} />
            </span>
            <span className="tracking-tight">AgentBoard</span>
            {/* Backend connection indicator */}
            <span
              aria-label={
                healthStatus === "ok"
                  ? "Backend connected"
                  : healthStatus === "error"
                  ? "Backend unreachable"
                  : "Checking backend…"
              }
              title={
                healthStatus === "ok"
                  ? "Backend connected"
                  : healthStatus === "error"
                  ? "Backend unreachable"
                  : "Checking backend…"
              }
              className={`w-2 h-2 rounded-full inline-block ml-0.5 ${
                healthStatus === "ok"
                  ? "bg-green-500"
                  : healthStatus === "error"
                  ? "bg-red-500"
                  : "bg-gray-400 animate-pulse"
              }`}
            />
          </Link>

          {/* Desktop nav */}
          <nav
            aria-label="Main navigation"
            className="hidden sm:flex items-center gap-1 sm:gap-2"
          >
            {PRIMARY_LINKS.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                aria-current={isActive(href) ? "page" : undefined}
                className={`${linkBase} ${isActive(href) ? activeClass : inactiveClass}`}
              >
                {label}
              </Link>
            ))}
            {/* Tools dropdown */}
            <div className="relative" ref={toolsRef}>
              <button
                type="button"
                onClick={() => setToolsOpen((v) => !v)}
                aria-expanded={toolsOpen}
                aria-haspopup="menu"
                className={`${linkBase} inline-flex items-center gap-1 ${
                  TOOL_LINKS.some(({ href }) => isActive(href)) ? activeClass : inactiveClass
                }`}
              >
                Tools
                <ChevronDown
                  className={`w-3.5 h-3.5 transition-transform duration-200 ${toolsOpen ? "rotate-180" : ""}`}
                  aria-hidden="true"
                />
              </button>
              {toolsOpen && (
                <div
                  role="menu"
                  className="absolute right-0 top-full mt-2 w-44 py-1.5 rounded-xl bg-surface-overlay
                             ring-1 ring-black/5 dark:ring-white/10 shadow-card-hover animate-fadeIn"
                >
                  {TOOL_LINKS.map(({ href, label }) => (
                    <Link
                      key={href}
                      href={href}
                      role="menuitem"
                      aria-current={isActive(href) ? "page" : undefined}
                      className={`block px-4 py-2 text-sm transition ${
                        isActive(href)
                          ? "text-accent-600 dark:text-accent-400 font-medium bg-accent-50 dark:bg-accent-900/20"
                          : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
                      }`}
                    >
                      {label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
            <LLMSettingsPanel />
            <ThemeToggle />
            {/* Keyboard shortcuts hint button */}
            <button
              type="button"
              onClick={() => setHelpOpen(true)}
              aria-label="Show keyboard shortcuts (?)"
              title="Keyboard shortcuts"
              className="
                p-1.5 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-200
                hover:bg-gray-100 dark:hover:bg-gray-800 transition text-xs font-mono
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
              "
            >
              ?
            </button>
          </nav>

          {/* Mobile: icons + hamburger */}
          <div className="flex sm:hidden items-center gap-1">
            <LLMSettingsPanel />
            <ThemeToggle />
            <button
              type="button"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              aria-controls="mobile-menu"
              onClick={() => setMenuOpen((v) => !v)}
              className="
                p-2 rounded text-gray-500 dark:text-gray-400
                hover:text-gray-800 dark:hover:text-gray-100
                hover:bg-gray-100 dark:hover:bg-gray-800
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500
                transition
              "
            >
              {menuOpen ? (
                <X className="w-5 h-5" aria-hidden="true" />
              ) : (
                <Menu className="w-5 h-5" aria-hidden="true" />
              )}
            </button>
          </div>
        </div>

        {/* Mobile dropdown menu */}
        {menuOpen && (
          <div
            id="mobile-menu"
            role="navigation"
            aria-label="Mobile navigation"
            className="sm:hidden border-t border-line bg-surface-raised/95 backdrop-blur"
          >
            <nav className="max-w-6xl mx-auto px-4 py-3 flex flex-col gap-1">
              {NAV_LINKS.map(({ href, label }) => (
                <Link
                  key={href}
                  href={href}
                  aria-current={isActive(href) ? "page" : undefined}
                  className={`
                    block px-3 py-2 rounded-lg text-sm font-medium transition
                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500
                    ${
                      isActive(href)
                        ? "bg-accent-50 dark:bg-accent-900/30 text-accent-600 dark:text-accent-400"
                        : "text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
                    }
                  `}
                >
                  {label}
                </Link>
              ))}
            </nav>
          </div>
        )}
      </header>
      <KeyboardShortcutsHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
    </>
  );
}
