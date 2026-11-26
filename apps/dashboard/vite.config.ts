import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs on :8000 (or VITE_API_TARGET); in production nginx serves the built
// dashboard and proxies /api to the API container, so the browser always talks to a single origin.
const target = process.env.VITE_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target, changeOrigin: false } } },
  build: { sourcemap: false, chunkSizeWarningLimit: 900 },
  test: { environment: "node", include: ["tests/**/*.test.ts"] },
});
