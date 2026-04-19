export type SessionType = {
  id: string
  name: string
}

export type SessionInstance = {
  id: string
  session_type_id: string
  scheduled_at: string
  duration_minutes: number
  location: string | null
  template_id: string | null
  status: "scheduled" | "cancelled"
  info: string | null
  coach_notes: string | null
}

export const getSessions = async (): Promise<SessionInstance[]> => {
  const res = await fetch("/api/sessions", { credentials: "include" })
  if (!res.ok) {
    throw new Error(`Failed to fetch sessions: ${res.status}`)
  }
  return res.json() as Promise<SessionInstance[]>
}

export const getSessionTypes = async (): Promise<SessionType[]> => {
  const res = await fetch("/api/session-types", { credentials: "include" })
  if (!res.ok) {
    throw new Error(`Failed to fetch session types: ${res.status}`)
  }
  return res.json() as Promise<SessionType[]>
}

export type SessionInstanceCreate = {
  session_type_id: string
  date: string // "YYYY-MM-DD"
  start_time: string // "HH:MM"
  duration_minutes: number
  location: string | null
  info: string | null
  coach_notes: string | null
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
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Failed to create session: ${res.status}`)
  }
  return res.json() as Promise<SessionInstance>
}

export type SessionTemplateCreate = {
  session_type_id: string
  title: string
  start_date: string       // "YYYY-MM-DD"
  start_time: string       // "HH:MM"
  duration_minutes: number
  recurrence_days: number[] // Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
  interval_weeks: 1 | 2
  location: string | null
  info: string | null
  coach_notes: string | null
}

export type SessionTemplate = {
  id: string
  session_type_id: string
  title: string
  start_date: string
  start_time: string
  duration_minutes: number
  recurrence_days: number[]
  interval_weeks: number
  location: string | null
  info: string | null
  coach_notes: string | null
}

export const createSessionTemplate = async (
  payload: SessionTemplateCreate,
): Promise<SessionTemplate> => {
  const res = await fetch("/api/sessions/templates", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Failed to create session template: ${res.status}`)
  }
  return res.json() as Promise<SessionTemplate>
}

export const createSessionType = async (name: string): Promise<SessionType> => {
  const res = await fetch("/api/session-types", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ name }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Failed to create session type: ${res.status}`)
  }
  return res.json() as Promise<SessionType>
}
