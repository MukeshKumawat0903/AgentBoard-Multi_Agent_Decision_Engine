/**
 * Toast – global notification system.
 *
 * Provides a ToastProvider context + portal that renders stacked
 * notifications at the bottom-right of the screen. Supports success /
 * error / info variants, auto-dismisses after 5 s, and caps at 3 toasts.
 *
 * Usage:
 *   1. Wrap your app with <ToastProvider> in layout.tsx.
 *   2. Call useToast().showToast("message", "success") from any client component.
 */

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

// ------------------------------------------------------------------ //
// Types & constants
// ------------------------------------------------------------------ //

export type ToastVariant = "success" | "error" | "info";

interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  showToast: (message: string, variant?: ToastVariant) => void;
}

const MAX_TOASTS = 3;
const DISMISS_AFTER_MS = 5000;

const VARIANT_STYLES: Record<ToastVariant, string> = {
  success: "bg-green-600 dark:bg-green-700",
  error:   "bg-red-600   dark:bg-red-700",
  info:    "bg-accent-600  dark:bg-blue-700",
};

const VARIANT_ICONS: Record<ToastVariant, string> = {
  success: "✓",
  error:   "✕",
  info:    "ℹ",
};

// ------------------------------------------------------------------ //
// Context
// ------------------------------------------------------------------ //

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}

// ------------------------------------------------------------------ //
// Single toast item
// ------------------------------------------------------------------ //

function SingleToast({
  toast,
  onDismiss,
}: {
  toast: ToastItem;
  onDismiss: () => void;
}) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(onDismiss, DISMISS_AFTER_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [onDismiss]);

  return (
    <div
      role="status"
      className={`flex items-start gap-3 min-w-[280px] max-w-sm px-4 py-3 rounded-lg shadow-lg
                  text-sm text-white animate-fadeIn ${VARIANT_STYLES[toast.variant]}`}
    >
      <span className="shrink-0 font-bold text-base leading-none mt-0.5" aria-hidden="true">
        {VARIANT_ICONS[toast.variant]}
      </span>
      <span className="flex-1 leading-snug">{toast.message}</span>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="shrink-0 opacity-70 hover:opacity-100 transition text-lg leading-none"
      >
        ×
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ //
// Provider
// ------------------------------------------------------------------ //

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [mounted, setMounted] = useState(false);

  // Avoid SSR/hydration mismatch — only render portal after mount.
  useEffect(() => {
    setMounted(true);
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, variant: ToastVariant = "info") => {
      const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setToasts((prev) => {
        const next = [...prev, { id, message, variant }];
        // Cap at MAX_TOASTS — drop the oldest if over the limit.
        return next.length > MAX_TOASTS ? next.slice(-MAX_TOASTS) : next;
      });
    },
    [],
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {mounted &&
        createPortal(
          <div
            aria-live="polite"
            aria-label="Notifications"
            className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2 items-end pointer-events-none"
          >
            {toasts.map((toast) => (
              <div key={toast.id} className="pointer-events-auto">
                <SingleToast toast={toast} onDismiss={() => dismiss(toast.id)} />
              </div>
            ))}
          </div>,
          document.body,
        )}
    </ToastContext.Provider>
  );
}
