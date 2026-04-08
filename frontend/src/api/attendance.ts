export type AttendanceRecord = {
  id: string
  session_id: string
  member_id: string
  checked_in_at: string
  recorded_by: string
}

export type CheckinToken = {
  token: string
  session_id: string
  expires_at: string
}

export const checkIn = async (sessionId: string): Promise<AttendanceRecord> => {
  const res = await fetch(`/api/sessions/${sessionId}/checkin`, {
    method: "POST",
    credentials: "include",
  })
  if (!res.ok) {
    const status = res.status
    if (status === 404) throw { status, message: "Session not found" }
    if (status === 409) throw { status, message: "Session is cancelled" }
    throw { status, message: "Failed to check in" }
  }
  return res.json() as Promise<AttendanceRecord>
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
