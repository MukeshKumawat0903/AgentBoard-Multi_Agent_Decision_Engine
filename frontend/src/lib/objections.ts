/**
 * Helpers for the consensus gate's open objections (backend services/consensus.py):
 * high/critical critiques the target's revision did not resolve.
 */

import type { OpenDisagreement } from "./types";

/** "Open: Risk → Strategy, Ethics → Risk". Empty when nothing is open. */
export function openObjectionsLabel(open: OpenDisagreement[] | null | undefined): string {
  if (!open || open.length === 0) return "";
  return `Open: ${open.map((o) => `${o.critic} → ${o.target}`).join(", ")}`;
}
