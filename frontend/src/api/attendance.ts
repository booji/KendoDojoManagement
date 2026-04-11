export type AttendanceRecord = {
  id: string
  session_id: string
  member_id: string | null
  visitor_name: string | null
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
