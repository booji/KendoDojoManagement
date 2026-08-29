import { apiFetch, throwApiError } from "@/api/client"

export type PendingGradeEntry = {
  id: string
  member_id: string
  member_name: string
  grade: string
  display_name: string
  promoted_at: string
  status: string
}

export type GradeHistoryEntry = {
  id: string
  member_id: string
  grade: string
  display_name: string
  promoted_at: string
  assigned_by: string | null
  status: string
}

export type SetGradeRequest = {
  grade: string
  awarded_at?: string
}

export type SetGradeResponse = {
  id: string
  member_id: string
  grade: string
  display_name: string
  awarded_at: string
  assigned_by: string | null
  status: string
}

export type CurrentGradeResponse = {
  grade: string
  display_name: string
  awarded_at: string
}

export const ASSIGNABLE_GRADES: Array<{ value: string; label: string }> = [
  { value: "ROKKYUU", label: "Rokkyū (6-kyu)" },
  { value: "GOKYUU", label: "Gokyū (5-kyu)" },
  { value: "YONKYUU", label: "Yonkyū (4-kyu)" },
  { value: "SANKYUU", label: "Sankyū (3-kyu)" },
  { value: "NIKYUU", label: "Nikyū (2-kyu)" },
  { value: "IKKYUU", label: "Ikkyū (1-kyu)" },
  { value: "SHODAN", label: "Shodan (1-dan)" },
  { value: "NIDAN", label: "Nidan (2-dan)" },
  { value: "SANDAN", label: "Sandan (3-dan)" },
  { value: "YONDAN", label: "Yondan (4-dan)" },
  { value: "GODAN", label: "Godan (5-dan)" },
  { value: "ROKUDAN", label: "Rokudan (6-dan)" },
  { value: "NANADAN", label: "Nanadan (7-dan)" },
  { value: "HACHIDAN", label: "Hachidan (8-dan)" },
]

export const setMemberGrade = async (
  memberId: string,
  body: SetGradeRequest
): Promise<SetGradeResponse> => {
  const res = await apiFetch(`/api/members/${memberId}/grades`, { method: "POST", body: body })

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 404) {
    await throwApiError(res, "Member not found")
  }
  if (res.status === 422) {
    await throwApiError(res, "Invalid grade")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to set grade")
  }

  return res.json() as Promise<SetGradeResponse>
}

export const proposeGrade = async (
  memberId: string,
  body: SetGradeRequest
): Promise<SetGradeResponse> => {
  const res = await apiFetch(`/api/members/${memberId}/grades/propose`, { method: "POST", body: body })

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 404) {
    await throwApiError(res, "Member not found")
  }
  if (res.status === 422) {
    await throwApiError(res, "Invalid grade")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to propose grade")
  }

  return res.json() as Promise<SetGradeResponse>
}

export const getCurrentGrade = async (
  memberId: string
): Promise<CurrentGradeResponse | null> => {
  const res = await apiFetch(`/api/members/${memberId}/grades/current`)

  if (res.status === 404) {
    return null
  }
  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load current grade")
  }

  return res.json() as Promise<CurrentGradeResponse>
}

export const approveGrade = async (
  memberId: string,
  entryId: string
): Promise<GradeHistoryEntry> => {
  const res = await apiFetch(`/api/members/${memberId}/grades/${entryId}/approve`, { method: "POST" })
  if (res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Grade entry not found")
  if (res.status === 409) await throwApiError(res, "Entry is not pending")
  if (!res.ok) await throwApiError(res, "Failed to approve grade")
  return res.json() as Promise<GradeHistoryEntry>
}

export const rejectGrade = async (
  memberId: string,
  entryId: string
): Promise<void> => {
  const res = await apiFetch(`/api/members/${memberId}/grades/${entryId}`, { method: "DELETE" })
  if (res.status === 403) await throwApiError(res, "Not authorized")
  if (res.status === 404) await throwApiError(res, "Grade entry not found")
  if (res.status === 409) await throwApiError(res, "Only pending entries may be rejected")
  if (!res.ok) await throwApiError(res, "Failed to reject grade")
}

export const listPendingGrades = async (): Promise<PendingGradeEntry[]> => {
  const res = await apiFetch("/api/grades/pending")
  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load pending grades")
  }
  return res.json() as Promise<PendingGradeEntry[]>
}

export const getGradeHistory = async (memberId: string): Promise<GradeHistoryEntry[]> => {
  const res = await apiFetch(`/api/members/${memberId}/grades`)

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 404) {
    await throwApiError(res, "Member not found")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to load grade history")
  }

  return res.json() as Promise<GradeHistoryEntry[]>
}
