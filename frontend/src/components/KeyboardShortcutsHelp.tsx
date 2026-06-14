/**
 * KeyboardShortcutsHelp – modal that lists all available keyboard shortcuts.
 *
 * - Press `?` globally to open (ignored when focus is inside input/textarea/select).
 * - Press `Escape` or click the backdrop to close.
 * - Focus is trapped inside the modal while open.
 * - Rendered via createPortal so it sits above everything.
 */

"use client";

import { useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";

const SHORTCUTS: { key: string; description: string }[] = [
  { key: "?",   description: "Show this keyboard shortcuts overlay" },
  { key: "Esc", description: "Close modal / cancel current action" },
  { key: "J",   description: "Focus next debate in History list" },
  { key: "K",   description: "Focus previous debate in History list" },
  { key: "N",   description: "Go to New Debate (homepage)" },
  { key: "H",   description: "Go to History" },
  { key: "A",   description: "Go to Analytics" },
  { key: "M",   description: "Go to Memory" },
  { key: "S",   description: "Go to Simulate" },
];

interface KeyboardShortcutsHelpProps {
  open: boolean;
  onClose: () => void;
}

export default function KeyboardShortcutsHelp({
  open,
  onClose,
}: KeyboardShortcutsHelpProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  /* ---- Focus trap ---- */
  const trapFocus = useCallback(
    (e: KeyboardEvent) => {
      if (!open || !panelRef.current) return;

      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }

      if (e.key !== "Tab") return;

      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute("disabled"));

      if (focusable.length === 0) {
        e.preventDefault();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (e.shiftKey) {
        if (active === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [open, onClose],
  );

  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", trapFocus);
    // Move focus into modal when it opens
    const closeBtn = panelRef.current?.querySelector<HTMLElement>("[data-close]");
    closeBtn?.focus();
    return () => document.removeEventListener("keydown", trapFocus);
  }, [open, trapFocus]);

  /* ---- Prevent body scroll while open ---- */
  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  if (!open) return null;

  const modal = (
    /* Backdrop */
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      className="fixed inset-0 z-[9998] flex items-center justify-center p-4"
    >
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        ref={panelRef}
        className="relative z-[1] w-full max-w-sm rounded-2xl bg-surface-raised
                   border border-line shadow-xl animate-fadeIn overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-line">
          <h2 className="font-semibold text-gray-800 dark:text-gray-100 text-base">
            Keyboard Shortcuts
          </h2>
          <button
            data-close
            type="button"
            onClick={onClose}
            aria-label="Close shortcuts overlay"
            className="p-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200
                       hover:bg-gray-100 dark:hover:bg-gray-800 transition
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Shortcut list */}
        <ul className="px-5 py-4 space-y-2">
          {SHORTCUTS.map(({ key, description }) => (
            <li key={key} className="flex items-center justify-between gap-4">
              <span className="text-sm text-gray-600 dark:text-gray-400">{description}</span>
              <kbd
                className="shrink-0 inline-flex items-center px-2 py-0.5 rounded border border-gray-300
                           dark:border-gray-600 bg-gray-50 dark:bg-gray-800 text-xs font-mono
                           text-gray-700 dark:text-gray-300 shadow-sm"
              >
                {key}
              </kbd>
            </li>
          ))}
        </ul>

        {/* Footer hint */}
        <div className="px-5 py-3 bg-gray-50 dark:bg-gray-800/50 border-t border-line">
          <p className="text-xs text-gray-400 dark:text-gray-500 text-center">
            Shortcuts are disabled when an input is focused.
          </p>
        </div>
      </div>
    </div>
  );

  return createPortal(modal, document.body);
}
