import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/health": process.env.BACKEND_URL ?? "http://localhost:8000",
      "/static": process.env.BACKEND_URL ?? "http://localhost:8000",
      // No rewrite: the backend serves its routers under /api too, so the dev
      // proxy and production use identical URLs (ADR-0001).
      "/api": process.env.BACKEND_URL ?? "http://localhost:8000",
    },
  },
})
