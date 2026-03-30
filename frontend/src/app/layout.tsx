import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import NavBar from "@/components/NavBar";
import { ToastProvider } from "@/components/Toast";

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
        <ToastProvider>
          {/* Top navigation */}
          <NavBar />

          {/* Main content */}
          <main id="main-content" className="max-w-5xl mx-auto px-4 py-8">{children}</main>

          {/* Footer */}
          <footer className="border-t border-gray-200 dark:border-gray-800 mt-12">
            <div className="max-w-5xl mx-auto px-4 py-6 text-center text-xs text-gray-400 dark:text-gray-600">
              AgentBoard &copy; {new Date().getFullYear()} &mdash; Powered by
              Groq, OpenAI &amp; Anthropic via LangChain
            </div>
          </footer>
        </ToastProvider>
      </body>
    </html>
  );
}
