import type { MemberResponse } from "@/api/members"

export type SelfUpdateMemberRequest = {
  first_name?: string
  surname?: string
  display_name?: string | null
  dob?: string
  emergency_contact_name?: string | null
  emergency_contact_phone?: string | null
}

export const getMyMember = async (): Promise<MemberResponse | null> => {
  const res = await fetch("/api/users/me/member", { credentials: "include" })
  if (res.status === 404) return null
  if (!res.ok) throw new Error("Failed to fetch member profile")
  return res.json() as Promise<MemberResponse>
}

export const putMyMember = async (data: SelfUpdateMemberRequest): Promise<MemberResponse> => {
  const res = await fetch("/api/users/me/member", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? "Failed to save profile")
  }
  return res.json() as Promise<MemberResponse>
}
