import { useEffect, useState } from "react"
import { getSessions, getSessionTypes } from "@/api/sessions"
import type { SessionInstance, SessionType } from "@/api/sessions"
import { getMe } from "@/api/auth"
import { checkIn, getCheckinToken } from "@/api/attendance"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

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

// Per-session check-in UI state
type CheckinState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success" }
  | { kind: "error"; message: string }

type ShareState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "url"; url: string }
  | { kind: "error"; message: string }

type SessionCardActionsProps = {
  session: SessionInstance
  isAdmin: boolean
}

const SessionCardActions = ({ session, isAdmin }: SessionCardActionsProps) => {
  const [checkinState, setCheckinState] = useState<CheckinState>({ kind: "idle" })
  const [shareState, setShareState] = useState<ShareState>({ kind: "idle" })

  const handleCheckIn = async () => {
    setCheckinState({ kind: "loading" })
    try {
      await checkIn(session.id)
      setCheckinState({ kind: "success" })
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to check in"
      setCheckinState({ kind: "error", message })
    }
  }

  const handleShare = async () => {
    setShareState({ kind: "loading" })
    try {
      const tokenData = await getCheckinToken(session.id)
      const url = `${window.location.origin}/checkin/${tokenData.token}`
      setShareState({ kind: "url", url })
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to get check-in link"
      setShareState({ kind: "error", message })
    }
  }

  return (
    <div className="mt-3 space-y-2">
      {/* Check-in button — full width, thumb-friendly */}
      {checkinState.kind === "success" ? (
        <div
          className="flex items-center justify-center w-full min-h-[48px] rounded-md bg-green-100 text-green-800 font-medium text-sm dark:bg-green-900/30 dark:text-green-300"
          role="status"
          aria-live="polite"
        >
          Checked in!
        </div>
      ) : (
        <Button
          size="lg"
          className="w-full min-h-[48px]"
          onClick={handleCheckIn}
          disabled={checkinState.kind === "loading"}
          aria-label="Check in to this session"
        >
          {checkinState.kind === "loading" ? "Checking in…" : "Check In"}
        </Button>
      )}
      {checkinState.kind === "error" && (
        <p className="text-xs text-destructive" role="alert">
          {checkinState.message}
        </p>
      )}

      {/* Admin-only: share check-in link */}
      {isAdmin && (
        <>
          {shareState.kind === "url" ? (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Share this check-in link:</p>
              <Input
                readOnly
                value={shareState.url}
                aria-label="Check-in link"
                onFocus={(e) => e.target.select()}
                className="text-xs"
              />
            </div>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={handleShare}
              disabled={shareState.kind === "loading"}
              aria-label="Share check-in link for this session"
            >
              {shareState.kind === "loading" ? "Getting link…" : "Share check-in link"}
            </Button>
          )}
          {shareState.kind === "error" && (
            <p className="text-xs text-destructive" role="alert">
              {shareState.message}
            </p>
          )}
        </>
      )}
    </div>
  )
}

const SessionsPage = () => {
  const [sessions, setSessions] = useState<SessionInstance[] | null>(null)
  const [typeMap, setTypeMap] = useState<Map<string, string>>(new Map())
  const [role, setRole] = useState<"admin" | "member" | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getSessions(), getSessionTypes(), getMe()])
      .then(([fetchedSessions, fetchedTypes, me]) => {
        setSessions(fetchedSessions)
        setTypeMap(
          new Map(fetchedTypes.map((t: SessionType) => [t.id, t.name]))
        )
        setRole(me.role)
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
  const isAdmin = role === "admin"

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
                      {!cancelled && (
                        <SessionCardActions session={session} isAdmin={isAdmin} />
                      )}
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
