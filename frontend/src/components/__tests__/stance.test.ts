import { describe, it, expect } from "vitest";
import { voteLabel } from "@/lib/stance";

describe("voteLabel", () => {
  it("counts the largest group over the agents who voted", () => {
    expect(voteLabel({ support: 2, oppose: 1, abstain: 1 })).toBe("2/3 vote");
    expect(voteLabel({ support: 2, oppose: 2 })).toBe("2/4 vote");
    expect(voteLabel({ conditional: 1, support: 1, oppose: 1 })).toBe("1/3 vote");
  });

  it("is empty when fewer than two agents voted", () => {
    expect(voteLabel({ support: 1, abstain: 3 })).toBe("");
    expect(voteLabel({})).toBe("");
    expect(voteLabel(undefined)).toBe("");
    expect(voteLabel(null)).toBe("");
  });
});
