import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// Dev server proxies the API + WebSocket to the FastAPI backend so the SPA and
// backend share an origin in dev. In prod the backend serves the built `dist/`.
const BACKEND = process.env.SR_BACKEND ?? "http://localhost:8000";

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
  build: { outDir: "dist" },
});
