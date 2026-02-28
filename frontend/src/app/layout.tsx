import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import ThemeToggle from "@/components/ThemeToggle";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AgentBoard — Multi-Agent Decision Engine",
  description:
    "An multi-agent debate system where AI agents collaboratively analyse queries and converge on a consensus decision.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      {/* Flash-free theme init: reads localStorage before first paint */}
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('theme');if(t==='dark'||(t===null&&window.matchMedia('(prefers-color-scheme:dark)').matches)){document.documentElement.classList.add('dark')}}catch(e){}})();`,
          }}
        />
      </head>
      <body className={inter.className}>
        {/* Top navigation */}
        <header className="sticky top-0 z-50 bg-white/80 dark:bg-gray-900/80 backdrop-blur border-b border-gray-200 dark:border-gray-800">
          <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
            <a href="/" className="flex items-center gap-2 font-bold text-gray-800 dark:text-gray-100">
              <span className="text-xl">🎯</span>
              <span>AgentBoard</span>
            </a>
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-400 dark:text-gray-500 hidden sm:inline">
                Multi-Agent Decision Engine
              </span>
              <ThemeToggle />
            </div>
          </div>
        </header>

        {/* Main content */}
        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>

        {/* Footer */}
        <footer className="border-t border-gray-200 dark:border-gray-800 mt-12">
          <div className="max-w-5xl mx-auto px-4 py-6 text-center text-xs text-gray-400 dark:text-gray-600">
            AgentBoard &copy; {new Date().getFullYear()} &mdash; Powered by
            GROQ &amp; LLaMA
          </div>
        </footer>
      </body>
    </html>
  );
}
