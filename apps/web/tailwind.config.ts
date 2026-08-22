import type { Config } from "tailwindcss";

// Design tokens from PRAMAN_BUILD.md §7 — the console reads as a records
// office, not a crypto exchange. Full screens land in Phase 7; this wires
// the palette now so nothing drifts from spec later.
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0B1220",
        surface: "#131C2E",
        raised: "#1A2540",
        line: "#22304A",
        paper: "#E8EDF5",
        muted: "#8095B3",
        seal: "#4CC2A6",
        amber: "#E8A33D",
        stamp: "#E0524D",
        chain: "#6C8CFF",
      },
      fontFamily: {
        heading: ["Archivo", "sans-serif"],
        body: ["Public Sans", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        DEFAULT: "4px",
      },
    },
  },
  plugins: [],
};

export default config;
