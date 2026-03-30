import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        analyst: { DEFAULT: "#3B82F6", light: "#DBEAFE" },
        risk: { DEFAULT: "#EF4444", light: "#FEE2E2" },
        strategy: { DEFAULT: "#22C55E", light: "#DCFCE7" },
        ethics: { DEFAULT: "#A855F7", light: "#F3E8FF" },
        moderator: { DEFAULT: "#EAB308", light: "#FEF9C3" },
      },
      animation: {
        fadeIn: "fadeIn 0.2s ease-out both",
        shake: "shake 0.3s ease-in-out",
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
      },
    },
  },
  plugins: [],
};

export default config;
