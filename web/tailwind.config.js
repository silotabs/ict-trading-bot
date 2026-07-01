/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111827",
        paper: "#f4efe4",
        ember: "#d97706",
        pine: "#0f766e",
        roseclay: "#9f1239",
        storm: "#475569",
      },
      boxShadow: {
        panel: "0 24px 60px rgba(17, 24, 39, 0.12)",
      },
      backgroundImage: {
        grid: "linear-gradient(to right, rgba(71, 85, 105, 0.12) 1px, transparent 1px), linear-gradient(to bottom, rgba(71, 85, 105, 0.12) 1px, transparent 1px)",
      },
      fontFamily: {
        display: ["Bahnschrift SemiCondensed", "DIN Alternate", "Arial Narrow", "sans-serif"],
        body: ["SF Pro Display", "Segoe UI", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
