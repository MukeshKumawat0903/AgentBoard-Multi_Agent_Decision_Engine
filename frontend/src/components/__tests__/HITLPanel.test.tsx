import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import HITLPanel from "@/components/HITLPanel";
import type { ApprovalRequiredEvent } from "@/lib/types";

const approveDebate = vi.fn();
vi.mock("@/lib/api", () => ({ approveDebate: (...args: unknown[]) => approveDebate(...args) }));

function event(overrides: Partial<ApprovalRequiredEvent> = {}): ApprovalRequiredEvent {
  return {
    type: "approval_required",
    round_number: 2,
    agreement_score: 0.7,
    termination_reason: "max_rounds_reached",
    synthesis_summary: "Agents broadly agree.",
    options: ["approve", "override", "add_round"],
    ...overrides,
  };
}

describe("HITLPanel", () => {
  it("offers Add Round while the backend allows it", () => {
    render(<HITLPanel event={event()} threadId="t1" onDone={vi.fn()} />);
    expect(screen.getByRole("button", { name: "+ Add Round" })).toBeTruthy();
  });

  it("hides Add Round once the debate is at its round limit", () => {
    render(<HITLPanel event={event({ options: ["approve", "override"] })} threadId="t1" onDone={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "+ Add Round" })).toBeNull();
  });

  it("reports the round it answered when the approval is accepted", async () => {
    approveDebate.mockResolvedValueOnce({ thread_id: "t1", status: "resuming", action: "approve" });
    const onDone = vi.fn();
    render(<HITLPanel event={event({ round_number: 3 })} threadId="t1" onDone={onDone} />);

    fireEvent.click(screen.getByRole("button", { name: /Approve/ }));

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(3));
    expect(approveDebate).toHaveBeenCalledWith("t1", "approve", "");
  });

  it("does not submit an override without feedback", () => {
    render(<HITLPanel event={event()} threadId="t1" onDone={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Override/ }));   // reveals the textarea
    const submit = screen.getByRole("button", { name: /Submit Override/ }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });
});
