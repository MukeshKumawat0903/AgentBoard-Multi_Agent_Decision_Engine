/**
 * LLMSettingsPanel – gear-icon button + modal to switch the active LLM
 * provider and model at runtime.
 *
 * - Groq  (default): uses the server-configured API key; no key needed from the user.
 * - OpenAI / Anthropic: user must supply their own API key.
 *   Keys are stored in localStorage for convenience and sent to the backend
 *   (in-memory only — never persisted to disk on the server).
 */

"use client";

import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { getLLMSettings, setLLMSettings } from "@/lib/api";
import { PROVIDER_MODELS } from "@/lib/types";
import type { LLMProvider, LLMSettingsResponse } from "@/lib/types";

// ------------------------------------------------------------------ //
// Provider metadata
// ------------------------------------------------------------------ //

const PROVIDERS: {
  id: LLMProvider;
  label: string;
  badge: string;
  badgeClass: string;
  needsKey: boolean;
  keyPlaceholder: string;
  hint: string;
}[] = [
  {
    id: "groq",
    label: "Groq",
    badge: "Default",
    badgeClass:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
    needsKey: false,
    keyPlaceholder: "",
    hint: "Uses the server-configured Groq key — no setup needed.",
  },
  {
    id: "openai",
    label: "OpenAI",
    badge: "Your key",
    badgeClass:
      "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
    needsKey: true,
    keyPlaceholder: "sk-...",
    hint: "Bring your own OpenAI API key. Stored in browser localStorage only.",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    badge: "Your key",
    badgeClass:
      "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300",
    needsKey: true,
    keyPlaceholder: "sk-ant-...",
    hint: "Bring your own Anthropic API key. Stored in browser localStorage only.",
  },
];

// ------------------------------------------------------------------ //
// Local-storage helpers
// ------------------------------------------------------------------ //

function loadSavedKey(provider: LLMProvider): string {
  try {
    return localStorage.getItem(`llm_api_key_${provider}`) ?? "";
  } catch {
    return "";
  }
}

function saveKey(provider: LLMProvider, key: string) {
  try {
    if (key) {
      localStorage.setItem(`llm_api_key_${provider}`, key);
    } else {
      localStorage.removeItem(`llm_api_key_${provider}`);
    }
  } catch {
    // localStorage unavailable — ignore
  }
}

// ------------------------------------------------------------------ //
// Component
// ------------------------------------------------------------------ //

