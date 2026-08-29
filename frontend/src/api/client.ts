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
 * Send a request the way every api module should, and hand back the raw
 * `Response` without inspecting it.
 *
 * `request` covers the common case. This exists for the handful of calls that
 * must read the failed response themselves — the check-in window's structured
 * 403 detail, a 404 that means "not found" rather than "error" — and would
 * otherwise reach for `fetch` directly and lose the credentials and encoding
 * rules along with it.
 */
export const apiFetch = async (
  path: string,
  { body, headers, ...init }: Omit<RequestOptions, "errorMessage"> = {},
): Promise<Response> => {
  const isFormData = body instanceof FormData
  return fetch(path, {
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
