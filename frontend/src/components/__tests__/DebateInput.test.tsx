import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import DebateInput, { type DebateOptions } from "@/components/DebateInput";
import type { AgentOption } from "@/components/AgentRoster";

const agents = [] as AgentOption[];
const QUERY = "Should we expand into the Southeast Asian market next year?";

function setup(props: Partial<React.ComponentProps<typeof DebateInput>> = {}) {
  const onSubmit = vi.fn<(query: string, options: DebateOptions) => void>();
  render(
    <DebateInput
      onSubmit={onSubmit}
      isLoading={false}
      agents={agents}
      selectedAgents={new Set()}
      {...props}
    />,
  );
  const textarea = screen.getByRole("textbox");
  const submit = () => fireEvent.click(screen.getByRole("button", { name: "Start Debate" }));
  return { onSubmit, textarea, submit };
}

describe("DebateInput", () => {
  it("sends Custom as its own mode with the chosen rounds and threshold", () => {
    const { onSubmit, textarea, submit } = setup();
    fireEvent.change(textarea, { target: { value: QUERY } });
    fireEvent.click(screen.getByRole("button", { name: /Custom/ }));
    submit();

    const options = onSubmit.mock.calls[0][1];
    expect(options.mode).toBe("custom");
    expect(options.max_rounds).toBe(4);
    expect(options.consensus_threshold).toBe(0.75);
  });

  it("defaults to Quick and sends presets without round overrides", () => {
    const { onSubmit, textarea, submit } = setup();
    fireEvent.change(textarea, { target: { value: QUERY } });
    submit();

    const options = onSubmit.mock.calls[0][1];
    expect(options.mode).toBe("quick");
    expect(options.max_rounds).toBeUndefined();
  });

  it("uses the server's default mode until the user picks one", () => {
    const onSubmit = vi.fn<(query: string, options: DebateOptions) => void>();
    const props = { onSubmit, isLoading: false, agents, selectedAgents: new Set<string>() };
    const { rerender } = render(<DebateInput {...props} />);
    // The default arrives after the first render (it's fetched from the server).
    rerender(<DebateInput {...props} defaultMode="thorough" />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: QUERY } });
    fireEvent.click(screen.getByRole("button", { name: "Start Debate" }));
    expect(onSubmit.mock.calls[0][1].mode).toBe("thorough");
  });

  it("does not let a late server default undo the user's choice", () => {
    const onSubmit = vi.fn<(query: string, options: DebateOptions) => void>();
    const props = { onSubmit, isLoading: false, agents, selectedAgents: new Set<string>() };
    const { rerender } = render(<DebateInput {...props} />);
    fireEvent.click(screen.getByRole("button", { name: /Custom/ }));
    rerender(<DebateInput {...props} defaultMode="thorough" />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: QUERY } });
    fireEvent.click(screen.getByRole("button", { name: "Start Debate" }));
    expect(onSubmit.mock.calls[0][1].mode).toBe("custom");
  });

  it("uses the mode a template suggests", () => {
    const { onSubmit, textarea, submit } = setup({ prefillMode: "thorough" });
    fireEvent.change(textarea, { target: { value: QUERY } });
    submit();
    expect(onSubmit.mock.calls[0][1].mode).toBe("thorough");
  });

  it("keeps the template id while the template's query is edited", () => {
    const { onSubmit, textarea, submit } = setup({ prefillQuery: QUERY, prefillTemplateId: "market-expansion" });
    fireEvent.change(textarea, { target: { value: QUERY.replace("next year", "in Q3") } });
    submit();

    expect(onSubmit.mock.calls[0][1].template_id).toBe("market-expansion");
  });

  it("drops the template id once the box is cleared for a new question", () => {
    const { onSubmit, textarea, submit } = setup({ prefillQuery: QUERY, prefillTemplateId: "market-expansion" });
    fireEvent.change(textarea, { target: { value: "" } });
    fireEvent.change(textarea, { target: { value: "Should we hire a second designer this year?" } });
    submit();

    expect(onSubmit.mock.calls[0][1].template_id).toBeUndefined();
  });

  it("takes the template id from a template sample chip", () => {
    const { onSubmit, submit } = setup({
      samples: [
        { label: "Market Expansion", query: QUERY, templateId: "market-expansion" },
        { label: "Free text", query: "Should we move our office downtown?" },
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "Market Expansion" }));
    submit();

    expect(onSubmit.mock.calls[0][1].template_id).toBe("market-expansion");
  });
});

describe("DebateInput agreement method", () => {
  it("defaults to Vote and sends it", () => {
    const { onSubmit, textarea, submit } = setup();
    expect(screen.getByRole("button", { name: "Vote" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.change(textarea, { target: { value: QUERY } });
    submit();
    expect(onSubmit.mock.calls[0][1].agreement_method).toBe("stance");
  });

  it("sends the method the user picks", () => {
    const { onSubmit, textarea, submit } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Text" }));
    fireEvent.change(textarea, { target: { value: QUERY } });
    submit();
    expect(onSubmit.mock.calls[0][1].agreement_method).toBe("lexical");
  });

  it("follows the server default until the user picks one", () => {
    const onSubmit = vi.fn<(query: string, options: DebateOptions) => void>();
    const props = { onSubmit, isLoading: false, agents, selectedAgents: new Set<string>() };
    const { rerender } = render(<DebateInput {...props} />);
    rerender(<DebateInput {...props} defaultAgreementMethod="lexical" />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: QUERY } });
    fireEvent.click(screen.getByRole("button", { name: "Start Debate" }));
    expect(onSubmit.mock.calls[0][1].agreement_method).toBe("lexical");
  });

  it("disables Semantic when the server cannot compute it", () => {
    const { onSubmit, textarea, submit } = setup({ semanticAvailable: false });
    const semantic = screen.getByRole("button", { name: "Semantic" });
    expect(semantic.getAttribute("aria-disabled")).toBe("true");
    expect(semantic.getAttribute("title")).toBe("Enable SEMANTIC_CONSENSUS_ENABLED on the server");
    fireEvent.click(semantic);
    fireEvent.change(textarea, { target: { value: QUERY } });
    submit();
    expect(onSubmit.mock.calls[0][1].agreement_method).toBe("stance");
  });

  it("allows Semantic when the server supports it", () => {
    const { onSubmit, textarea, submit } = setup({ semanticAvailable: true });
    fireEvent.click(screen.getByRole("button", { name: "Semantic" }));
    fireEvent.change(textarea, { target: { value: QUERY } });
    submit();
    expect(onSubmit.mock.calls[0][1].agreement_method).toBe("semantic");
  });

  it("keeps the explanations in tooltips", () => {
    setup();
    expect(screen.getByRole("button", { name: "Vote" }).getAttribute("title")).toBe(
      "Agents vote support / oppose. Recommended.",
    );
    expect(screen.queryByText("Agents vote support / oppose. Recommended.")).toBeNull();
  });
});
