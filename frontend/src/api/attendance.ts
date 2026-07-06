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
  const res = await fetch(new Request(`${location.origin}/api/sessions/${sessionId}/checkin`, {
    method: "POST",
    credentials: "include",
  }))
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
  const res = await fetch(`/api/sessions/${sessionId}/checkin-token`, {
    credentials: "include",
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to get check-in token" }
  }
  return res.json() as Promise<CheckinToken>
}

export const checkinViaToken = async (token: string): Promise<AttendanceRecord> => {
  const res = await fetch(`/api/checkin/${token}`, {
    method: "POST",
    credentials: "include",
  })
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
  const res = await fetch(`/api/sessions/${sessionId}/attendance`, {
    credentials: "include",
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch attendance" }
  }
  return res.json() as Promise<AttendanceRecord[]>
}

export const markAttended = async (sessionId: string, memberId: string): Promise<AttendanceRecord> => {
  const res = await fetch(`/api/sessions/${sessionId}/attendance`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_id: memberId }),
  })
  if (!res.ok) {
    const status = res.status
    if (status === 404) throw { status, message: "Session or member not found" }
    if (status === 409) throw { status, message: "Member already marked attended" }
    throw { status, message: "Failed to mark member attended" }
  }
  return res.json() as Promise<AttendanceRecord>
}

export const removeAttendance = async (sessionId: string, memberId: string): Promise<void> => {
  const res = await fetch(`/api/sessions/${sessionId}/attendance/${memberId}`, {
    method: "DELETE",
    credentials: "include",
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to remove attendance" }
  }
}

export const addVisitor = async (sessionId: string, visitorName: string): Promise<AttendanceRecord> => {
  const res = await fetch(`/api/sessions/${sessionId}/visitors`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ visitor_name: visitorName }),
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to add visitor" }
  }
  return res.json() as Promise<AttendanceRecord>
}

export const getMemberAttendanceHistory = async (memberId: string): Promise<AttendanceRecord[]> => {
  const res = await fetch(`/api/members/${memberId}/attendance`, {
    credentials: "include",
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch attendance history" }
  }
  return res.json() as Promise<AttendanceRecord[]>
}