export default function LLMSettingsPanel() {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [current, setCurrent] = useState<LLMSettingsResponse | null>(null);

  // Form state
  const [provider, setProvider] = useState<LLMProvider>("groq");
  const [model, setModel] = useState<string>(PROVIDER_MODELS.groq[0]);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);

  // UI state
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const panelRef = useRef<HTMLDivElement>(null);

  // Needed so createPortal only runs client-side (document exists)
  useEffect(() => { setMounted(true); }, []);

  // Fetch current settings when panel first opens
  useEffect(() => {
    if (!open) return;
    getLLMSettings()
      .then((s) => {
        setCurrent(s);
        setProvider(s.provider);
        setModel(s.model);
        setApiKey(loadSavedKey(s.provider));
        setError(null);
      })
      .catch(() => {
        // Backend unreachable — fall back to Groq defaults silently
      });
  }, [open]);

  // When provider tab changes: switch model to first available + load saved key
  useEffect(() => {
    setModel(PROVIDER_MODELS[provider][0]);
    setApiKey(loadSavedKey(provider));
    setError(null);
    setSaved(false);
  }, [provider]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  async function handleApply() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await setLLMSettings({
        provider,
        model,
        ...(provider !== "groq" && apiKey ? { api_key: apiKey } : {}),
      });
      if (provider !== "groq") saveKey(provider, apiKey);
      setCurrent(res);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "Failed to update settings.";
      // Try to surface the backend validation detail
      const body = (err as { body?: { detail?: string } })?.body;
      setError(body?.detail ?? msg);
    } finally {
      setSaving(false);
    }
  }

  const providerMeta = PROVIDERS.find((p) => p.id === provider)!;
  const currentProviderMeta = current
    ? PROVIDERS.find((p) => p.id === current.provider)
    : null;

  return (
    <>
      {/* ---- Trigger button ---- */}
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="LLM provider settings"
        title="Switch LLM provider"
        className="relative flex items-center gap-1.5 px-2 py-1.5 rounded-lg
                   text-gray-500 dark:text-gray-400
                   hover:bg-gray-100 dark:hover:bg-gray-800 transition"
      >
        {/* Gear icon */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="w-4 h-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
          />
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
          />
        </svg>

        {/* Active provider pill */}
        {currentProviderMeta && (
          <span
            className={`hidden sm:inline text-xs font-medium px-1.5 py-0.5 rounded-full ${currentProviderMeta.badgeClass}`}
          >
            {currentProviderMeta.label}
          </span>
        )}
      </button>

      {/* ---- Modal overlay — rendered via portal to escape header stacking context ---- */}
      {mounted && open && createPortal(
        <div className="fixed inset-0 z-[9999] flex items-start justify-center pt-20 px-4 pb-8 bg-black/50 backdrop-blur-sm overflow-y-auto custom-scroll">
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="llm-settings-title"
            className="w-full max-w-md bg-surface-raised rounded-2xl shadow-2xl
                       border border-line flex flex-col"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-gray-800">
              <div>
                <h2
                  id="llm-settings-title"
                  className="text-base font-semibold text-gray-800 dark:text-gray-100"
                >
                  LLM Provider
                </h2>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  Choose which AI model powers the debate agents
                </p>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100
                           dark:hover:bg-gray-800 transition"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="w-4 h-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>

            {/* Provider tabs */}
            <div className="px-5 pt-4">
              <div className="flex gap-2">
                {PROVIDERS.map((p) => {
                  const isActive = provider === p.id;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setProvider(p.id)}
                      className={`flex-1 flex flex-col items-center py-3 px-2 rounded-xl border text-sm
                                  font-medium transition
                                  ${
                                    isActive
                                      ? "border-accent-500 bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-300"
                                      : "border-line text-gray-600 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-500"
                                  }`}
                    >
                      <span className="font-semibold">{p.label}</span>
                      <span
                        className={`mt-1 text-xs px-1.5 py-0.5 rounded-full ${p.badgeClass}`}
                      >
                        {p.badge}
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* Provider hint */}
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                {providerMeta.hint}
              </p>
            </div>

            {/* Model selector */}
            <div className="px-5 pt-4">
              <label
                htmlFor="model-select"
                className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1"
              >
                Model
              </label>
              <select
                id="model-select"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-line
                           bg-surface-raised text-sm text-gray-800 dark:text-gray-200
                           focus:outline-none focus:ring-2 focus:ring-accent-500"
              >
                {PROVIDER_MODELS[provider].map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>

            {/* API key input (only for non-Groq) */}
            {providerMeta.needsKey && (
              <div className="px-5 pt-4">
                <label
                  htmlFor="api-key-input"
                  className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1"
                >
                  {providerMeta.label} API Key{" "}
                  <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <input
                    id="api-key-input"
                    type={showKey ? "text" : "password"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={providerMeta.keyPlaceholder}
                    autoComplete="off"
                    spellCheck={false}
                    className="w-full px-3 py-2 pr-10 rounded-lg border border-line
                               bg-surface-raised text-sm text-gray-800 dark:text-gray-200
                               focus:outline-none focus:ring-2 focus:ring-accent-500
                               placeholder:text-gray-400 font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey((v) => !v)}
                    tabIndex={-1}
                    aria-label={showKey ? "Hide API key" : "Show API key"}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2
                               text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
                  >
                    {showKey ? (
                      // Eye-off
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="w-4 h-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                        />
                      </svg>
                    ) : (
                      // Eye
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="w-4 h-4"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                        />
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                        />
                      </svg>
                    )}
                  </button>
                </div>
                <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                  ⚠ Saved to browser localStorage. Never shared with third parties.
                </p>
              </div>
            )}

            {/* Error / success banner */}
            {error && (
              <div className="mx-5 mt-4 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-900/30
                              border border-red-200 dark:border-red-700
                              text-xs text-red-700 dark:text-red-300">
                {error}
              </div>
            )}
            {saved && (
              <div className="mx-5 mt-4 px-3 py-2 rounded-lg bg-emerald-50 dark:bg-emerald-900/30
                              border border-emerald-200 dark:border-emerald-700
                              text-xs text-emerald-700 dark:text-emerald-300">
                ✓ Provider switched to <strong>{provider}</strong> · {model}
              </div>
            )}

            {/* Footer */}
            <div className="flex items-center justify-between px-5 py-4 mt-4
                            border-t border-gray-100 dark:border-gray-800">
              {/* Current active provider */}
              {current && (
                <p className="text-xs text-gray-400 dark:text-gray-500">
                  Active:{" "}
                  <span className="font-medium text-gray-600 dark:text-gray-300">
                    {current.provider} / {current.model}
                  </span>
                </p>
              )}

              <div className="flex gap-2 ml-auto">
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="px-4 py-2 text-sm rounded-lg border border-line
                             text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleApply}
                  disabled={
                    saving ||
                    (providerMeta.needsKey && !apiKey.trim())
                  }
                  className="px-4 py-2 text-sm rounded-lg font-medium
                             bg-accent-600 hover:bg-accent-700 disabled:opacity-50
                             text-white transition"
                >
                  {saving ? "Applying…" : "Apply"}
                </button>
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
