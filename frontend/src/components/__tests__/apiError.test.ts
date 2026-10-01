import { describe, it, expect } from "vitest";
import { ApiError, extractErrorMessage } from "@/lib/api";
import { debateStreamReducer, initialStreamState } from "@/lib/debateStreamReducer";

describe("ApiError messages", () => {
  it("uses the inner detail of a structured ErrorResponse (not [object Object])", () => {
    const err = new ApiError(409, {
      detail: { error: "debate_not_awaiting_approval", detail: "Debate 't1' is not awaiting approval." },
    });
    expect(err.message).toBe("Debate 't1' is not awaiting approval.");
    expect(err.code).toBe("debate_not_awaiting_approval");
  });

  it("joins FastAPI validation messages", () => {
    const err = new ApiError(422, {
      detail: [{ msg: "String should have at most 5000 characters" }, { msg: "Field required" }],
    });
    expect(err.message).toBe("String should have at most 5000 characters; Field required");
  });

  it("reads the rate limiter's top-level error text", () => {
    expect(new ApiError(429, { error: "Rate limit exceeded: 30 per 1 minute" }).message).toBe(
      "Rate limit exceeded: 30 per 1 minute",
    );
  });

  it("explains LLM failures instead of claiming the backend is down", () => {
    const err = new ApiError(502, { error: "llm_response_error", detail: "raw provider text" });
    expect(err.message).toContain("AI model returned an invalid response");
    expect(err.message).not.toContain("Backend unavailable");
    expect(new ApiError(429, { error: "llm_rate_limit", detail: "x" }).message).toContain("rate-limiting");
  });

  it("still reports an unreachable backend", () => {
    expect(new ApiError(500, null).message).toContain("Backend unreachable");
    expect(new ApiError(502, { detail: "Backend unreachable: fetch failed" }).message).toContain(
      "Backend unavailable",
    );
  });

  it("extractErrorMessage returns null for bodies without text", () => {
    expect(extractErrorMessage(null)).toBeNull();
    expect(extractErrorMessage({})).toBeNull();
    expect(extractErrorMessage({ detail: [] })).toBeNull();
  });
});

describe("stream error mapping", () => {
  it("maps by error_type, not by searching the (now sanitised) detail", () => {
    const next = debateStreamReducer(initialStreamState, {
      event: {
        type: "error",
        error: "debate_execution_failed",
        error_type: "LLMConnectionError",
        detail: "Could not connect to the AI provider.",
      } as never,
    });
    expect(next.error).toBe("Could not connect to the AI provider.");
  });

  it("maps recovery and missing-decision codes to plain explanations", () => {
    const recovery = debateStreamReducer(initialStreamState, {
      event: { type: "error", error: "debate_recovery_required", detail: "error:LLMResponseError" } as never,
    });
    expect(recovery.error).toContain("was interrupted");

    const missing = debateStreamReducer(initialStreamState, {
      event: { type: "error", error: "decision_unavailable", detail: "x" } as never,
    });
    expect(missing.error).toContain("could not be loaded");
  });
});
