/**
 * CollapsibleSection – header + rotating chevron + animated-height body.
 *
 * Height animation uses the CSS grid 0fr→1fr trick so content of any height
 * animates smoothly without measuring. Supports controlled (open/onToggle)
 * and uncontrolled (defaultOpen) usage.
 */

"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

export interface CollapsibleSectionProps {
  title: ReactNode;
  /** Muted extra info rendered after the title (counts, hints). */
  meta?: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onToggle?: (open: boolean) => void;
  /** Classes for the header button. */
  headerClassName?: string;
  /** Classes for the body wrapper (inside the animated region). */
  bodyClassName?: string;
  className?: string;
  children: ReactNode;
}

export default function CollapsibleSection({
  title,
  meta,
  defaultOpen = false,
  open: controlledOpen,
  onToggle,
  headerClassName = "",
  bodyClassName = "",
  className = "",
  children,
}: CollapsibleSectionProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const open = isControlled ? controlledOpen : uncontrolledOpen;

  function toggle() {
    const next = !open;
    if (!isControlled) setUncontrolledOpen(next);
    onToggle?.(next);
  }

  return (
    <div className={className}>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className={`w-full flex items-center justify-between gap-3 text-left
                    focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 rounded-lg
                    ${headerClassName}`}
      >
        <span className="flex items-center gap-2 min-w-0">
          {title}
          {meta}
        </span>
        <ChevronDown
          aria-hidden="true"
          className={`w-4 h-4 shrink-0 text-gray-400 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>
      <div
        className={`grid transition-[grid-template-rows] duration-300 ease-out ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden min-h-0">
          <div className={bodyClassName}>{children}</div>
        </div>
      </div>
    </div>
  );
}
