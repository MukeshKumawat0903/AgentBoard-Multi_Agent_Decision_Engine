/**
 * AgentAvatar – circular agent identity mark.
 *
 * Gradient disc in the agent's colour with a white lucide icon. Replaces the
 * platform-dependent emoji avatars. Optional status ring/badge for the live
 * presence strip (working / done / timeout).
 */

"use client";

import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  ShieldAlert,
  Target,
  Scale,
  Gavel,
  Banknote,
  Lock,
  ClipboardList,
  HeartPulse,
  Bot,
  Check,
  Clock,
} from "lucide-react";
import { AGENT_META, DOMAIN_AGENT_META } from "@/lib/types";

const AGENT_ICONS: Record<string, LucideIcon> = {
  Analyst: BarChart3,
  Risk: ShieldAlert,
  Strategy: Target,
  Ethics: Scale,
  Moderator: Gavel,
  FinancialEthics: Banknote,
  Security: Lock,
  Compliance: ClipboardList,
  PatientSafety: HeartPulse,
};

const FALLBACK_COLOR = "#6B7280";

export type AgentAvatarSize = "sm" | "md" | "lg";
export type AgentAvatarStatus = "idle" | "working" | "done" | "timeout";

const SIZE: Record<AgentAvatarSize, { disc: string; icon: string; badge: string; badgeIcon: string }> = {
  sm: { disc: "w-6 h-6", icon: "w-3 h-3", badge: "w-3 h-3 -right-0.5 -bottom-0.5", badgeIcon: "w-2 h-2" },
  md: { disc: "w-8 h-8", icon: "w-4 h-4", badge: "w-3.5 h-3.5 -right-0.5 -bottom-0.5", badgeIcon: "w-2.5 h-2.5" },
  lg: { disc: "w-12 h-12", icon: "w-6 h-6", badge: "w-4 h-4 -right-0.5 -bottom-0.5", badgeIcon: "w-3 h-3" },
};

export function agentColor(name: string): string {
  return (
    AGENT_META[name as keyof typeof AGENT_META]?.color ??
    DOMAIN_AGENT_META[name]?.color ??
    FALLBACK_COLOR
  );
}

export interface AgentAvatarProps {
  name: string;
  size?: AgentAvatarSize;
  status?: AgentAvatarStatus;
  className?: string;
}

export default function AgentAvatar({
  name,
  size = "md",
  status = "idle",
  className = "",
}: AgentAvatarProps) {
  const color = agentColor(name);
  const Icon = AGENT_ICONS[name] ?? Bot;
  const s = SIZE[size];

  return (
    <span className={`relative inline-flex shrink-0 ${className}`}>
      <span
        aria-hidden="true"
        className={`${s.disc} rounded-full inline-flex items-center justify-center text-white shadow-sm
                    ${status === "working" ? "animate-pulse ring-2 ring-offset-1 ring-offset-surface-raised" : ""}`}
        style={{
          background: `linear-gradient(135deg, ${color}, color-mix(in srgb, ${color} 65%, #1e1b4b))`,
          ...(status === "working" ? { ["--tw-ring-color" as string]: `${color}66` } : {}),
        }}
      >
        <Icon className={s.icon} strokeWidth={2.25} />
      </span>
      {status === "done" && (
        <span
          className={`absolute ${s.badge} rounded-full bg-green-500 text-white flex items-center justify-center ring-2 ring-surface-raised`}
          aria-hidden="true"
        >
          <Check className={s.badgeIcon} strokeWidth={3} />
        </span>
      )}
      {status === "timeout" && (
        <span
          className={`absolute ${s.badge} rounded-full bg-amber-500 text-white flex items-center justify-center ring-2 ring-surface-raised`}
          aria-hidden="true"
        >
          <Clock className={s.badgeIcon} strokeWidth={3} />
        </span>
      )}
    </span>
  );
}
