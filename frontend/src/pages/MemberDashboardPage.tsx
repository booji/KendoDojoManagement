import { useEffect, useState } from "react"
import { getSessions, getSessionTypes } from "@/api/sessions"
import type { SessionInstance, SessionType } from "@/api/sessions"
import { checkIn } from "@/api/attendance"
import { distinctSessionTypes } from "@/lib/sessionTypes"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { formatSessionDate } from "@/lib/date"

const formatTime = (startTime: string): string => startTime

const isToday = (date: string): boolean => {
  const d = new Date(`${date}T00:00:00`)
  const now = new Date()
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  )
}

// A session is "active" if it's scheduled today and not cancelled
const isActiveToday = (session: SessionInstance): boolean =>
  !session.cancelled && isToday(session.date)

// ── Calendar helpers ──────────────────────────────────────────────────────────

const DAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

// Returns the ISO weekday offset for the first day of the month (0 = Mon, 6 = Sun)
const firstDayOffset = (year: number, month: number): number => {
  const dow = new Date(year, month, 1).getDay() // 0=Sun
  return dow === 0 ? 6 : dow - 1
}

const daysInMonth = (year: number, month: number): number =>
  new Date(year, month + 1, 0).getDate()

// ── Check-in state ─────────────────────────────────────────────────────────────

type CheckinStatus =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success" }
  | { kind: "error"; message: string }

// ── Sub-components ─────────────────────────────────────────────────────────────

const SessionBadge = ({ date }: { date: string }) => {
  const d = new Date(`${date}T00:00:00`)
  return (
    <div
      className="flex flex-col items-center justify-center rounded-lg bg-muted px-3 py-2 min-w-[56px] shrink-0"
      aria-hidden="true"
    >
      <span className="text-xs font-medium text-muted-foreground uppercase">
        {d.toLocaleDateString("default", { month: "short" })}
      </span>
      <span className="text-xl font-bold tabular-nums leading-tight">
        {d.getDate()}
      </span>
    </div>
  )
}

const DashboardSkeletons = () => (
  <div className="space-y-4" aria-busy="true" aria-label="Loading dashboard">
    <Skeleton className="h-36 w-full rounded-xl" />
    <Skeleton className="h-64 w-full rounded-xl" />
  </div>
)

// ── Calendar component ─────────────────────────────────────────────────────────

type MonthCalendarProps = {
  sessions: SessionInstance[]
  year: number
  month: number
}

