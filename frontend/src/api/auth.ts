export type RegisterResponse = {
  sub: string
  email: string
  role: "admin" | "member"
  is_active: boolean
  show_nudge?: boolean
}

export type LoginResponse = {
  detail: string
}

export type UserClaims = {
  sub: string
  email: string
  role: "admin" | "member"
  is_active: boolean
  theme: "light" | "dark" | "system"
}

export type ApiError = {
  status: number
  message: string
}

const isApiError = (e: unknown): e is ApiError =>
  typeof e === "object" && e !== null && "status" in e && "message" in e

export { isApiError }

export const getMe = async (): Promise<UserClaims> => {
  const res = await fetch("/api/auth/me", {
    credentials: "include",
  })

  if (res.status === 401 || res.status === 403) {
    throw { status: res.status, message: "Not authenticated" } satisfies ApiError
  }
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch user" } satisfies ApiError
  }

  return res.json() as Promise<UserClaims>
}

export const logout = async (): Promise<void> => {
  await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "include",
  })
}

// --- WebAuthn helpers ---

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

type PasskeyRequestOptions = {
  challenge: string
  timeout?: number
  rpId?: string
  allowCredentials?: Array<{ id: string; type: string; transports?: AuthenticatorTransport[] }>
  userVerification?: UserVerificationRequirement
}

export const registerPasskeyBegin = async (email: string): Promise<PasskeyCreationOptions> => {
  const res = await fetch("/api/auth/register/passkey/begin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to begin passkey registration" } satisfies ApiError
  }
  const data = (await res.json()) as { publicKey: PasskeyCreationOptions }
  return data.publicKey
}

export const registerPasskeyComplete = async (
  email: string,
  credential: object
): Promise<RegisterResponse> => {
  const res = await fetch("/api/auth/register/passkey/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, credential }),
  })
  if (!res.ok) {
    throw { status: res.status, message: "Passkey registration failed" } satisfies ApiError
  }
  return res.json() as Promise<RegisterResponse>
}

export const loginPasskeyBegin = async (email: string): Promise<PasskeyRequestOptions> => {
  const res = await fetch("/api/auth/login/passkey/begin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to begin passkey login" } satisfies ApiError
  }
  const data = (await res.json()) as { publicKey: PasskeyRequestOptions }
  return data.publicKey
}

export const loginPasskeyComplete = async (
  email: string,
  credential: object
): Promise<LoginResponse> => {
  const res = await fetch("/api/auth/login/passkey/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, credential }),
  })
  if (!res.ok) {
    throw { status: res.status, message: "Passkey login failed" } satisfies ApiError
  }
  return res.json() as Promise<LoginResponse>
}

export const performPasskeyRegistration = async (email: string): Promise<RegisterResponse> => {
  const options = await registerPasskeyBegin(email)

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

  return registerPasskeyComplete(email, credentialData)
}

export const performPasskeyLogin = async (email: string): Promise<LoginResponse> => {
  const options = await loginPasskeyBegin(email)

  const publicKey: PublicKeyCredentialRequestOptions = {
    ...options,
    challenge: base64urlToBuffer(options.challenge),
    allowCredentials: options.allowCredentials?.map((c) => ({
      ...c,
      id: base64urlToBuffer(c.id),
      type: c.type as PublicKeyCredentialType,
    })),
  }

  const credential = await navigator.credentials.get({ publicKey })
  if (credential === null) {
    throw { status: 0, message: "No credential returned from authenticator" } satisfies ApiError
  }

  const cred = credential as PublicKeyCredential
  const response = cred.response as AuthenticatorAssertionResponse
  const credentialData = {
    id: cred.id,
    rawId: bufferToBase64url(cred.rawId),
    response: {
      clientDataJSON: bufferToBase64url(response.clientDataJSON),
      authenticatorData: bufferToBase64url(response.authenticatorData),
      signature: bufferToBase64url(response.signature),
    },
    type: cred.type,
  }

  return loginPasskeyComplete(email, credentialData)
}

export const redeemRecoveryCode = async (
  email: string,
  code: string
): Promise<{ access_token: string }> => {
  const res = await fetch("/api/auth/recovery/redeem", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code }),
  })

  if (res.status === 401) {
    throw { status: 401, message: "Invalid or used recovery code" } satisfies ApiError
  }
  if (res.status === 429) {
    throw { status: 429, message: "Account locked. Too many failed attempts." } satisfies ApiError
  }
  if (!res.ok) {
    throw { status: res.status, message: "Recovery code redemption failed" } satisfies ApiError
  }

  return res.json() as Promise<{ access_token: string }>
}

export const updateTheme = async (theme: "light" | "dark" | "system"): Promise<UserClaims> => {
  const res = await fetch("/api/auth/me/theme", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ theme }),
  })
  if (!res.ok) throw { status: res.status, message: "Failed to update theme" } satisfies ApiError
  return res.json() as Promise<UserClaims>
}
