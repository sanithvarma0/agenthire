import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The web app calls its own origin; these paths go on to the back end, so the
// browser never needs cross-origin requests (and the same holds once deployed).
// BACKEND_URL points a second dev server at a scratch back end, for checks that should not
// touch data/agenthire.db.
const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
const API_PATHS = ["/jobs", "/roles", "/apply", "/location", "/providers", "/events", "/conversations", "/health"];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(API_PATHS.map((path) => [path, BACKEND])),
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
} as never);
