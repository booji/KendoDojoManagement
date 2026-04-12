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
  notes?: string | null
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
