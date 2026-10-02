/**
 * Helpers for the stance-based agreement score (backend services/consensus.py).
 */

/** "2/3 vote": agents in the largest voting group / agents who voted.
 *  Abstainers don't vote. Empty when fewer than two agents voted. */
export function voteLabel(tally: Record<string, number> | null | undefined): string {
  if (!tally) return "";
  const votes = Object.entries(tally)
    .filter(([stance]) => stance !== "abstain")
    .map(([, count]) => count);
  const voters = votes.reduce((sum, n) => sum + n, 0);
  if (voters < 2) return "";
  return `${Math.max(...votes)}/${voters} vote`;
}
