import { describe, it, expect } from "vitest";
import { openObjectionsLabel } from "@/lib/objections";

describe("openObjectionsLabel", () => {
  it("lists each open critic → target pair", () => {
    expect(
      openObjectionsLabel([
        { critic: "Risk", target: "Strategy", severity: "high", status: "unaddressed" },
        { critic: "Ethics", target: "Risk", severity: "critical", status: "rebutted" },
      ]),
    ).toBe("Open: Risk → Strategy, Ethics → Risk");
  });

  it("is empty when nothing is open or the event predates the field", () => {
    expect(openObjectionsLabel([])).toBe("");
    expect(openObjectionsLabel(undefined)).toBe("");
    expect(openObjectionsLabel(null)).toBe("");
  });
});
