import { apiFetch, request, throwApiError } from "@/api/client"
import type { MembershipStatus } from "@/api/members"

export type SessionSummary = {
  session_id: string
  date: string
  headcount: number
}

export type MemberAttendanceRate = {
  member_id: string
  display_name: string
  sessions_attended: number
  total_sessions: number
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
  return request<AttendanceReport>(`/api/reports/attendance?${params.toString()}`, { errorMessage: "Failed to fetch attendance report" })
}

export const fetchMembersReport = async (): Promise<MemberReport[]> => {
  return request<MemberReport[]>("/api/reports/members", { errorMessage: "Failed to fetch members report" })
}

export const downloadAttendanceCsv = async (
  dateFrom: string,
  dateTo: string,
): Promise<void> => {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
  // A CSV download wants the bytes, not a parsed body, so this goes through
  // apiFetch rather than request.
  const res = await apiFetch(`/api/reports/attendance/csv?${params.toString()}`)
  if (!res.ok) await throwApiError(res, "Failed to download attendance CSV")
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
  const res = await apiFetch("/api/reports/members/csv")
  if (!res.ok) await throwApiError(res, "Failed to download members CSV")
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

// ── Charts tab (#558) ─────────────────────────────────────────────────────────

export type GradeCount = {
  grade: string
  display_name: string
  count: number
}

/** Members holding each Grade today, Mukyū up to the highest held, zeros kept. */
export const fetchGradeDistribution = async (
  statuses: MembershipStatus[],
): Promise<GradeCount[]> => {
  const params = new URLSearchParams(statuses.map((s) => ["status", s]))
  return request<GradeCount[]>(`/api/reports/grades?${params.toString()}`, {
    errorMessage: "Failed to fetch grade distribution",
  })
}

export type SessionHeadcount = {
  session_id: string
  date: string
  members: number
  visitors: number
}

/** Members and Visitors at each held Session in the range, oldest first. */
export const fetchHeadcount = async (
  dateFrom: string,
  dateTo: string,
): Promise<SessionHeadcount[]> => {
  const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
  return request<SessionHeadcount[]>(`/api/reports/headcount?${params.toString()}`, {
    errorMessage: "Failed to fetch headcount",
  })
}

export type AttendanceStreak = {
  member_id: string
  display_name: string
  weeks: number
  /** Still unbroken as of today. */
  running: boolean
}

/** The 10 longest Attendance Streaks from 1 January to today, longest first. */
export const fetchAttendanceStreaks = async (
  statuses: MembershipStatus[],
): Promise<AttendanceStreak[]> => {
  const params = new URLSearchParams(statuses.map((s) => ["status", s]))
  return request<AttendanceStreak[]>(`/api/reports/streaks?${params.toString()}`, {
    errorMessage: "Failed to fetch Attendance Streaks",
  })
}

export type AbsentMember = {
  member_id: string
  display_name: string
  email: string | null
  last_attended: string | null
  days_absent: number
}

/** Members with no Attendance in the last 14 days, as of today, longest first. */
export const fetchAbsentMembers = async (
  statuses: MembershipStatus[],
): Promise<AbsentMember[]> => {
  const params = new URLSearchParams(statuses.map((s) => ["status", s]))
  return request<AbsentMember[]>(`/api/reports/absent-members?${params.toString()}`, {
    errorMessage: "Failed to fetch Absent Members",
  })
}
