import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API is served under the same origin (/api) so the refresh cookie (SameSite=Strict, path /api/v1/auth)
// works: Vite proxies in development, Nginx in production.
const api = process.env.SSMS_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": api, "/health": api } },
  preview: { port: 4173, proxy: { "/api": api, "/health": api } },
  build: { target: "es2020", sourcemap: false, chunkSizeWarningLimit: 250 },
});
