export type SessionSummary = {
  session_id: string
  scheduled_at: string
  headcount: number
}

export type MemberAttendanceRate = {
  member_id: string
  display_name: string
  sessions_attended: number
  attendance_rate: number
}

export type AttendanceReport = {
  sessions: SessionSummary[]
  member_rates: MemberAttendanceRate[]
}

export type MemberReport = {
  member_id: string
  display_name: string
  join_date: string
  current_grade: string | null
}

export const fetchAttendanceReport = async (
  dateFrom: string,
  dateTo: string,
): Promise<AttendanceReport> => {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
  const res = await fetch(`/api/reports/attendance?${params.toString()}`, {
    credentials: "include",
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch attendance report" }
  }
  return res.json() as Promise<AttendanceReport>
}

export const fetchMembersReport = async (): Promise<MemberReport[]> => {
  const res = await fetch("/api/reports/members", {
    credentials: "include",
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to fetch members report" }
  }
  return res.json() as Promise<MemberReport[]>
}

export const downloadAttendanceCsv = async (
  dateFrom: string,
  dateTo: string,
): Promise<void> => {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
  const res = await fetch(`/api/reports/attendance/csv?${params.toString()}`, {
    credentials: "include",
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to download attendance CSV" }
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `attendance_${dateFrom}_${dateTo}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export const downloadMembersCsv = async (): Promise<void> => {
  const res = await fetch("/api/reports/members/csv", {
    credentials: "include",
  })
  if (!res.ok) {
    throw { status: res.status, message: "Failed to download members CSV" }
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = "members.csv"
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
