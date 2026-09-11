/**
 * Shared HTTP error shape for every `src/api/*` module.
 *
 * Callers narrow a caught value with `isApiError` to reach the backend's own
 * `detail` message and the HTTP status. Modules that throw a bare `Error`
 * instead are invisible to that guard, so every failing fetch should go
 * through `throwApiError` rather than constructing its own message.
 */

export type ApiError = {
  status: number
  message: string
}

export const isApiError = (e: unknown): e is ApiError =>
  typeof e === "object" && e !== null && "status" in e && "message" in e

/**
 * The message to show a user for anything thrown by an API call or a browser
 * ceremony, falling back only when the value carries none.
 *
 * `isApiError` narrows the backend's own errors, but a WebAuthn ceremony
 * rejects with a DOMException, which fails that guard — so a generic fallback
 * used to swallow the one line naming the cause ("The relying party ID is not
 * a registrable domain suffix of ... the current domain" when WEBAUTHN_RP_ID
 * does not match the origin the browser is on). Prefer whatever message the
 * thrown value actually has.
 */
export const errorMessage = (e: unknown, fallback: string): string => {
  const message =
    typeof e === "object" && e !== null
      ? (e as { message?: unknown }).message
      : undefined
  return typeof message === "string" && message !== "" ? message : fallback
}

/**
 * Read the backend's error message out of a failed response.
 *
 * FastAPI puts a plain string in `detail` for raised HTTPExceptions, but a
 * 422 carries a list of `{ msg }` validation errors instead; both are handled
 * so a validation failure reaches the user as something readable rather than
 * the bare status code. Falls back to `defaultMessage` for a non-JSON or
 * unrecognised body.
 */
const extractErrorMessage = async (
  res: Response,
  defaultMessage: string,
): Promise<string> => {
  try {
    const body = (await res.json()) as { detail?: unknown }
    if (typeof body.detail === "string" && body.detail) return body.detail
    if (Array.isArray(body.detail)) {
      const msgs = body.detail
        .map((d) =>
          d && typeof d === "object" && "msg" in d
            ? String((d as { msg: unknown }).msg)
            : null,
        )
        .filter((m): m is string => m !== null)
      if (msgs.length > 0) return msgs.join("; ")
    }
  } catch {
    // non-JSON body; fall through to the default
  }
  return defaultMessage
}

/**
 * Throw a failed response as an `ApiError`, preferring the backend's own
 * message over `defaultMessage`. Never returns.
 */
export const throwApiError = async (
  res: Response,
  defaultMessage: string,
): Promise<never> => {
  const message = await extractErrorMessage(res, defaultMessage)
  throw { status: res.status, message } satisfies ApiError
}

/**
 * Perform an API request and return its parsed body.
 *
 * Every `src/api/*` call goes through here, so the things each call used to
 * restate — `credentials: "include"`, the JSON content-type, the ok-check —
 * live in one place and cannot be forgotten at a call site.
 *
 * - A plain-object `body` is JSON-encoded and gets the content-type header.
 * - A `FormData` body passes through untouched: the browser must set its own
 *   multipart boundary, and adding a content-type header would break it.
 * - A non-ok response throws `ApiError` carrying the backend's own message.
 * - 204 and empty bodies resolve to `undefined` rather than failing in `json()`.
 */
export type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown
  errorMessage?: string
}

/**
 * Endpoints where a 401 answers the request rather than reporting that the
 * session has gone: the pre-auth ceremonies, recovery-code redemption (a wrong
 * code is a 401), and `/auth/me`, whose caller distinguishes "not signed in"
 * from "this instance has never been set up" and routes to /setup accordingly.
 * Everywhere else a 401 means the cookie expired or was revoked.
 */
const PRE_AUTH_PATHS = [
  "/api/auth/me",
  "/api/auth/login/",
  "/api/auth/register/",
  "/api/auth/recovery/redeem",
  "/api/auth/invites/redeem/",
  "/api/setup",
]

/**
 * Whether a signed-in session has been observed in this page load.
 *
 * Public pages make authenticated calls that legitimately 401 — the theme
 * preference and the dojo settings load on /login and /setup too — so a 401
 * alone does not mean "your session ended". Only a 401 *after* the app has
 * seen a session is an expiry. Reset by any full page load, which is also
 * what a redirect to /login causes.
 */
let sessionEstablished = false

/** Called once the authenticated layout has a user (see App.tsx). */
export const markSessionEstablished = (): void => {
  sessionEstablished = true
}

/**
 * Send an expired session back to the login page.
 *
 * A full navigation rather than a router push: this is reachable from any
 * component and from outside the router, and throwing the SPA's state away is
 * the point — the alternative is a signed-out app still rendering a sidebar
 * and a members list. The session-expiry cliff (#387) used to surface as
 * "Not authorized" toasts from every action with no way back but a reload.
 */
const redirectToLogin = (path: string): void => {
  if (!sessionEstablished) return
  const { pathname } = new URL(path, window.location.origin)
  if (PRE_AUTH_PATHS.some((p) => pathname.startsWith(p))) return
  if (window.location.pathname === "/login") return
  window.location.assign("/login")
}

/**
 * Send a request the way every api module should, and hand back the raw
 * `Response` without inspecting it.
 *
 * `request` covers the common case. This exists for the handful of calls that
 * must read the failed response themselves — the check-in window's structured
 * 403 detail, a 404 that means "not found" rather than "error" — and would
 * otherwise reach for `fetch` directly and lose the credentials and encoding
 * rules along with it.
 *
 * A 401 that is not one of the pre-auth cases sends the user to /login, so an
 * expired session reads as a sign-out rather than as a broken app (#387).
 */
export const apiFetch = async (
  path: string,
  { body, headers, ...init }: Omit<RequestOptions, "errorMessage"> = {},
): Promise<Response> => {
  const isFormData = body instanceof FormData
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers:
      body === undefined || isFormData
        ? headers
        : { "Content-Type": "application/json", ...headers },
    body: isFormData
      ? (body as FormData)
      : body === undefined
        ? undefined
        : JSON.stringify(body),
  })

  if (response.status === 401) redirectToLogin(path)
  return response
}

export const request = async <T>(
  path: string,
  { errorMessage = "Request failed", ...options }: RequestOptions = {},
): Promise<T> => {
  const response = await apiFetch(path, options)

  if (!response.ok) await throwApiError(response, errorMessage)
  if (response.status === 204) return undefined as T

  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}
