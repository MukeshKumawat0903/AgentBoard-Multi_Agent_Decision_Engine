import type { Config } from "tailwindcss";
import colors from "tailwindcss/colors";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Brand accent ramp — indigo, used for primary actions and highlights.
        accent: colors.indigo,
        // Surface hierarchy driven by CSS variables (see globals.css).
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          raised: "rgb(var(--surface-raised) / <alpha-value>)",
          overlay: "rgb(var(--surface-overlay) / <alpha-value>)",
        },
        // Border tokens — use as border-line / border-line-strong.
        line: {
          DEFAULT: "rgb(var(--line) / <alpha-value>)",
          strong: "rgb(var(--line-strong) / <alpha-value>)",
        },
        analyst: { DEFAULT: "#3B82F6", light: "#DBEAFE" },
        risk: { DEFAULT: "#EF4444", light: "#FEE2E2" },
        strategy: { DEFAULT: "#22C55E", light: "#DCFCE7" },
        ethics: { DEFAULT: "#A855F7", light: "#F3E8FF" },
        moderator: { DEFAULT: "#EAB308", light: "#FEF9C3" },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(0 0 0 / 0.04), 0 4px 12px -4px rgb(0 0 0 / 0.08)",
        "card-hover":
          "0 2px 4px 0 rgb(0 0 0 / 0.05), 0 12px 24px -8px rgb(0 0 0 / 0.12)",
      },
      animation: {
        fadeIn: "fadeIn 0.2s ease-out both",
        shake: "shake 0.3s ease-in-out",
        slideUpIn: "slideUpIn 0.35s cubic-bezier(0.21, 1.02, 0.73, 1) both",
        scaleIn: "scaleIn 0.3s cubic-bezier(0.21, 1.02, 0.73, 1) both",
        thinking: "thinking 1.2s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shake: {
          "0%, 100%": { transform: "translateX(0)" },
          "20%": { transform: "translateX(-6px)" },
          "40%": { transform: "translateX(6px)" },
          "60%": { transform: "translateX(-4px)" },
          "80%": { transform: "translateX(4px)" },
        },
        slideUpIn: {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        scaleIn: {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        thinking: {
          "0%, 100%": { opacity: "0.35", transform: "scale(0.85)" },
          "40%": { opacity: "1", transform: "scale(1)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
