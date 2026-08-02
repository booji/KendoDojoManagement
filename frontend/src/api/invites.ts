import type { ApiError, PasskeyCreationOptions, RegisterResponse } from "@/api/auth"
import { runPasskeyCreationCeremony } from "@/api/auth"

export type InviteStatus = "pending" | "redeemed" | "expired" | "revoked"

export type InviteListItem = {
  id: string
  email: string
  first_name: string
  surname: string
  status: InviteStatus
  issued_by: string | null
  expires_at: string
  redeemed_at: string | null
  revoked_at: string | null
  created_at: string
}

export type InviteMintResponse = {
  id: string
  email: string
  token: string
  link: string
  expires_at: string
}

const throwApiError = async (res: Response, defaultMessage: string): Promise<never> => {
  let message = defaultMessage
  try {
    const body = (await res.json()) as { detail?: string }
    if (body.detail) message = body.detail
  } catch {
    // ignore parse errors
  }
  throw { status: res.status, message } satisfies ApiError
}

// --- Admin invite management ---

export const issueInvite = async (
  email: string,
  firstName: string,
  surname: string,
): Promise<InviteMintResponse> => {
  const res = await fetch("/api/auth/admin/invites", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, first_name: firstName, surname }),
  })
  if (!res.ok) {
    await throwApiError(res, "Failed to issue invite")
  }
  return res.json() as Promise<InviteMintResponse>
}

export const listInvites = async (): Promise<InviteListItem[]> => {
  const res = await fetch("/api/auth/admin/invites", { credentials: "include" })
  if (!res.ok) {
    await throwApiError(res, "Failed to load invites")
  }
  return res.json() as Promise<InviteListItem[]>
}

export const revokeInvite = async (
  id: string
): Promise<{ id: string; status: InviteStatus }> => {
  const res = await fetch(`/api/auth/admin/invites/${id}/revoke`, {
    method: "POST",
    credentials: "include",
  })
  if (res.status === 404) {
    await throwApiError(res, "Invite not found")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to revoke invite")
  }
  return res.json() as Promise<{ id: string; status: InviteStatus }>
}

// --- Invite redemption (public, unauthenticated) ---
//
// The server deliberately makes unknown/expired/revoked/already-redeemed tokens
// indistinguishable (same status code, same body shape, constant-time floor) so an
// attacker probing invite links can't learn anything about their state. Every failure
// path here — including a cancelled or failed WebAuthn ceremony — collapses to the
// same generic ApiError; callers must not attempt to show a more specific reason.
const GENERIC_INVITE_FAILURE: ApiError = {
  status: 0,
  message: "This invite link is invalid or has expired.",
}

const inviteRedeemBegin = async (token: string): Promise<PasskeyCreationOptions> => {
  const res = await fetch("/api/auth/invites/redeem/begin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) {
    throw GENERIC_INVITE_FAILURE
  }
  const data = (await res.json()) as { publicKey: PasskeyCreationOptions }
  return data.publicKey
}

const inviteRedeemComplete = async (
  token: string,
  credential: object
): Promise<RegisterResponse> => {
  const res = await fetch("/api/auth/invites/redeem/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, credential }),
  })
  if (!res.ok) {
    throw GENERIC_INVITE_FAILURE
  }
  return res.json() as Promise<RegisterResponse>
}

// Drives the full passkey-registration ceremony for an invite token, reusing the same
// navigator.credentials.create() plumbing as self-service passkey registration. Any
// failure along the way — bad token, cancelled ceremony, network error — surfaces as
// the single GENERIC_INVITE_FAILURE so the landing page has nothing reason-specific to
// leak.
export const performInviteRedemption = async (token: string): Promise<RegisterResponse> => {
  const options = await inviteRedeemBegin(token)

  let credentialData: object
  try {
    credentialData = await runPasskeyCreationCeremony(options)
  } catch {
    throw GENERIC_INVITE_FAILURE
  }

  return inviteRedeemComplete(token, credentialData)
}
