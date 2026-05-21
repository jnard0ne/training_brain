/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0a",
        panel: "#171717",
        border: "#262626",
        muted: "#737373",
        text: "#e5e5e5",
        accent: "#60a5fa",
        ok: "#16a34a",
        warn: "#f59e0b",
        err: "#dc2626",
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SF Mono", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
