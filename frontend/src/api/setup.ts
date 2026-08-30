import { apiFetch } from "@/api/client"

import type { UserClaims, ApiError } from "@/api/auth"

// --- WebAuthn buffer helpers (copied from auth.ts — not exported there) ---

const base64urlToBuffer = (base64url: string): ArrayBuffer => {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/")
  const padded = base64.padEnd(base64.length + (4 - (base64.length % 4)) % 4, "=")
  const binary = atob(padded)
  const buffer = new ArrayBuffer(binary.length)
  const bytes = new Uint8Array(buffer)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return buffer
}

const bufferToBase64url = (buffer: ArrayBuffer): string => {
  const bytes = new Uint8Array(buffer)
  let binary = ""
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "")
}

type PasskeyCreationOptions = {
  challenge: string
  user: { id: string; name: string; displayName: string }
  rp: { name: string; id?: string }
  pubKeyCredParams?: PublicKeyCredentialParameters[]
  timeout?: number
  attestation?: AttestationConveyancePreference
  excludeCredentials?: Array<{ id: string; type: string; transports?: AuthenticatorTransport[] }>
  authenticatorSelection?: AuthenticatorSelectionCriteria
}

/**
 * Returns true if the instance has no users yet (setup available),
 * false if setup is already completed.
 */
export const checkSetupAvailable = async (): Promise<boolean> => {
  const res = await apiFetch("/api/setup")
  if (res.status === 200) return true
  if (res.status === 404) return false
  throw { status: res.status, message: "Failed to check setup status" } satisfies ApiError
}

/**
 * Runs the full passkey registration ceremony against /api/setup/passkey/begin
 * and /api/setup/passkey/complete, returning UserClaims for the new admin.
 */
export const performSetupPasskeyRegistration = async (email: string): Promise<UserClaims> => {
  // Begin
  const beginRes = await apiFetch("/api/setup/passkey/begin", { method: "POST", body: { email } })
  if (!beginRes.ok) {
    throw { status: beginRes.status, message: "Failed to begin setup passkey registration" } satisfies ApiError
  }
  const beginData = (await beginRes.json()) as { publicKey: PasskeyCreationOptions }
  const options = beginData.publicKey

  // Run WebAuthn ceremony
  const publicKey: PublicKeyCredentialCreationOptions = {
    challenge: base64urlToBuffer(options.challenge),
    rp: options.rp,
    user: {
      id: base64urlToBuffer(options.user.id),
      name: options.user.name,
      displayName: options.user.displayName,
    },
    pubKeyCredParams: options.pubKeyCredParams ?? [{ type: "public-key", alg: -7 }],
    ...(options.timeout !== undefined && { timeout: options.timeout }),
    ...(options.attestation !== undefined && { attestation: options.attestation }),
    ...(options.authenticatorSelection !== undefined && {
      authenticatorSelection: options.authenticatorSelection,
    }),
    ...(options.excludeCredentials !== undefined && {
      excludeCredentials: options.excludeCredentials.map((c) => ({
        id: base64urlToBuffer(c.id),
        type: c.type as PublicKeyCredentialType,
        ...(c.transports !== undefined && { transports: c.transports }),
      })),
    }),
  }

  const credential = await navigator.credentials.create({ publicKey })
  if (credential === null) {
    throw { status: 0, message: "No credential returned from authenticator" } satisfies ApiError
  }

  const cred = credential as PublicKeyCredential
  const response = cred.response as AuthenticatorAttestationResponse
  const credentialData = {
    id: cred.id,
    rawId: bufferToBase64url(cred.rawId),
    response: {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      attestationObject: bufferToBase64url(response.attestationObject),
    },
    type: cred.type,
  }

  // Complete
  const completeRes = await apiFetch("/api/setup/passkey/complete", { method: "POST", body: { email, credential: credentialData } })
  if (!completeRes.ok) {
    throw { status: completeRes.status, message: "Setup passkey registration failed" } satisfies ApiError
  }
  return completeRes.json() as Promise<UserClaims>
}
