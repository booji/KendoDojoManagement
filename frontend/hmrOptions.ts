/**
 * WebSocket client settings for a Vite dev server running behind a reverse
 * proxy (`server.ws`, which HMR dials).
 *
 * Without a proxy origin the client keeps dialling its own origin (the test
 * container and the direct :5173 escape hatch). With one, host and scheme are
 * pinned to the proxy; the port is pinned only when the origin names one, so a
 * portless origin (https://dojo.localhost) leaves the client to infer the port
 * from the page, and keeps Vite's direct-websocket fallback. See docs/adr/0002-traefik-in-the-dev-stack.md.
 */
export function hmrOptions(origin: string | undefined) {
  if (!origin) return undefined
  let url: URL
  try {
    url = new URL(origin)
  } catch {
    throw new Error(`DEV_PROXY_ORIGIN is not a valid URL: ${origin}`)
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new Error(`DEV_PROXY_ORIGIN must be an http(s) URL: ${origin}`)
  }
  return {
    protocol: url.protocol === "https:" ? "wss" : "ws",
    host: url.hostname,
    ...(url.port ? { clientPort: Number(url.port) } : {}),
  }
}