const MonthCalendar = ({ sessions, year, month }: MonthCalendarProps) => {
  const today = new Date()
  const totalDays = daysInMonth(year, month)
  const offset = firstDayOffset(year, month)

  // Build a set of day numbers that have sessions in this month
  const sessionDaySet = new Set<number>()
  for (const s of sessions) {
    const d = new Date(`${s.date}T00:00:00`)
    if (d.getFullYear() === year && d.getMonth() === month) {
      sessionDaySet.add(d.getDate())
    }
  }

  // Build cells: leading blanks then day numbers, padded to a full grid
  const cells: Array<number | null> = Array(offset).fill(null)
  for (let d = 1; d <= totalDays; d++) cells.push(d)
  while (cells.length % 7 !== 0) cells.push(null)

  const monthLabel = new Date(year, month, 1).toLocaleDateString("default", {
    month: "long",
    year: "numeric",
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-semibold">{monthLabel}</CardTitle>
      </CardHeader>
      <CardContent>
        <div
          className="grid grid-cols-7 gap-y-1"
          role="grid"
          aria-label={`Calendar for ${monthLabel}`}
        >
          {/* Day-of-week headers */}
          {DAY_HEADERS.map((d) => (
            <div
              key={d}
              role="columnheader"
              className="text-center text-xs font-medium text-muted-foreground py-1"
              aria-label={d}
            >
              {d}
            </div>
          ))}

          {/* Day cells */}
          {cells.map((day, i) => {
            if (day === null) {
              return <div key={`blank-${i}`} role="gridcell" aria-hidden="true" />
            }
            const isCurrentDay =
              today.getFullYear() === year &&
              today.getMonth() === month &&
              today.getDate() === day
            const hasSession = sessionDaySet.has(day)

            return (
              <div
                key={day}
                role="gridcell"
                aria-label={`${day}${hasSession ? ", session" : ""}${isCurrentDay ? ", today" : ""}`}
                className="flex items-center justify-center py-0.5"
              >
                <span
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full text-sm tabular-nums",
                    isCurrentDay &&
                      "bg-primary text-primary-foreground font-bold",
                    !isCurrentDay &&
                      hasSession &&
                      "bg-accent text-accent-foreground font-medium ring-1 ring-accent-foreground/20",
                    !isCurrentDay && !hasSession && "text-muted-foreground",
                  )}
                >
                  {day}
                </span>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

const MemberDashboardPage = () => {
  const [sessions, setSessions] = useState<SessionInstance[] | null>(null)
  const [typeMap, setTypeMap] = useState<Map<string, SessionType>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [checkin, setCheckin] = useState<CheckinStatus>({ kind: "idle" })

  useEffect(() => {
    Promise.all([getSessions(), getSessionTypes()])
      .then(([data, types]: [SessionInstance[], SessionType[]]) => {
        const upcoming = data
          .filter(
            (s) =>
              !s.cancelled &&
              new Date(`${s.date}T${s.start_time}`) >= new Date(Date.now() - 24 * 60 * 60 * 1000),
          )
          .sort(
            (a, b) =>
              new Date(`${a.date}T${a.start_time}`).getTime() -
              new Date(`${b.date}T${b.start_time}`).getTime(),
          )
        setSessions(upcoming)
        setTypeMap(new Map(types.map((t) => [t.id, t])))
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load sessions")
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const activeSession = sessions?.find(isActiveToday) ?? null
  const nextSession = sessions?.[0] ?? null

  const now = new Date()
  const calYear = now.getFullYear()
  const calMonth = now.getMonth()

  const handleCheckIn = async () => {
    if (activeSession === null) return
    setCheckin({ kind: "loading" })
    try {
      await checkIn(activeSession.id)
      setCheckin({ kind: "success" })
    } catch (err: unknown) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to check in"
      setCheckin({ kind: "error", message })
    }
  }

  return (
    <div className="px-4 py-6 space-y-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      {loading && <DashboardSkeletons />}

      {!loading && error !== null && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {!loading && sessions !== null && (
        <>
          {/* Next session card */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold">Next Session</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {nextSession === null ? (
                <p className="text-sm text-muted-foreground">
                  No upcoming sessions scheduled.
                </p>
              ) : (
                <div className="flex items-center gap-3">
                  <SessionBadge date={nextSession.date} />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium truncate flex items-center gap-1.5">
                      {nextSession.title}
                      {distinctSessionTypes(nextSession.segments, typeMap).map((t) => (
                        <span
                          key={t.id}
                          className="h-2 w-2 rounded-full shrink-0"
                          style={{ backgroundColor: t.colour ?? "var(--muted-foreground)" }}
                          aria-hidden="true"
                        />
                      ))}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {formatSessionDate(nextSession.date)}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {formatTime(nextSession.start_time)}&nbsp;&middot;&nbsp;
                      {nextSession.duration_minutes}&nbsp;min
                      {nextSession.location !== null &&
                        `\u00a0\u00b7\u00a0${nextSession.location}`}
                    </p>
                  </div>
                </div>
              )}

              {/* Check In — in bottom half of card for thumb-zone access on mobile */}
              {checkin.kind === "success" ? (
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
                  onClick={() => void handleCheckIn()}
                  disabled={activeSession === null || checkin.kind === "loading"}
                  aria-label={
                    activeSession !== null
                      ? "Check in to today's session"
                      : "No active session today"
                  }
                >
                  {checkin.kind === "loading"
                    ? "Checking in…"
                    : activeSession !== null
                      ? "Check In"
                      : "No Active Session"}
                </Button>
              )}

              {checkin.kind === "error" && (
                <p className="text-xs text-destructive" role="alert">
                  {checkin.message}
                </p>
              )}
            </CardContent>
          </Card>

          {/* Monthly calendar */}
          <MonthCalendar
            sessions={sessions}
            year={calYear}
            month={calMonth}
          />
        </>
      )}
    </div>
  )
}

export default MemberDashboardPage
