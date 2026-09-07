/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        serif_title: ["DM Serif Display", "Georgia", "serif"],
        sans: ["Merriweather Sans", "system-ui", "sans-serif"],
        lato: ["Lato", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        // Brand palette (blue: flow / thermal-hydraulics). Change these to re-theme the whole site.
        brand: {
          50: "#f0f9ff",
          100: "#e0f2fe",
          200: "#bae6fd",
          300: "#7dd3fc",
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
          800: "#075985",
          900: "#0c4a6e",
          950: "#082f49",
        },
        // Accent (orange: the "hot" side, matches the highlighted bar in the report figures).
        accent: {
          400: "#fb923c",
          500: "#f97316",
          600: "#ea580c",
        },
      },
    },
  },
  plugins: [],
}
