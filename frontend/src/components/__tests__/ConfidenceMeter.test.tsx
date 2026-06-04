import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ConfidenceMeter from "@/components/ConfidenceMeter";

describe("ConfidenceMeter", () => {
  it("renders without a label", () => {
    const { container } = render(<ConfidenceMeter score={0.5} />);
    expect(container.querySelector(".rounded-full")).toBeTruthy();
  });

  it("renders label and percentage text", () => {
    render(<ConfidenceMeter score={0.75} label="Confidence" />);
    expect(screen.getByText("Confidence")).toBeTruthy();
    expect(screen.getByText("75%")).toBeTruthy();
  });

  it("uses red bar for score < 0.3", () => {
    const { container } = render(<ConfidenceMeter score={0.2} />);
    const bar = container.querySelector(".bg-red-500");
    expect(bar).toBeTruthy();
  });

  it("uses yellow bar for score 0.3–0.6", () => {
    const { container } = render(<ConfidenceMeter score={0.45} />);
    const bar = container.querySelector(".bg-yellow-400");
    expect(bar).toBeTruthy();
  });

  it("uses lime bar for score 0.6–0.8", () => {
    const { container } = render(<ConfidenceMeter score={0.7} />);
    const bar = container.querySelector(".bg-lime-400");
    expect(bar).toBeTruthy();
  });

  it("uses green bar for score >= 0.8", () => {
    const { container } = render(<ConfidenceMeter score={0.95} />);
    const bar = container.querySelector(".bg-green-500");
    expect(bar).toBeTruthy();
  });

  it("bar width matches percentage", () => {
    const { container } = render(<ConfidenceMeter score={0.6} />);
    const bar = container.querySelector("[style]") as HTMLElement;
    expect(bar.style.width).toBe("60%");
  });

  it("sm size uses h-2 track", () => {
    const { container } = render(<ConfidenceMeter score={0.5} size="sm" />);
    const track = container.querySelector(".h-2");
    expect(track).toBeTruthy();
  });

  it("md size (default) uses h-3 track", () => {
    const { container } = render(<ConfidenceMeter score={0.5} />);
    const track = container.querySelector(".h-3");
    expect(track).toBeTruthy();
  });
});
