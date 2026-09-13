import { apiFetch, request, throwApiError } from "@/api/client"

export type SessionType = {
  id: string
  name: string
  colour: string | null
}

export type Segment = {
  id?: string
  start_time: string // "HH:MM"
  duration_minutes: number
  title: string | null // public, optional
  type_ids: string[]
}

export type SegmentInput = {
  start_time: string // "HH:MM"
  duration_minutes: number
  title?: string | null // public, optional
  type_ids: string[]
}

export type SessionInstance = {
  id: string
  title: string
  date: string
  start_time: string // derived envelope value
  duration_minutes: number // derived envelope value
  location: string | null
  template_id: string | null
  cancelled: boolean
  notes: string | null
  info: string | null
  coach_notes: string | null
  // The session's one check-in link: tokenless, stable, built by the backend.
  checkin_link: string
  checkin_window_before_minutes: number | null
  checkin_window_after_minutes: number | null
  attendance_count: number
  is_checked_in: boolean
  segments: Segment[]
}

export type SessionInstanceUpdate = {
  title: string
  date: string
  location: string | null
  notes: string | null
  info: string | null
  coach_notes: string | null
  segments: SegmentInput[]
  checkin_window_before_minutes: number | null
  checkin_window_after_minutes: number | null
}

export const getSessions = async (): Promise<SessionInstance[]> => {
  return request<SessionInstance[]>("/api/sessions", { errorMessage: "Failed to fetch sessions" })
}

export const getSessionTypes = async (): Promise<SessionType[]> => {
  return request<SessionType[]>("/api/session-types", { errorMessage: "Failed to fetch session types" })
}

export const getSession = async (id: string): Promise<SessionInstance> => {
  return request<SessionInstance>(`/api/sessions/${id}`, { errorMessage: "Failed to fetch session" })
}

export const updateSession = async (
  id: string,
  payload: Partial<SessionInstanceUpdate>,
): Promise<SessionInstance> => {
  return request<SessionInstance>(`/api/sessions/${id}`, { method: "PUT", body: payload, errorMessage: "Failed to update session" })
}

export const cancelSession = async (id: string): Promise<SessionInstance> => {
  return request<SessionInstance>(`/api/sessions/${id}/cancel`, { method: "POST", errorMessage: "Failed to cancel session" })
}

export const deleteTemplate = async (templateId: string): Promise<void> => {
  return request<void>(`/api/sessions/templates/${templateId}`, { method: "DELETE", errorMessage: "Failed to delete template" })
}

export type SessionInstanceCreate = {
  title: string
  date: string // "YYYY-MM-DD"
  location: string | null
  info: string | null
  coach_notes: string | null
  segments: SegmentInput[]
}

export const createSession = async (
  payload: SessionInstanceCreate,
): Promise<SessionInstance> => {
  return request<SessionInstance>("/api/sessions", { method: "POST", body: payload, errorMessage: "Failed to create session" })
}

export type SessionTemplateCreate = {
  title: string
  start_date: string       // "YYYY-MM-DD"
  end_date: string          // "YYYY-MM-DD" — required; start_date < end_date <= start_date+6mo
  recurrence_days: number[] // Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
  interval_weeks: 1 | 2
  location: string | null
  info: string | null
  coach_notes: string | null
  segments: SegmentInput[]
}

export type SessionTemplate = {
  id: string
  title: string
  start_date: string
  end_date: string
  start_time: string // derived envelope value
  duration_minutes: number // derived envelope value
  recurrence_days: number[]
  interval_weeks: number
  location: string | null
  info: string | null
  coach_notes: string | null
  segments: Segment[]
}

// FastAPI returns validation failures (422) as `{ detail: [{ msg, loc, ... }] }`
// rather than a plain string. Flatten either shape into one readable message
// so callers never have to show a raw JSON blob to the user.
export const createSessionTemplate = async (
  payload: SessionTemplateCreate,
): Promise<SessionTemplate> => {
  return request<SessionTemplate>("/api/sessions/templates", { method: "POST", body: payload, errorMessage: "Failed to create session template" })
}

export const getSessionTemplate = async (templateId: string): Promise<SessionTemplate> => {
  return request<SessionTemplate>(`/api/sessions/templates/${templateId}`, { errorMessage: "Failed to fetch session template" })
}

export const extendSessionTemplate = async (
  templateId: string,
  endDate: string,
): Promise<SessionTemplate> => {
  return request<SessionTemplate>(`/api/sessions/templates/${templateId}/extend`, {
    method: "POST",
    body: { end_date: endDate },
    errorMessage: "Failed to extend session template",
  })
}

export const createSessionType = async (name: string): Promise<SessionType> => {
  return request<SessionType>("/api/session-types", { method: "POST", body: { name }, errorMessage: "Failed to create session type" })
}

export const getSessionsForRange = async (
  from: string,
  to: string,
): Promise<SessionInstance[]> => {
  const params = new URLSearchParams({ from, to })
  return request<SessionInstance[]>(`/api/sessions?${params.toString()}`, { errorMessage: "Failed to fetch sessions" })
}

export const deleteSessionType = async (id: string): Promise<void> => {
  const res = await apiFetch(`/api/session-types/${id}`, { method: "DELETE" })
  // A 409 carries a { detail } explaining that a segment still references the
  // type; throwApiError surfaces that to the admin.
  if (!res.ok) await throwApiError(res, "Failed to delete session type")
}

export const updateSessionTypeColour = async (id: string, colour: string | null): Promise<SessionType> => {
  return request<SessionType>(`/api/session-types/${id}`, { method: "PUT", body: { colour }, errorMessage: "Failed to update session type colour" })
}
