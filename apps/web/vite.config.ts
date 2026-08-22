import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Bound to 0.0.0.0:5173 so the compose healthcheck (wget from inside the
// container) and host access both work without a second config.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
  },
});
