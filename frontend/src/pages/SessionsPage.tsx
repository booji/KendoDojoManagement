import { useEffect, useState } from "react"
import { getSessions, getSessionTypes } from "@/api/sessions"
import type { SessionInstance, SessionType } from "@/api/sessions"
import { getMe } from "@/api/auth"
import {
  checkIn,
  getCheckinToken,
  getSessionAttendance,
  markAttended,
  removeAttendance,
  addVisitor,
} from "@/api/attendance"
import type { AttendanceRecord } from "@/api/attendance"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ChevronDownIcon, ChevronUpIcon } from "lucide-react"

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

          <SessionAttendancePanel sessionId={session.id} />
        </>
      )}
    </div>
  )
}

// ── Session attendance panel (admin only) ─────────────────────────────────────

type AttendancePanelState =
  | { kind: "closed" }
  | { kind: "loading" }
  | { kind: "loaded"; records: AttendanceRecord[] }
  | { kind: "error"; message: string }

type SessionAttendancePanelProps = {
  sessionId: string
}

const SessionAttendancePanel = ({ sessionId }: SessionAttendancePanelProps) => {
  const [panel, setPanel] = useState<AttendancePanelState>({ kind: "closed" })
  const [memberIdInput, setMemberIdInput] = useState("")
  const [markingError, setMarkingError] = useState<string | null>(null)
  const [marking, setMarking] = useState(false)
  const [visitorInput, setVisitorInput] = useState("")
  const [addingVisitor, setAddingVisitor] = useState(false)
  const [visitorError, setVisitorError] = useState<string | null>(null)

  const open = panel.kind !== "closed"

  const load = async () => {
    setPanel({ kind: "loading" })
    try {
      const records = await getSessionAttendance(sessionId)
      setPanel({ kind: "loaded", records })
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to load attendance"
      setPanel({ kind: "error", message })
    }
  }

  const toggle = () => {
    if (open) {
      setPanel({ kind: "closed" })
    } else {
      void load()
    }
  }

  const handleRemove = async (memberId: string) => {
    try {
      await removeAttendance(sessionId, memberId)
      setPanel((prev) =>
        prev.kind === "loaded"
          ? { kind: "loaded", records: prev.records.filter((r) => r.member_id !== memberId) }
          : prev
      )
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to remove"
      setMarkingError(message)
    }
  }

  const handleMarkAttended = async (e: React.FormEvent) => {
    e.preventDefault()
    const id = memberIdInput.trim()
    if (!id) return
    setMarkingError(null)
    setMarking(true)
    try {
      const record = await markAttended(sessionId, id)
      setPanel((prev) =>
        prev.kind === "loaded"
          ? { kind: "loaded", records: [...prev.records, record] }
          : prev
      )
      setMemberIdInput("")
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to mark attended"
      setMarkingError(message)
    } finally {
      setMarking(false)
    }
  }

  const handleAddVisitor = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = visitorInput.trim()
    if (!name) return
    setVisitorError(null)
    setAddingVisitor(true)
    try {
      const record = await addVisitor(sessionId, name)
      setPanel((prev) =>
        prev.kind === "loaded"
          ? { kind: "loaded", records: [...prev.records, record] }
          : prev
      )
      setVisitorInput("")
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to add visitor"
      setVisitorError(message)
    } finally {
      setAddingVisitor(false)
    }
  }

  return (
    <div className="mt-2 border-t pt-3">
      <button
        type="button"
        className="flex w-full items-center justify-between text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
        onClick={toggle}
        aria-expanded={open}
        aria-controls="attendance-panel"
      >
        <span>Attendance</span>
        {open ? (
          <ChevronUpIcon className="h-4 w-4" aria-hidden="true" />
        ) : (
          <ChevronDownIcon className="h-4 w-4" aria-hidden="true" />
        )}
      </button>

      {open && (
        <div id="attendance-panel" className="mt-3 space-y-4">
          {panel.kind === "loading" && (
            <div className="space-y-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-3/4" />
            </div>
          )}

          {panel.kind === "error" && (
            <p className="text-xs text-destructive" role="alert">{panel.message}</p>
          )}

          {panel.kind === "loaded" && (
            <>
              {panel.records.length === 0 ? (
                <p className="text-xs text-muted-foreground">No attendees yet</p>
              ) : (
                <ul className="space-y-1" aria-label="Attendance list">
                  {panel.records.map((record) => (
                    <li
                      key={record.id}
                      className="flex items-center justify-between gap-2 text-xs"
                    >
                      <span className="truncate font-mono min-w-0">
                        {record.visitor_name !== null
                          ? record.visitor_name
                          : record.member_id !== null
                            ? record.member_id.slice(0, 8) + "…"
                            : "Unknown"}
                      </span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {record.visitor_name !== null && (
                          <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
                            Visitor
                          </span>
                        )}
                        {record.member_id !== null && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs text-destructive hover:text-destructive"
                            onClick={() => void handleRemove(record.member_id!)}
                            aria-label={`Remove attendance for ${record.member_id?.slice(0, 8)}`}
                          >
                            Remove
                          </Button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {/* Mark member attended */}
              <form onSubmit={(e) => void handleMarkAttended(e)} className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Mark member attended
                </p>
                <div className="flex gap-2">
                  <Input
                    placeholder="Member ID"
                    value={memberIdInput}
                    onChange={(e) => setMemberIdInput(e.target.value)}
                    className="min-h-[44px] flex-1 text-sm"
                    aria-label="Member ID to mark attended"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={marking || memberIdInput.trim() === ""}
                    className="min-h-[44px] shrink-0"
                    aria-label="Mark member attended"
                  >
                    {marking ? "…" : "Mark Attended"}
                  </Button>
                </div>
                {markingError !== null && (
                  <p className="text-xs text-destructive" role="alert">{markingError}</p>
                )}
              </form>

              {/* Add visitor */}
              <form onSubmit={(e) => void handleAddVisitor(e)} className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Add visitor
                </p>
                <div className="flex gap-2">
                  <Input
                    placeholder="Visitor name"
                    value={visitorInput}
                    onChange={(e) => setVisitorInput(e.target.value)}
                    className="min-h-[44px] flex-1 text-sm"
                    aria-label="Visitor name"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={addingVisitor || visitorInput.trim() === ""}
                    className="min-h-[44px] shrink-0"
                    aria-label="Add visitor"
                  >
                    {addingVisitor ? "…" : "Add Visitor"}
                  </Button>
                </div>
                {visitorError !== null && (
                  <p className="text-xs text-destructive" role="alert">{visitorError}</p>
                )}
              </form>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Sessions page ─────────────────────────────────────────────────────────────

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
