import type { MemberResponse } from "@/api/members"
import { apiFetch, request, throwApiError } from "@/api/client"

export type SelfUpdateMemberRequest = {
  first_name?: string
  surname?: string
  display_name?: string | null
  dob?: string
  emergency_contact_name?: string | null
  emergency_contact_phone?: string | null
}

export const getMyMember = async (): Promise<MemberResponse | null> => {
  const res = await apiFetch("/api/users/me/member")
  if (res.status === 404) return null
  if (!res.ok) await throwApiError(res, "Failed to fetch member profile")
  return res.json() as Promise<MemberResponse>
}

export const putMyMember = async (data: SelfUpdateMemberRequest): Promise<MemberResponse> => {
  return request<MemberResponse>("/api/users/me/member", { method: "PUT", body: data, errorMessage: "Failed to save profile" })
}
