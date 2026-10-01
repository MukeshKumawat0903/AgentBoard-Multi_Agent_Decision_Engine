import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import HomePage from "@/app/page";
import { getDebateModes, startDebateAsync } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  startDebateAsync: vi.fn(async () => ({ thread_id: "t-1" })),
  cancelDebate: vi.fn(async () => undefined),
  getTemplates: vi.fn(async () => []),
  getDomainPacks: vi.fn(async () => []),
  getHistory: vi.fn(async () => ({ items: [], total: 0, page: 1, limit: 3 })),
  getAgents: vi.fn(async () => []), // keeps the built-in roster: 4 debaters + Moderator
  getDebateModes: vi.fn(async () => ({ default_mode: "quick", presets: {} })),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

async function toggle(name: string) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name }));
  });
}

describe("HomePage default mode", () => {
  async function submit() {
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Should we expand into the Southeast Asian market?" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start Debate" }));
    });
    return vi.mocked(startDebateAsync).mock.calls[0][0];
  }

  it("starts in the server's default mode (DEFAULT_DEBATE_MODE)", async () => {
    vi.mocked(getDebateModes).mockResolvedValueOnce({ default_mode: "standard", presets: {} });
    await act(async () => {
      render(<HomePage />);
    });
    expect((await submit()).mode).toBe("standard");
  });

  it("falls back to Quick when the server default can't be loaded", async () => {
    vi.mocked(getDebateModes).mockRejectedValue(new Error("offline"));
    await act(async () => {
      render(<HomePage />);
    });
    expect((await submit()).mode).toBe("quick");
    vi.mocked(getDebateModes).mockResolvedValue({ default_mode: "quick", presets: {} });
  });
});

describe("HomePage agent roster", () => {
  it("keeps two debating agents besides the Moderator", async () => {
    await act(async () => {
      render(<HomePage />);
    });
    await toggle("Analyst");
    await toggle("Risk");
    await toggle("Strategy"); // would leave only Ethics + Moderator

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Should we expand into the Southeast Asian market?" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start Debate" }));
    });

    const request = vi.mocked(startDebateAsync).mock.calls[0][0];
    expect(new Set(request.agents)).toEqual(new Set(["Strategy", "Ethics", "Moderator"]));
  });
});
