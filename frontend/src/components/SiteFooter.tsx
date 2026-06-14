"use client";

import { usePathname } from "next/navigation";

// Footer is hidden on the home page so the New Debate workspace owns the full
// viewport; it renders normally on every other route.
export default function SiteFooter() {
  const pathname = usePathname();
  if (pathname === "/") return null;

  return (
    <footer className="border-t border-line mt-12">
      <div className="max-w-6xl mx-auto px-4 py-6 text-center text-xs text-gray-400 dark:text-gray-600">
        AgentBoard &copy; {new Date().getFullYear()} &mdash; Powered by Groq,
        OpenAI, Anthropic &amp; Gemini via LangChain
      </div>
    </footer>
  );
}
