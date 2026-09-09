import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

import { hmrOptions } from "./hmrOptions"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Behind Traefik the HMR client would infer ws://dojo.localhost:5173 from
    // the page URL — neither the right scheme nor the right port. Set only
    // when the proxy is actually in front (docker-compose.dev.yml exports it),
    // because runs with the variable unset — the test container, a bare
    // `npm run dev` — must keep dialling their own origin. Note the dev stack
    // exports it in the same container that publishes :5173, so the direct
    // :5173 escape hatch still gets an HMR client pointed at the proxy.
    // See docs/adr/0002-traefik-in-the-dev-stack.md.
    ws: hmrOptions(process.env.DEV_PROXY_ORIGIN),
    proxy: {
      "/health": process.env.BACKEND_URL ?? "http://localhost:8000",
      "/static": process.env.BACKEND_URL ?? "http://localhost:8000",
      // No rewrite: the backend serves its routers under /api too, so the dev
      // proxy and production use identical URLs (ADR-0001).
      "/api": process.env.BACKEND_URL ?? "http://localhost:8000",
    },
  },
})
