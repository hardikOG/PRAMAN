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
        // Shopper-facing "daylight" surface: same semantic hues (seal/amber/
        // stamp) on a light, high-contrast ground, because the person
        // confirming a purchase is on a phone in daylight, not an engineer
        // at a desk — see src/components/ShopperConfirm.tsx.
        day: "#F4F6FA",
        daycard: "#FFFFFF",
        daytext: "#0B1220",
        daymuted: "#4A5A75",
        dayline: "#D9E0EC",
        dayamber: "#FFF4E0",
        dayamberline: "#E8A33D",
        dayseal: "#0F7B63",
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
