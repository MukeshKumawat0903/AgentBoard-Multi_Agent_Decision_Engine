/**
 * ThemeToggle – sun/moon button that toggles the `dark` class on <html>.
 *
 * The initial class is set by an inline script in layout.tsx (no flash).
 * The chosen preference is persisted in localStorage under the key "theme".
 */

"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

export default function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    // Sync local state with whatever the inline script already applied
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const isDark = document.documentElement.classList.toggle("dark");
    localStorage.setItem("theme", isDark ? "dark" : "light");
    setDark(isDark);
  }

  return (
    <button
      onClick={toggle}
      aria-label="Toggle dark mode"
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      className="p-2 rounded-lg text-gray-500 hover:bg-gray-100
                 dark:text-gray-400 dark:hover:bg-gray-800 transition"
    >
      {dark ? (
        <Sun className="w-5 h-5" aria-hidden="true" />
      ) : (
        <Moon className="w-5 h-5" aria-hidden="true" />
      )}
    </button>
  );
}
