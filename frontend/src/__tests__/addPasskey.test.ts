/**
 * Adding a passkey names the Account by the caller's session, never by email
 * (#443, #472). Settings and the post-recovery page go through
 * /api/auth/passkeys/register/*, which the backend scopes to the session
 * cookie or the recovery token.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

import { performPasskeyAdd } from "@/api/auth"

const buffer = () => new Uint8Array([1, 2, 3]).buffer

const options = {
  publicKey: {
    challenge: "AQID",
    user: { id: "AQID", name: "a@dojo.test", displayName: "a@dojo.test" },
    rp: { name: "Dojo" },
  },
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(options), { status: 200 }))
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ sub: "acc-1", show_nudge: false }), { status: 201 }),
    )
  vi.stubGlobal("fetch", fetchMock)
  vi.stubGlobal("navigator", {
    credentials: {
      create: vi.fn().mockResolvedValue({
        id: "cred",
        rawId: buffer(),
        type: "public-key",
        response: { clientDataJSON: buffer(), attestationObject: buffer() },
      }),
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const calls = () =>
  fetchMock.mock.calls.map(([path, init]: [string, RequestInit]) => ({
    path,
    headers: init.headers as Record<string, string> | undefined,
    body: init.body ? JSON.parse(init.body as string) : undefined,
  }))

describe("performPasskeyAdd", () => {
  it("runs the session-scoped ceremony without sending an email", async () => {
    const result = await performPasskeyAdd()

    expect(result).toEqual({ sub: "acc-1", show_nudge: false })
    const [begin, complete] = calls()
    expect(begin.path).toBe("/api/auth/passkeys/register/begin")
    expect(complete.path).toBe("/api/auth/passkeys/register/complete")
    expect(Object.keys(complete.body)).toEqual(["credential"])
    expect(begin.headers?.Authorization).toBeUndefined()
  })

  it("sends a recovery token as a Bearer header on both calls", async () => {
    await performPasskeyAdd("recovery.jwt")

    for (const call of calls()) {
      expect(call.headers?.Authorization).toBe("Bearer recovery.jwt")
    }
  })
})
