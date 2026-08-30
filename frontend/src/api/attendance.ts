import { apiFetch, request } from "@/api/client"

export type AttendanceRecord = {
  id: string
  session_id: string
  member_id: string | null
  visitor_name: string | null
  checked_in_at: string
  recorded_by: string
  display_name: string | null
}

export type CheckinToken = {
  token: string
  session_id: string
  expires_at: string
}

// Structured detail returned by POST /sessions/{id}/checkin when the
// check-in window (issue #192) rejects the attempt with a 403.
export type CheckinWindowError = {
  status: 403
  reason: "too_early" | "closed"
  boundary: string // ISO datetime — opens_at for too_early, closes_at for closed
  message: string
}

export const checkIn = async (sessionId: string): Promise<AttendanceRecord> => {
  const res = await apiFetch(`/api/sessions/${sessionId}/checkin`, { method: "POST" })
  if (!res.ok) {
    const status = res.status
    if (status === 401) throw { status, message: "Not authenticated" }
    if (status === 404) throw { status, message: "Session not found" }
    if (status === 403) {
      const detail = await readJsonDetail(res)
      if (
        typeof detail === "object" &&
        detail !== null &&
        "reason" in detail &&
        (detail.reason === "too_early" || detail.reason === "closed")
      ) {
        const boundary = detail.reason === "too_early" ? detail.opens_at : detail.closes_at
        throw {
          status,
          reason: detail.reason,
          boundary: typeof boundary === "string" ? boundary : "",
          message: "Check-in window is not open",
        } satisfies CheckinWindowError
      }
      throw { status, message: "Check-in is not currently allowed" }
    }
    if (status === 409) {
      const detail = await readDetail(res)
      throw { status, message: detail ?? "Session is cancelled" }
    }
    throw { status, message: "Failed to check in" }
  }
  return res.json() as Promise<AttendanceRecord>
}

// Reads the `detail` field from a JSON error body without throwing if the
// body is missing or not JSON. Used to distinguish same-status errors (e.g.
// two different 409 causes) by message content.
const readDetail = async (res: Response): Promise<string | null> => {
  try {
    const body: unknown = await res.json()
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail
      return typeof detail === "string" ? detail : null
    }
    return null
  } catch {
    return null
  }
}

// Reads the `detail` field from a JSON error body as an opaque object (used
// for the structured 403 check-in-window payload), returning null if the
// body is missing, not JSON, or not an object.
const readJsonDetail = async (res: Response): Promise<Record<string, unknown> | null> => {
  try {
    const body: unknown = await res.json()
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail
      return typeof detail === "object" && detail !== null
        ? (detail as Record<string, unknown>)
        : null
    }
    return null
  } catch {
    return null
  }
}

export const getCheckinToken = async (sessionId: string): Promise<CheckinToken> => {
  return request<CheckinToken>(`/api/sessions/${sessionId}/checkin-token`, { errorMessage: "Failed to get check-in token" })
}

export const checkinViaToken = async (token: string): Promise<AttendanceRecord> => {
  const res = await apiFetch(`/api/checkin/${token}`, { method: "POST" })
  if (!res.ok) {
    const status = res.status
    if (status === 401) throw { status, message: "Not authenticated" }
    if (status === 404) throw { status, message: "Token not found" }
    if (status === 410) throw { status, message: "Token expired" }
    if (status === 409) throw { status, message: "Session cancelled" }
    throw { status, message: "Failed to check in" }
  }
  return res.json() as Promise<AttendanceRecord>
}

export const getSessionAttendance = async (sessionId: string): Promise<AttendanceRecord[]> => {
  return request<AttendanceRecord[]>(`/api/sessions/${sessionId}/attendance`, { errorMessage: "Failed to fetch attendance" })
}

export const markAttended = async (sessionId: string, memberId: string): Promise<AttendanceRecord> => {
  const res = await apiFetch(`/api/sessions/${sessionId}/attendance`, { method: "POST", body: { member_id: memberId } })
  if (!res.ok) {
    const status = res.status
    if (status === 404) throw { status, message: "Session or member not found" }
    if (status === 409) throw { status, message: "Member already marked attended" }
    throw { status, message: "Failed to mark member attended" }
  }
  return res.json() as Promise<AttendanceRecord>
}

export const removeAttendance = async (sessionId: string, memberId: string): Promise<void> => {
  return request<void>(`/api/sessions/${sessionId}/attendance/${memberId}`, { method: "DELETE", errorMessage: "Failed to remove attendance" })
}

export const addVisitor = async (sessionId: string, visitorName: string): Promise<AttendanceRecord> => {
  return request<AttendanceRecord>(`/api/sessions/${sessionId}/visitors`, { method: "POST", body: { visitor_name: visitorName }, errorMessage: "Failed to add visitor" })
}

export const getMemberAttendanceHistory = async (memberId: string): Promise<AttendanceRecord[]> => {
  return request<AttendanceRecord[]>(`/api/members/${memberId}/attendance`, { errorMessage: "Failed to fetch attendance history" })
}
