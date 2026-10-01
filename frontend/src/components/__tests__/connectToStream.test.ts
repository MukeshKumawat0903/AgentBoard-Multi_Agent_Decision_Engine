import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { connectToStream } from "@/lib/api";

type Listener = (e: MessageEvent) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }

  close() {
    this.closed = true;
  }

  emitRaw(type: string, event: MessageEvent) {
    for (const fn of this.listeners.get(type) ?? []) fn(event);
  }

  emit(type: string, data: Record<string, unknown> = {}, lastEventId = "") {
    for (const fn of this.listeners.get(type) ?? []) {
      fn({ data: JSON.stringify(data), lastEventId } as MessageEvent);
    }
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("connectToStream reconnect limit", () => {
  it("gives up after 10 failed reconnects, backing off between them", () => {
    const onError = vi.fn();
    const ctrl = connectToStream("t-1", { onEvent: vi.fn(), onError });

    for (let i = 0; i < 11; i++) {
      const source = FakeEventSource.instances[i];
      // A failed connection fires the browser's data-less "error" event, which also
      // reaches the listener registered for the server's named "error" event.
      source.emitRaw("error", {} as MessageEvent);
      source.onerror?.();
      vi.advanceTimersByTime(30_000);
    }

    expect(onError).toHaveBeenCalledTimes(1);
    expect(FakeEventSource.instances).toHaveLength(11);
    ctrl.abort();
  });

  it("still delivers the server's own error event", () => {
    const onEvent = vi.fn();
    const ctrl = connectToStream("t-1", { onEvent });
    FakeEventSource.instances[0].emit("error", { type: "error", detail: "LLM failed" });
    expect(onEvent).toHaveBeenCalledWith({ type: "error", detail: "LLM failed" });
    ctrl.abort();
  });
});

describe("connectToStream status", () => {
  it("reports connected again once a reconnect succeeds", () => {
    const statuses: string[] = [];
    const ctrl = connectToStream("t-1", { onEvent: vi.fn(), onStatusChange: (s) => statuses.push(s) });
    FakeEventSource.instances[0].onopen?.();

    FakeEventSource.instances[0].onerror?.();
    vi.advanceTimersByTime(1_000);
    expect(FakeEventSource.instances).toHaveLength(2);
    FakeEventSource.instances[1].onopen?.();

    expect(statuses.at(-1)).toBe("connected");
    expect(statuses).toContain("reconnecting");
    ctrl.abort();
  });
});

describe("connectToStream heartbeat", () => {
  it("server pings keep a quiet connection (e.g. a HITL pause) open", () => {
    const onError = vi.fn();
    const ctrl = connectToStream("t-1", { onEvent: vi.fn(), onError });

    // 15 minutes with nothing but a ping every 20 s.
    for (let i = 0; i < 45; i++) {
      vi.advanceTimersByTime(20_000);
      FakeEventSource.instances[0].emit("ping");
    }

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].closed).toBe(false);
    expect(onError).not.toHaveBeenCalled();
    ctrl.abort();
  });

  it("a connection that goes fully silent is treated as stale and reconnected", () => {
    const ctrl = connectToStream("t-1", { onEvent: vi.fn() });

    vi.advanceTimersByTime(60_001);
    expect(FakeEventSource.instances[0].closed).toBe(true);
    vi.advanceTimersByTime(1_000);
    expect(FakeEventSource.instances).toHaveLength(2);
    ctrl.abort();
  });

  it("pings are not forwarded as debate events", () => {
    const onEvent = vi.fn();
    const ctrl = connectToStream("t-1", { onEvent });

    FakeEventSource.instances[0].emit("ping");
    expect(onEvent).not.toHaveBeenCalled();

    FakeEventSource.instances[0].emit("round_started", { type: "round_started", round_number: 1, max_rounds: 2 });
    expect(onEvent).toHaveBeenCalledTimes(1);
    ctrl.abort();
  });

  it("abort closes whichever connection is current after reconnects", () => {
    const ctrl = connectToStream("t-1", { onEvent: vi.fn() });
    FakeEventSource.instances[0].onerror?.();
    vi.advanceTimersByTime(1_000);
    FakeEventSource.instances[1].onerror?.();
    vi.advanceTimersByTime(2_000);
    expect(FakeEventSource.instances).toHaveLength(3);

    ctrl.abort();
    expect(FakeEventSource.instances[2].closed).toBe(true);
    vi.advanceTimersByTime(120_000);
    expect(FakeEventSource.instances).toHaveLength(3); // no reconnects after abort
  });
});
