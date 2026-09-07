/**
 * Unit tests for errorMessage (issue #374 follow-up).
 *
 * A WebAuthn ceremony rejects with a DOMException, not an ApiError, so every
 * `isApiError(err) ? err.message : "An unexpected error occurred"` discarded
 * the one line that named the cause — "The relying party ID is not a
 * registrable domain suffix of ... the current domain" became "An unexpected
 * error occurred", and a wrong-origin dev stack looked like a broken app.
 */

import { describe, it, expect } from "vitest"

import { errorMessage } from "@/api/client"

describe("errorMessage", () => {
  it("prefers the backend's message on an ApiError", () => {
    expect(errorMessage({ status: 400, message: "Email already used" }, "fallback")).toBe(
      "Email already used",
    )
  })

  it("surfaces a DOMException's message rather than the fallback", () => {
    const err = new DOMException(
      "The relying party ID is not a registrable domain suffix of, nor equal to, the current domain.",
      "SecurityError",
    )
    expect(errorMessage(err, "An unexpected error occurred")).toContain(
      "relying party ID",
    )
  })

  it("surfaces a plain Error's message", () => {
    expect(errorMessage(new Error("Network request failed"), "fallback")).toBe(
      "Network request failed",
    )
  })

  it("falls back when the value carries no usable message", () => {
    expect(errorMessage("boom", "fallback")).toBe("fallback")
    expect(errorMessage(null, "fallback")).toBe("fallback")
    expect(errorMessage({ message: "" }, "fallback")).toBe("fallback")
  })
})
