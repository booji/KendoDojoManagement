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
