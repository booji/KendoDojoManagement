import { apiFetch, throwApiError } from "@/api/client"

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

export type FederationCreateRequest = {
  name: string
  abbreviation?: string
  iso_code?: string
  website?: string
  continental_grouping?: string
  type?: string
  is_pinned?: boolean
  is_active?: boolean
}

export type FederationUpdateRequest = Partial<FederationCreateRequest>

// ── Federation catalogue ──────────────────────────────────────────────────────

export const listFederations = async (params?: {
  search?: string
  type?: string
  continental_grouping?: string
}): Promise<FederationResponse[]> => {
  const qs = new URLSearchParams()
  if (params?.search) qs.set("search", params.search)
  if (params?.type) qs.set("type", params.type)
  if (params?.continental_grouping) qs.set("continental_grouping", params.continental_grouping)
  const query = qs.toString()
  const url = query ? `/api/federations?${query}` : `/api/federations`
  const res = await apiFetch(url)
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (!res.ok) await throwApiError(res, "Failed to load federations")
  return res.json() as Promise<FederationResponse[]>
}

export const createFederation = async (
  body: FederationCreateRequest
): Promise<FederationResponse> => {
  const res = await apiFetch(`/api/federations`, { method: "POST", body: body })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 409) await throwApiError(res, "A federation with this name already exists")
  if (!res.ok) await throwApiError(res, "Failed to create federation")
  return res.json() as Promise<FederationResponse>
}

export const updateFederation = async (
  id: string,
  body: FederationUpdateRequest
): Promise<FederationResponse> => {
  const res = await apiFetch(`/api/federations/${id}`, { method: "PUT", body: body })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation not found")
  if (!res.ok) await throwApiError(res, "Failed to update federation")
  return res.json() as Promise<FederationResponse>
}

export const deactivateFederation = async (id: string): Promise<FederationResponse> => {
  const res = await apiFetch(`/api/federations/${id}`, { method: "DELETE" })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation not found")
  if (!res.ok) await throwApiError(res, "Failed to deactivate federation")
  return res.json() as Promise<FederationResponse>
}

// ── Self-service (member's own profile) ───────────────────────────────────────

export const getMyFederations = async (): Promise<MemberFederationResponse[]> => {
  const res = await apiFetch(`/api/users/me/federations`)
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (!res.ok) await throwApiError(res, "Failed to load federation memberships")
  return res.json() as Promise<MemberFederationResponse[]>
}

export const addMyFederation = async (
  body: MemberFederationCreateRequest
): Promise<MemberFederationResponse> => {
  const res = await apiFetch(`/api/users/me/federations`, { method: "POST", body: body })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 409) await throwApiError(res, "Already a member of this federation")
  if (!res.ok) await throwApiError(res, "Failed to add federation membership")
  return res.json() as Promise<MemberFederationResponse>
}

export const updateMyFederation = async (
  mfId: string,
  body: MemberFederationUpdateRequest
): Promise<MemberFederationResponse> => {
  const res = await apiFetch(`/api/users/me/federations/${mfId}`, { method: "PUT", body: body })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation membership not found")
  if (!res.ok) await throwApiError(res, "Failed to update federation membership")
  return res.json() as Promise<MemberFederationResponse>
}

export const deleteMyFederation = async (mfId: string): Promise<void> => {
  const res = await apiFetch(`/api/users/me/federations/${mfId}`, { method: "DELETE" })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation membership not found")
  if (!res.ok) await throwApiError(res, "Failed to remove federation membership")
}

// ── Admin (managing any member) ───────────────────────────────────────────────

export const getMemberFederations = async (
  memberId: string
): Promise<MemberFederationResponse[]> => {
  const res = await apiFetch(`/api/members/${memberId}/federations`)
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Member not found")
  if (!res.ok) await throwApiError(res, "Failed to load federation memberships")
  return res.json() as Promise<MemberFederationResponse[]>
}

export const addMemberFederation = async (
  memberId: string,
  body: MemberFederationCreateRequest
): Promise<MemberFederationResponse> => {
  const res = await apiFetch(`/api/members/${memberId}/federations`, { method: "POST", body: body })
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
  const res = await apiFetch(`/api/members/${memberId}/federations/${mfId}`, { method: "PUT", body: body })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation membership not found")
  if (!res.ok) await throwApiError(res, "Failed to update federation membership")
  return res.json() as Promise<MemberFederationResponse>
}

export const deleteMemberFederation = async (memberId: string, mfId: string): Promise<void> => {
  const res = await apiFetch(`/api/members/${memberId}/federations/${mfId}`, { method: "DELETE" })
  if (res.status === 401 || res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Federation membership not found")
  if (!res.ok) await throwApiError(res, "Failed to remove federation membership")
}
