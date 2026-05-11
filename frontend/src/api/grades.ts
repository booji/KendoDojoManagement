import type { ApiError } from "@/api/auth"

export type GradeHistoryEntry = {
  id: string
  member_id: string
  grade: string
  display_name: string
  promoted_at: string
  assigned_by: string
  status: string
}

export type PromoteResponse = {
  id: string
  member_id: string
  grade: string
  display_name: string
  promoted_at: string
  assigned_by: string
  status: string
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

export const promoteMember = async (memberId: string): Promise<PromoteResponse> => {
  const res = await fetch(`/api/members/${memberId}/promote`, {
    method: "POST",
    credentials: "include",
  })

  if (res.status === 401 || res.status === 403) {
    await throwApiError(res, "Not authorized")
  }
  if (res.status === 404) {
    await throwApiError(res, "Member not found")
  }
  if (res.status === 409) {
    await throwApiError(res, "Member is already at the highest grade")
  }
  if (!res.ok) {
    await throwApiError(res, "Failed to promote member")
  }

  return res.json() as Promise<PromoteResponse>
}

export const getGradeHistory = async (memberId: string): Promise<GradeHistoryEntry[]> => {
  const res = await fetch(`/api/members/${memberId}/grades`, {
    credentials: "include",
  })

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
