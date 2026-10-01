/**
 * LLMSettingsPanel – gear-icon button + modal to switch the active LLM
 * provider and model at runtime.
 *
 * - A provider with a key configured on the server needs no key from the user;
 *   otherwise the user supplies one. Keys are kept in sessionStorage (this tab
 *   only) and sent to the backend, which holds them in memory only.
 * - Switching changes the provider for every user of the deployment, so the
 *   backend may require the admin token (shown here when it does).
 */

"use client";

import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Eye, EyeOff, Settings, X } from "lucide-react";
import { getAdminToken, getLLMSettings, setAdminToken, setLLMSettings } from "@/lib/api";
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
    hint: "Use your own OpenAI API key unless the server has one configured.",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    badge: "Your key",
    badgeClass:
      "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300",
    needsKey: true,
    keyPlaceholder: "sk-ant-...",
    hint: "Use your own Anthropic API key unless the server has one configured.",
  },
  {
    id: "gemini",
    label: "Gemini",
    badge: "Your key",
    badgeClass:
      "bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300",
    needsKey: true,
    keyPlaceholder: "AIza...",
    hint: "Use your own Google AI Studio API key unless the server has one configured.",
  },
];

// ------------------------------------------------------------------ //
// Key storage — sessionStorage (this tab only), never localStorage
// ------------------------------------------------------------------ //

function storageKey(provider: LLMProvider): string {
  return `llm_api_key_${provider}`;
}

function loadSavedKey(provider: LLMProvider): string {
  try {
    // Keys saved by older versions lived in localStorage (on disk); move them
    // into this tab's session and delete the persistent copy.
    const legacy = localStorage.getItem(storageKey(provider));
    if (legacy !== null) {
      localStorage.removeItem(storageKey(provider));
      if (!sessionStorage.getItem(storageKey(provider))) {
        sessionStorage.setItem(storageKey(provider), legacy);
      }
    }
    return sessionStorage.getItem(storageKey(provider)) ?? "";
  } catch {
    return "";
  }
}

function saveKey(provider: LLMProvider, key: string) {
  try {
    if (key) {
      sessionStorage.setItem(storageKey(provider), key);
    } else {
      sessionStorage.removeItem(storageKey(provider));
    }
  } catch {
    // storage unavailable — ignore
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
  const [adminToken, setAdminTokenInput] = useState("");

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
        setAdminTokenInput(getAdminToken());
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
      if (current?.admin_token_required) setAdminToken(adminToken.trim());
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
      // ApiError already turns every backend error shape into readable text.
      setError(err instanceof Error ? err.message : "Failed to update settings.");
    } finally {
      setSaving(false);
    }
  }

  const providerMeta = PROVIDERS.find((p) => p.id === provider)!;
  // A user key is only required when the server has none for this provider.
  const keyRequired = providerMeta.needsKey && !current?.server_keys?.[provider];
  const tokenRequired = Boolean(current?.admin_token_required);
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
        <Settings className="w-4 h-4" aria-hidden="true" />

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
                <X className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>

            {/* Provider tabs */}
            <div className="px-5 pt-4">
              <div className="grid grid-cols-2 gap-2">
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
                  {keyRequired ? (
                    <span className="text-red-500">*</span>
                  ) : (
                    <span className="text-gray-400">(optional — the server has one)</span>
                  )}
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
                      <EyeOff className="w-4 h-4" aria-hidden="true" />
                    ) : (
                      <Eye className="w-4 h-4" aria-hidden="true" />
                    )}
                  </button>
                </div>
                <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                  ⚠ Kept for this browser tab only. Switching applies to every user of this server.
                </p>
              </div>
            )}

            {/* Admin token (when the server requires one to switch providers) */}
            {tokenRequired && (
              <div className="px-5 pt-4">
                <label
                  htmlFor="admin-token-input"
                  className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1"
                >
                  Admin token <span className="text-red-500">*</span>
                </label>
                <input
                  id="admin-token-input"
                  type="password"
                  value={adminToken}
                  onChange={(e) => setAdminTokenInput(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  className="w-full px-3 py-2 rounded-lg border border-line
                             bg-surface-raised text-sm text-gray-800 dark:text-gray-200
                             focus:outline-none focus:ring-2 focus:ring-accent-500 font-mono"
                />
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
                    (keyRequired && !apiKey.trim()) ||
                    (tokenRequired && !adminToken.trim())
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
