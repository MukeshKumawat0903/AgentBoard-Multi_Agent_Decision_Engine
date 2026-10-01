import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { HistoryItem, HistoryListResponse } from "@/lib/types";
import HistoryPage from "@/app/history/page";
import { getHistory } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  getHistory: vi.fn(),
}));

const mockedGetHistory = vi.mocked(getHistory);

function item(thread_id: string, user_query: string): HistoryItem {
  return {
    thread_id,
    user_query,
    status: "converged",
    created_at: "2026-01-01T00:00:00Z",
    total_rounds: 2,
    agreement_score: 0.8,
    termination_reason: "consensus_reached",
  } as HistoryItem;
}

function page(...items: HistoryItem[]): HistoryListResponse {
  return { items, total: items.length, page: 1, limit: 15 } as HistoryListResponse;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("HistoryPage", () => {
  it("asks the server to sort and filter instead of reordering the current page", async () => {
    mockedGetHistory.mockResolvedValue(page(item("a", "First question")));
    render(<HistoryPage />);
    await screen.findByText("First question");

    await act(async () => {
      fireEvent.change(screen.getByRole("combobox"), { target: { value: "highest_agreement" } });
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Human Override" }));
    });

    expect(mockedGetHistory).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, sort: "highest_agreement", termination_reason: "human_override" }),
    );
  });

  it("shows the server's items in the order it returned them", async () => {
    mockedGetHistory.mockResolvedValue(page(item("b", "Second"), item("a", "First")));
    render(<HistoryPage />);
    await screen.findByText("Second");

    const queries = screen.getAllByText(/^(First|Second)$/).map((el) => el.textContent);
    expect(queries).toEqual(["Second", "First"]);
  });

  it("ignores a slow response that arrives after a newer one", async () => {
    const slow = deferred<HistoryListResponse>();
    const fast = deferred<HistoryListResponse>();
    mockedGetHistory.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);

    render(<HistoryPage />);
    await act(async () => {
      fireEvent.change(screen.getByRole("combobox"), { target: { value: "oldest" } });
    });
    expect(mockedGetHistory).toHaveBeenCalledTimes(2);

    await act(async () => { fast.resolve(page(item("new", "Oldest-first result"))); });
    await act(async () => { slow.resolve(page(item("old", "Stale newest-first result"))); });

    expect(screen.getByText("Oldest-first result")).toBeTruthy();
    expect(screen.queryByText("Stale newest-first result")).toBeNull();
  });
});
