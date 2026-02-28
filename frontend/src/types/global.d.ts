/**
 * Minimal type stubs so the IDE does not report errors before
 * `npm install` has been run.  These are superseded by the real
 * @types/react, @types/node and tailwindcss type declarations
 * once node_modules is populated.
 */

/* React JSX support ------------------------------------------------ */
declare namespace JSX {
  type Element = any;
  interface IntrinsicElements {
    [elemName: string]: any;
  }
}

declare namespace React {
  type ReactNode = any;
  type FormEvent = any;
  type ChangeEvent<T = Element> = { target: T & { value: string } };
  function useState<T>(init: T | (() => T)): [T, (v: T | ((p: T) => T)) => void];
  function useEffect(cb: () => void | (() => void), deps?: any[]): void;
}

interface HTMLTextAreaElement {}
interface HTMLInputElement {}

declare module "react" {
  export = React;
  export as namespace React;
}

declare module "next/font/google" {
  export function Inter(opts: any): { className: string };
}

declare module "next/navigation" {
  export function useRouter(): { push(url: string): void };
  export function useParams<T = Record<string, string>>(): T;
}

/* Node.js globals -------------------------------------------------- */
declare const process: { env: Record<string, string | undefined> };

/* Next.js ---------------------------------------------------------- */
declare module "next" {
  export interface Metadata {
    title?: string;
    description?: string;
    [key: string]: any;
  }
}

/* Tailwind CSS ----------------------------------------------------- */
declare module "tailwindcss" {
  export interface Config {
    content?: string[];
    theme?: Record<string, any>;
    plugins?: any[];
    [key: string]: any;
  }
}
