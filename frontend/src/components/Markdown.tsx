/**
 * Markdown – lightweight, dark-mode-aware Markdown renderer used for agent positions,
 * reasoning, and the final decision text. LLMs emit Markdown (lists, bold,
 * headings, tables); rendering it makes outputs far more readable than the
 * previous raw `<p>` with literal `-`/`**`.
 *
 * Security: react-markdown does NOT render raw HTML unless `rehype-raw` is
 * added, so user/LLM content cannot inject markup — this is XSS-safe by default.
 */

"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

const components: Components = {
  p: (props) => <p className="mb-2 last:mb-0 leading-relaxed" {...props} />,
  ul: (props) => <ul className="list-disc list-inside mb-2 space-y-0.5" {...props} />,
  ol: (props) => <ol className="list-decimal list-inside mb-2 space-y-0.5" {...props} />,
  li: (props) => <li className="leading-relaxed" {...props} />,
  strong: (props) => <strong className="font-semibold text-gray-800 dark:text-gray-200" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  h1: (props) => <h1 className="text-base font-semibold mt-3 mb-1.5" {...props} />,
  h2: (props) => <h2 className="text-sm font-semibold mt-3 mb-1.5" {...props} />,
  h3: (props) => <h3 className="text-sm font-semibold mt-2 mb-1" {...props} />,
  a: (props) => (
    <a
      className="text-blue-600 dark:text-blue-400 underline underline-offset-2"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
  code: (props) => (
    <code className="px-1 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[0.85em] font-mono" {...props} />
  ),
  pre: (props) => (
    <pre className="p-3 rounded-lg bg-gray-100 dark:bg-gray-800 overflow-x-auto text-xs mb-2" {...props} />
  ),
  blockquote: (props) => (
    <blockquote
      className="border-l-2 border-gray-300 dark:border-gray-600 pl-3 italic text-gray-500 dark:text-gray-400 mb-2"
      {...props}
    />
  ),
  table: (props) => <table className="w-full text-xs border-collapse mb-2" {...props} />,
  th: (props) => (
    <th className="border border-gray-300 dark:border-gray-600 px-2 py-1 text-left font-semibold" {...props} />
  ),
  td: (props) => <td className="border border-gray-300 dark:border-gray-600 px-2 py-1" {...props} />,
};

interface MarkdownProps {
  children: string;
  className?: string;
}

export default function Markdown({ children, className = "" }: MarkdownProps) {
  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
