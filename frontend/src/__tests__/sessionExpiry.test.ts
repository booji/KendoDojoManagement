/**
 * A 401 on an authenticated call means the session is gone (#387).
 *
 * Before this, every api module turned a 401 into a toast and the SPA stayed
 * rendered as if signed in: an expiry mid-session looked like the app had
 * broken rather than like a sign-out, and only a manual reload recovered.
 * apiFetch is the one seam every module already routes through, so the
 * redirect lives there — except on the pre-auth endpoints, where a 401 is a
 * legitimate answer ("wrong recovery code") rather than an expired session.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

import { apiFetch, markSessionEstablished } from "@/api/client"

const assign = vi.fn()

const respondWith = (status: number) =>
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status }))

beforeEach(() => {
  assign.mockClear()
  markSessionEstablished()
  vi.stubGlobal("location", { origin: "http://localhost:3000", pathname: "/members", assign })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("apiFetch on 401", () => {
  it("sends the user to the login page", async () => {
    respondWith(401)

    await apiFetch("/api/members")

    expect(assign).toHaveBeenCalledWith("/login")
  })

  it("leaves successful responses alone", async () => {
    respondWith(200)

    await apiFetch("/api/members")

    expect(assign).not.toHaveBeenCalled()
  })

  it("leaves a 403 alone — that is an authorization answer, not an expiry", async () => {
    respondWith(403)

    await apiFetch("/api/members")

    expect(assign).not.toHaveBeenCalled()
  })

  it.each([
    "/api/auth/login/passkey/begin",
    "/api/auth/recovery/redeem",
    "/api/auth/invites/redeem/complete",
    "/api/setup",
    "/api/auth/me",
  ])("keeps local 401 handling on %s", async (path) => {
    respondWith(401)

    await apiFetch(path)

    expect(assign).not.toHaveBeenCalled()
  })

  it("does not redirect when already on the login page", async () => {
    vi.stubGlobal("location", { origin: "http://localhost:3000", pathname: "/login", assign })
    respondWith(401)

    await apiFetch("/api/members")

    expect(assign).not.toHaveBeenCalled()
  })

  it("still returns the response so callers can read the body", async () => {
    respondWith(401)

    const res = await apiFetch("/api/members")

    expect(res.status).toBe(401)
  })
})

describe("apiFetch on 401 before any session exists", () => {
  it("leaves public pages alone", async () => {
    /**
     * /login and /setup load the theme preference and the dojo settings, both
     * of which 401 for a signed-out visitor. Redirecting on those bounced the
     * setup page straight back to /login on a fresh instance.
     */
    vi.resetModules()
    const { apiFetch: freshFetch } = await import("@/api/client")
    respondWith(401)

    await freshFetch("/api/users/me/preferences")

    expect(assign).not.toHaveBeenCalled()
  })
})
