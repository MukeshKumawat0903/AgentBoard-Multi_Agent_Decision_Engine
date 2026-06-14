import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ThemeToggle from "@/components/ThemeToggle";

beforeEach(() => {
  document.documentElement.classList.remove("dark");
  (localStorage.setItem as ReturnType<typeof vi.fn>).mockClear();
});

describe("ThemeToggle", () => {
  it("renders a button with aria-label", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: /toggle dark mode/i })).toBeTruthy();
  });

  it("toggles dark class on <html> when clicked", () => {
    render(<ThemeToggle />);
    const btn = screen.getByRole("button");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    fireEvent.click(btn);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("persists preference to localStorage on toggle", () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button"));
    expect(localStorage.setItem).toHaveBeenCalledWith("theme", "dark");
  });

  it("toggles back to light and persists", () => {
    document.documentElement.classList.add("dark");
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button"));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.setItem).toHaveBeenCalledWith("theme", "light");
  });
});
