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
    },
  },
  plugins: [],
};

export default config;
