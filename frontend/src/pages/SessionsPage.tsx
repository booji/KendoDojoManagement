import { useEffect, useState } from "react"
import { getSessions, getSessionTypes } from "@/api/sessions"
import type { SessionInstance, SessionType } from "@/api/sessions"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

// Returns the Monday of the week containing the given date (local time)
const startOfWeek = (date: Date): Date => {
  const d = new Date(date)
  const day = d.getDay() // 0=Sun, 1=Mon, …
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

const weekLabel = (weekStart: Date): string => {
  const day = weekStart.getDate()
  const month = weekStart.toLocaleString("default", { month: "short" })
  return `Week of ${day} ${month}`
}

// Group sessions by the Monday of their week, preserving order
const groupByWeek = (
  sessions: SessionInstance[]
): { label: string; sessions: SessionInstance[] }[] => {
  const map = new Map<string, { label: string; sessions: SessionInstance[] }>()
  for (const s of sessions) {
    const date = new Date(s.scheduled_at)
    const monday = startOfWeek(date)
    const key = monday.toISOString()
    if (!map.has(key)) {
      map.set(key, { label: weekLabel(monday), sessions: [] })
    }
    map.get(key)!.sessions.push(s)
  }
  return Array.from(map.values())
}

const formatTime = (iso: string): string => {
  const date = new Date(iso)
  return date.toLocaleTimeString("default", { hour: "2-digit", minute: "2-digit" })
}

const formatDate = (iso: string): string => {
  const date = new Date(iso)
  return date.toLocaleDateString("default", { weekday: "short", day: "numeric", month: "short" })
}

const SessionsPage = () => {
  const [sessions, setSessions] = useState<SessionInstance[] | null>(null)
  const [typeMap, setTypeMap] = useState<Map<string, string>>(new Map())
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getSessions(), getSessionTypes()])
      .then(([fetchedSessions, fetchedTypes]) => {
        setSessions(fetchedSessions)
        setTypeMap(
          new Map(fetchedTypes.map((t: SessionType) => [t.id, t.name]))
        )
      })
      .catch(() => {
        setError("Failed to load sessions. Please try again.")
      })
  }, [])

  if (error !== null) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (sessions === null) {
    return (
      <div className="px-4 py-6 space-y-4 max-w-2xl mx-auto">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-20 w-full rounded-xl" />
      </div>
    )
  }

  if (sessions.length === 0) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <p className="text-sm text-muted-foreground">No upcoming sessions</p>
      </div>
    )
  }

  const groups = groupByWeek(sessions)

  return (
    <div className="px-4 py-6 space-y-8 max-w-2xl mx-auto">
      <h1 className="text-xl font-semibold">Sessions</h1>
      {groups.map((group) => (
        <section key={group.label}>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {group.label}
          </h2>
          <ul className="space-y-3">
            {group.sessions.map((session) => {
              const cancelled = session.status === "cancelled"
              return (
                <li key={session.id}>
                  <Card
                    className={
                      cancelled ? "opacity-60" : undefined
                    }
                  >
                    <CardContent className="py-3">
                      <div
                        className={
                          cancelled ? "line-through text-muted-foreground" : undefined
                        }
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="font-medium truncate">
                              {typeMap.get(session.session_type_id) ?? "Unknown"}
                            </p>
                            <p className="text-sm text-muted-foreground mt-0.5">
                              {formatDate(session.scheduled_at)}&nbsp;&middot;&nbsp;
                              {formatTime(session.scheduled_at)}&nbsp;&middot;&nbsp;
                              {session.duration_minutes} min
                            </p>
                            {session.location !== null && (
                              <p className="text-sm text-muted-foreground mt-0.5">
                                {session.location}
                              </p>
                            )}
                          </div>
                          {cancelled && (
                            <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                              Cancelled
                            </span>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}

export default SessionsPage
