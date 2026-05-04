import type { ApiError } from "@/api/auth"

// ── Types ─────────────────────────────────────────────────────────────────────

export type FederationResponse = {
  id: string
  name: string
  abbreviation: string | null
  iso_code: string | null
  website: string | null
  continental_grouping: string | null
  type: string | null
  is_pinned: boolean
  is_active: boolean
}

export type RenewalStatus = "expiring_soon" | "expired" | null

export type MemberFederationResponse = {
  id: string
  member_id: string
  federation_id: string
  member_number: string
  renewal_date: string | null
  renewal_status: RenewalStatus
}

export type MemberFederationCreateRequest = {
  federation_id: string
  member_number: string
  renewal_date?: string
}

export type MemberFederationUpdateRequest = {
  member_number?: string
  renewal_date?: string | null
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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

// ── Federation catalogue ──────────────────────────────────────────────────────

export const listFederations = async (search?: string): Promise<FederationResponse[]> => {
  const url = search
    ? `/api/federations?search=${encodeURIComponent(search)}`
    : `/api/federations`
  const res = await fetch(url, { credentials: "include" })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (!res.ok) await throwApiError(res, "Failed to load federations")
  return res.json() as Promise<FederationResponse[]>
}

// ── Self-service (member's own profile) ───────────────────────────────────────

export const getMyFederations = async (): Promise<MemberFederationResponse[]> => {
  const res = await fetch(`/api/users/me/federations`, { credentials: "include" })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (!res.ok) await throwApiError(res, "Failed to load federation memberships")
  return res.json() as Promise<MemberFederationResponse[]>
}

export const addMyFederation = async (
  body: MemberFederationCreateRequest
): Promise<MemberFederationResponse> => {
  const res = await fetch(`/api/users/me/federations`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 409) await throwApiError(res, "Already a member of this federation")
  if (!res.ok) await throwApiError(res, "Failed to add federation membership")
  return res.json() as Promise<MemberFederationResponse>
}

export const updateMyFederation = async (
  mfId: string,
  body: MemberFederationUpdateRequest
): Promise<MemberFederationResponse> => {
  const res = await fetch(`/api/users/me/federations/${mfId}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation membership not found")
  if (!res.ok) await throwApiError(res, "Failed to update federation membership")
  return res.json() as Promise<MemberFederationResponse>
}

export const deleteMyFederation = async (mfId: string): Promise<void> => {
  const res = await fetch(`/api/users/me/federations/${mfId}`, {
    method: "DELETE",
    credentials: "include",
  })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation membership not found")
  if (!res.ok) await throwApiError(res, "Failed to remove federation membership")
}

// ── Admin (managing any member) ───────────────────────────────────────────────

export const getMemberFederations = async (
  memberId: string
): Promise<MemberFederationResponse[]> => {
  const res = await fetch(`/api/members/${memberId}/federations`, { credentials: "include" })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Member not found")
  if (!res.ok) await throwApiError(res, "Failed to load federation memberships")
  return res.json() as Promise<MemberFederationResponse[]>
}

export const addMemberFederation = async (
  memberId: string,
  body: MemberFederationCreateRequest
): Promise<MemberFederationResponse> => {
  const res = await fetch(`/api/members/${memberId}/federations`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Member not found")
  if (res.status === 409) await throwApiError(res, "Already a member of this federation")
  if (!res.ok) await throwApiError(res, "Failed to add federation membership")
  return res.json() as Promise<MemberFederationResponse>
}

export const updateMemberFederation = async (
  memberId: string,
  mfId: string,
  body: MemberFederationUpdateRequest
): Promise<MemberFederationResponse> => {
  const res = await fetch(`/api/members/${memberId}/federations/${mfId}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation membership not found")
  if (!res.ok) await throwApiError(res, "Failed to update federation membership")
  return res.json() as Promise<MemberFederationResponse>
}

export const deleteMemberFederation = async (memberId: string, mfId: string): Promise<void> => {
  const res = await fetch(`/api/members/${memberId}/federations/${mfId}`, {
    method: "DELETE",
    credentials: "include",
  })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation membership not found")
  if (!res.ok) await throwApiError(res, "Failed to remove federation membership")
}
