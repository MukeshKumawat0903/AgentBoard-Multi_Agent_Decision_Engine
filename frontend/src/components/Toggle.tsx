/**
 * Toggle – a dark-theme on/off switch.
 *
 * Renders a real (visually hidden) checkbox so it keeps the native
 * `checkbox` role, label association, and keyboard behaviour, while the
 * custom track/thumb are driven by Tailwind `peer-*` utilities.
 */

"use client";

import type { ChangeEvent } from "react";

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  id?: string;
}

export default function Toggle({ checked, onChange, disabled, id }: ToggleProps) {
  return (
    <span className="relative inline-flex shrink-0 items-center">
      <input
        type="checkbox"
        id={id}
        checked={checked}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.checked)}
        disabled={disabled}
        className="peer sr-only"
      />
      {/* Track */}
      <span
        aria-hidden="true"
        className="block h-5 w-9 rounded-full bg-gray-300 dark:bg-gray-600 transition-colors
                   peer-checked:bg-accent-600
                   peer-focus-visible:ring-2 peer-focus-visible:ring-blue-400 peer-focus-visible:ring-offset-1
                   peer-disabled:opacity-50 peer-disabled:cursor-not-allowed"
      />
      {/* Thumb */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow-sm
                   transition-transform peer-checked:translate-x-4 peer-disabled:opacity-70"
      />
    </span>
  );
}
