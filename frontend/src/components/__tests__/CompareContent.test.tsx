import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import CompareContent from "@/components/CompareContent";

vi.mock("@/lib/api", () => ({
  getHistoryItem: vi.fn().mockResolvedValue(null),
  getHistory: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, limit: 8 }),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, body: unknown) {
      super(String(body));
      this.status = status;
    }
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  // Provide a stable window.location.search
  Object.defineProperty(window, "location", {
    value: { search: "" },
    writable: true,
  });
});

describe("CompareContent", () => {
  it("renders heading and description", () => {
    render(<CompareContent />);
    expect(screen.getByText("Compare Debates")).toBeTruthy();
    expect(screen.getByText(/Select two debate thread IDs/i)).toBeTruthy();
  });

  it("renders Debate A and Debate B input labels", () => {
    render(<CompareContent />);
    expect(screen.getByText("Debate A")).toBeTruthy();
    expect(screen.getByText("Debate B")).toBeTruthy();
  });

  it("Compare button is disabled when both inputs are empty", () => {
    render(<CompareContent />);
    const btn = screen.getByText("Compare").closest("button") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("Compare button is enabled after typing in Debate A input", () => {
    render(<CompareContent />);
    const [inputA] = screen.getAllByPlaceholderText("Enter thread ID…");
    fireEvent.change(inputA, { target: { value: "thread-abc" } });
    const btn = screen.getByText("Compare").closest("button") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it("Swap A / B button appears when input A has value", () => {
    render(<CompareContent />);
    const [inputA] = screen.getAllByPlaceholderText("Enter thread ID…");
    fireEvent.change(inputA, { target: { value: "thread-abc" } });
    expect(screen.getByText(/Swap A \/ B/)).toBeTruthy();
  });

  it("swapping A and B exchanges input values", () => {
    render(<CompareContent />);
    const [inputA, inputB] = screen.getAllByPlaceholderText("Enter thread ID…") as HTMLInputElement[];
    fireEvent.change(inputA, { target: { value: "aaaa" } });
    fireEvent.change(inputB, { target: { value: "bbbb" } });
    fireEvent.click(screen.getByText(/Swap A \/ B/));
    expect(inputA.value).toBe("bbbb");
    expect(inputB.value).toBe("aaaa");
  });
});
