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

export const getSession = async (id: string): Promise<SessionInstance> => {
  const res = await fetch(`/api/sessions/${id}`, { credentials: "include" })
  if (!res.ok) {
    throw new Error(`Failed to fetch session: ${res.status}`)
  }
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
  if (!res.ok) {
    throw new Error(`Failed to update session: ${res.status}`)
  }
  return res.json() as Promise<SessionInstance>
}

export const cancelSession = async (id: string): Promise<SessionInstance> => {
  const res = await fetch(new Request(`${location.origin}/api/sessions/${id}/cancel`, {
    method: "POST",
    credentials: "include",
  }))
  if (!res.ok) {
    throw new Error(`Failed to cancel session: ${res.status}`)
  }
  return res.json() as Promise<SessionInstance>
}

export const deleteTemplate = async (templateId: string): Promise<void> => {
  const res = await fetch(new Request(`${location.origin}/api/sessions/templates/${templateId}`, {
    method: "DELETE",
    credentials: "include",
  }))
  if (!res.ok) {
    throw new Error(`Failed to delete template: ${res.status}`)
  }
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
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Failed to create session: ${res.status}`)
  }
  return res.json() as Promise<SessionInstance>
}

export type SessionTemplateCreate = {
  title: string
  start_date: string       // "YYYY-MM-DD"
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
  start_time: string // derived envelope value
  duration_minutes: number // derived envelope value
  recurrence_days: number[]
  interval_weeks: number
  location: string | null
  info: string | null
  coach_notes: string | null
  segments: Segment[]
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

export const getSessionsForRange = async (
  from: string,
  to: string,
): Promise<SessionInstance[]> => {
  const params = new URLSearchParams({ from, to })
  const res = await fetch(`/api/sessions?${params.toString()}`, {
    credentials: "include",
  })
  if (!res.ok) {
    throw new Error(`Failed to fetch sessions: ${res.status}`)
  }
  return res.json() as Promise<SessionInstance[]>
}

export const deleteSessionType = async (id: string): Promise<void> => {
  const res = await fetch(`/api/session-types/${id}`, {
    method: "DELETE",
    credentials: "include",
  })
  if (!res.ok) {
    // The backend returns a 409 with a { detail } message when the type is
    // still referenced by a segment — surface that message to the admin.
    let detail: string | null = null
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === "string") detail = body.detail
    } catch {
      // non-JSON body; fall through to a generic message
    }
    throw new Error(detail ?? `Failed to delete session type: ${res.status}`)
  }
}

export const updateSessionTypeColour = async (id: string, colour: string | null): Promise<SessionType> => {
  const res = await fetch(`/api/session-types/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ colour }),
  })
  if (!res.ok) throw new Error(`Failed to update session type colour: ${res.status}`)
  return res.json() as Promise<SessionType>
}
