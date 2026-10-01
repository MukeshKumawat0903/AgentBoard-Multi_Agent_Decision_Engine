import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import LLMSettingsPanel from "@/components/LLMSettingsPanel";

type Settings = Record<string, unknown>;

function mockFetch(settings: Settings) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = init?.method === "POST" ? { ...settings, ...JSON.parse(String(init.body)) } : settings;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const BASE: Settings = {
  provider: "groq",
  model: "llama-3.3-70b-versatile",
  available_models: {},
  using_custom_key: false,
};

async function openPanel() {
  fireEvent.click(screen.getByRole("button", { name: "LLM provider settings" }));
  await screen.findByText(/Active:/);
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LLMSettingsPanel", () => {
  it("moves a key saved by an older version out of localStorage", async () => {
    localStorage.setItem("llm_api_key_openai", "sk-legacy");
    mockFetch({ ...BASE, provider: "openai", model: "gpt-5.5" });
    render(<LLMSettingsPanel />);
    await openPanel();

    await waitFor(() => expect(sessionStorage.getItem("llm_api_key_openai")).toBe("sk-legacy"));
    expect(localStorage.getItem("llm_api_key_openai")).toBeNull();
  });

  it("does not require a user key when the server has one", async () => {
    mockFetch({ ...BASE, provider: "openai", model: "gpt-5.5", server_keys: { groq: true, openai: true } });
    render(<LLMSettingsPanel />);
    await openPanel();

    expect(screen.getByText(/optional — the server has one/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Apply" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("asks for the admin token when required and sends it with the switch", async () => {
    const calls = mockFetch({ ...BASE, server_keys: { groq: true }, admin_token_required: true });
    render(<LLMSettingsPanel />);
    await openPanel();

    const apply = screen.getByRole("button", { name: "Apply" }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true); // token missing
    fireEvent.change(screen.getByLabelText(/Admin token/), { target: { value: "s3cret-admin" } });
    fireEvent.click(apply);

    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.init?.method === "POST")!;
    const headers = post.init!.headers as Record<string, string>;
    expect(headers["X-Admin-Token"]).toBe("s3cret-admin");
    expect(headers["Content-Type"]).toBe("application/json"); // merged, not replaced
    expect(sessionStorage.getItem("agentboard_admin_token")).toBe("s3cret-admin");
  });
});
