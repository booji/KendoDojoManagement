import { throwApiError } from "@/api/client"

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
  note: string | null // public, optional
  type_ids: string[]
}

export type SegmentInput = {
  start_time: string // "HH:MM"
  duration_minutes: number
  title?: string | null // public, optional
  note?: string | null // public, optional
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
  checkin_url: string | null
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
  const res = await fetch("/api/sessions", { credentials: "include" })
  if (!res.ok) await throwApiError(res, "Failed to fetch sessions")
  return res.json() as Promise<SessionInstance[]>
}

export const getSessionTypes = async (): Promise<SessionType[]> => {
  const res = await fetch("/api/session-types", { credentials: "include" })
  if (!res.ok) await throwApiError(res, "Failed to fetch session types")
  return res.json() as Promise<SessionType[]>
}

export const getSession = async (id: string): Promise<SessionInstance> => {
  const res = await fetch(`/api/sessions/${id}`, { credentials: "include" })
  if (!res.ok) await throwApiError(res, "Failed to fetch session")
  return res.json() as Promise<SessionInstance>
}

export const updateSession = async (
  id: string,
  payload: Partial<SessionInstanceUpdate>,
): Promise<SessionInstance> => {
  const res = await fetch(new Request(`${location.origin}/api/sessions/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  }))
  if (!res.ok) await throwApiError(res, "Failed to update session")
  return res.json() as Promise<SessionInstance>
}

export const cancelSession = async (id: string): Promise<SessionInstance> => {
  const res = await fetch(new Request(`${location.origin}/api/sessions/${id}/cancel`, {
    method: "POST",
    credentials: "include",
  }))
  if (!res.ok) await throwApiError(res, "Failed to cancel session")
  return res.json() as Promise<SessionInstance>
}

export const deleteTemplate = async (templateId: string): Promise<void> => {
  const res = await fetch(new Request(`${location.origin}/api/sessions/templates/${templateId}`, {
    method: "DELETE",
    credentials: "include",
  }))
  if (!res.ok) await throwApiError(res, "Failed to delete template")
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
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  })
  if (!res.ok) await throwApiError(res, "Failed to create session")
  return res.json() as Promise<SessionInstance>
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
  const res = await fetch("/api/sessions/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  })
  if (!res.ok) await throwApiError(res, "Failed to create session template")
  return res.json() as Promise<SessionTemplate>
}

export const getSessionTemplate = async (templateId: string): Promise<SessionTemplate> => {
  const res = await fetch(`/api/sessions/templates/${templateId}`, {
    credentials: "include",
  })
  if (!res.ok) await throwApiError(res, "Failed to fetch session template")
  return res.json() as Promise<SessionTemplate>
}

export const extendSessionTemplate = async (
  templateId: string,
  endDate: string,
): Promise<SessionTemplate> => {
  const res = await fetch(
    new Request(`${location.origin}/api/sessions/templates/${templateId}/extend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ end_date: endDate }),
    }),
  )
  if (!res.ok) await throwApiError(res, "Failed to extend session template")
  return res.json() as Promise<SessionTemplate>
}

export const createSessionType = async (name: string): Promise<SessionType> => {
  const res = await fetch("/api/session-types", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ name }),
  })
  if (!res.ok) await throwApiError(res, "Failed to create session type")
  return res.json() as Promise<SessionType>
}

export const getSessionsForRange = async (
  from: string,
  to: string,
): Promise<SessionInstance[]> => {
  const params = new URLSearchParams({ from, to })
  const res = await fetch(`/api/sessions?${params.toString()}`, {
    credentials: "include",
  })
  if (!res.ok) await throwApiError(res, "Failed to fetch sessions")
  return res.json() as Promise<SessionInstance[]>
}

export const deleteSessionType = async (id: string): Promise<void> => {
  const res = await fetch(`/api/session-types/${id}`, {
    method: "DELETE",
    credentials: "include",
  })
  // A 409 carries a { detail } explaining that a segment still references the
  // type; throwApiError surfaces that to the admin.
  if (!res.ok) await throwApiError(res, "Failed to delete session type")
}

export const updateSessionTypeColour = async (id: string, colour: string | null): Promise<SessionType> => {
  const res = await fetch(`/api/session-types/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ colour }),
  })
  if (!res.ok) await throwApiError(res, "Failed to update session type colour")
  return res.json() as Promise<SessionType>
}
