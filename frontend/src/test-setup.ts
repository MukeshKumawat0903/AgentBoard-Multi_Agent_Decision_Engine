import "@testing-library/jest-dom";
import { vi } from "vitest";

// Mock Next.js navigation hooks used by client components
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

// Stable localStorage stub — reset between tests
const _storage: Record<string, string> = {};
const localStorageMock = {
  getItem: vi.fn((k: string) => _storage[k] ?? null),
  setItem: vi.fn((k: string, v: string) => { _storage[k] = v; }),
  removeItem: vi.fn((k: string) => { delete _storage[k]; }),
  clear: vi.fn(() => { Object.keys(_storage).forEach((k) => delete _storage[k]); }),
};
Object.defineProperty(global, "localStorage", { value: localStorageMock, writable: true });

// Silence Next.js "router not available" console errors in tests
global.console.error = vi.fn();
