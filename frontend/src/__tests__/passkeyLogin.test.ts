/**
 * The login ceremony reports how the authenticator was attached, so the app can
 * offer a passkey for this device after a sign-in from a phone (#612).
 */

import { describe, it, expect, vi, afterEach } from "vitest"

import { performPasskeyLogin } from "@/api/auth"

const buffer = () => new Uint8Array([1, 2, 3]).buffer

const stubLogin = (authenticatorAttachment?: string | null) => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ publicKey: { challenge: "AQID" } }), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "ok" }), { status: 200 })),
  )
  vi.stubGlobal("navigator", {
    credentials: {
      get: vi.fn().mockResolvedValue({
        id: "cred",
        rawId: buffer(),
        type: "public-key",
        ...(authenticatorAttachment !== undefined && { authenticatorAttachment }),
        response: {
          clientDataJSON: buffer(),
          authenticatorData: buffer(),
          signature: buffer(),
        },
      }),
    },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("performPasskeyLogin", () => {
  it("reports a cross-platform attachment", async () => {
    stubLogin("cross-platform")
    expect((await performPasskeyLogin("a@dojo.test")).authenticatorAttachment).toBe(
      "cross-platform",
    )
  })

  it("reports null when the browser omits the attachment", async () => {
    stubLogin()
    expect((await performPasskeyLogin("a@dojo.test")).authenticatorAttachment).toBeNull()
  })
})
