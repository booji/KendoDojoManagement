import { apiFetch, throwApiError } from "@/api/client"

export type MembershipStatus = "active" | "inactive" | "suspended" | "archived"

export type MemberResponse = {
  id: string
  email: string
  first_name: string
  surname: string
  display_name: string | null
  dob: string | null
  join_date: string
  membership_status: MembershipStatus
  is_coach: boolean
  is_first_aider: boolean
  emergency_contact_name: string | null
  emergency_contact_phone: string | null
  anonymised_at: string | null
  anonymised_by: string | null
}

export type CreateMemberRequest = {
  email: string
  first_name: string
  surname: string
  display_name?: string | null
  dob?: string
  join_date: string
  membership_status?: MembershipStatus
  is_coach?: boolean
  is_first_aider?: boolean
  emergency_contact_name?: string | null
  emergency_contact_phone?: string | null
}

export type UpdateMemberRequest = {
  email?: string
  first_name?: string
  surname?: string
  display_name?: string | null
  dob?: string
  join_date?: string
  membership_status?: MembershipStatus
  is_coach?: boolean
  is_first_aider?: boolean
  emergency_contact_name?: string | null
  emergency_contact_phone?: string | null
}

export type ListMembersParams = {
  status?: MembershipStatus
  search?: string
}

export const listMembers = async (
  params?: ListMembersParams
): Promise<MemberResponse[]> => {
  const url = new URL("/api/members", window.location.origin)
  if (params?.status !== undefined) url.searchParams.set("status", params.status)
  if (params?.search !== undefined) url.searchParams.set("search", params.search)

  const res = await apiFetch(url.toString())

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load members")
  }

  return res.json() as Promise<MemberResponse[]>
}

export const getMember = async (id: string): Promise<MemberResponse> => {
  const res = await apiFetch(`/api/members/${id}`)

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 404) {
    await throwApiError(res, "Member not found")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load member")
  }

  return res.json() as Promise<MemberResponse>
}

export const createMember = async (
  data: CreateMemberRequest
): Promise<MemberResponse> => {
  const res = await apiFetch("/api/members", { method: "POST", body: data })

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 409) {
    await throwApiError(res, "Email already registered")
  }
  if (res.status === 422) {
    await throwApiError(res, "Invalid member data")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to create member")
  }

  return res.json() as Promise<MemberResponse>
}

export const updateMember = async (
  id: string,
  data: UpdateMemberRequest
): Promise<MemberResponse> => {
  const res = await apiFetch(`/api/members/${id}`, { method: "PUT", body: data })

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 404) {
    await throwApiError(res, "Member not found")
  }
  if (res.status === 422) {
    await throwApiError(res, "Invalid member data")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to update member")
  }

  return res.json() as Promise<MemberResponse>
}

export type MyMemberUpdateRequest = {
  first_name?: string
  surname?: string
  display_name?: string | null
  dob?: string
  emergency_contact_name?: string | null
  emergency_contact_phone?: string | null
}

export const getMyMember = async (): Promise<MemberResponse | null> => {
  const res = await apiFetch("/api/accounts/me/member")

  if (res.status === 404) {
    return null
  }
  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load your member details")
  }

  return res.json() as Promise<MemberResponse>
}

export const updateMyMember = async (
  data: MyMemberUpdateRequest
): Promise<MemberResponse> => {
  const res = await apiFetch("/api/accounts/me/member", { method: "PUT", body: data })

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 409) {
    await throwApiError(res, "Member record conflict — please contact support")
  }
  if (res.status === 422) {
    await throwApiError(res, "Invalid data — please check your inputs")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to save your details")
  }

  return res.json() as Promise<MemberResponse>
}

export const eraseMember = async (id: string): Promise<MemberResponse> => {
  const res = await apiFetch(`/api/members/${id}/erase`, { method: "POST" })

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 404) {
    await throwApiError(res, "Member not found")
  }
  if (res.status === 409) {
    await throwApiError(res, "Member cannot be erased")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to erase member")
  }

  return res.json() as Promise<MemberResponse>
}

export const formatMemberName = (member: Pick<MemberResponse, "display_name" | "first_name" | "surname">): string =>
  member.display_name ?? `${member.first_name} ${member.surname}`
