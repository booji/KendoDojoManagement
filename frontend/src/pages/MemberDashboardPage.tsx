import { useEffect, useState } from "react"
import { getSessions } from "@/api/sessions"
import type { SessionInstance } from "@/api/sessions"
import { checkIn } from "@/api/attendance"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

// ── Date helpers ───────────────────────────────────────────────────────────────

const formatDate = (iso: string): string =>
  new Date(iso).toLocaleDateString("default", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  })

const formatTime = (iso: string): string =>
  new Date(iso).toLocaleTimeString("default", {
    hour: "2-digit",
    minute: "2-digit",
  })

const isToday = (iso: string): boolean => {
  const d = new Date(iso)
  const now = new Date()
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  )
}

// A session is "active" if it's scheduled today and not cancelled
const isActiveToday = (session: SessionInstance): boolean =>
  session.status !== "cancelled" && isToday(session.scheduled_at)

// ── Check-in state ─────────────────────────────────────────────────────────────

type CheckinStatus =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success" }
  | { kind: "error"; message: string }

// ── Sub-components ─────────────────────────────────────────────────────────────

const SessionBadge = ({ iso }: { iso: string }) => (
  <div
    className="flex flex-col items-center justify-center rounded-lg bg-muted px-3 py-2 min-w-[56px] shrink-0"
    aria-hidden="true"
  >
    <span className="text-xs font-medium text-muted-foreground uppercase">
      {new Date(iso).toLocaleDateString("default", { month: "short" })}
    </span>
    <span className="text-xl font-bold tabular-nums leading-tight">
      {new Date(iso).getDate()}
    </span>
  </div>
)

const UpcomingSessionRow = ({ session }: { session: SessionInstance }) => (
  <li className="flex items-center gap-3 py-2">
    <SessionBadge iso={session.scheduled_at} />
    <div className="min-w-0 flex-1">
      <p className="text-sm font-medium truncate">
        {formatDate(session.scheduled_at)}
      </p>
      <p className="text-xs text-muted-foreground">
        {formatTime(session.scheduled_at)} &middot; {session.duration_minutes} min
      </p>
    </div>
  </li>
)

const DashboardSkeletons = () => (
  <div className="space-y-4" aria-busy="true" aria-label="Loading dashboard">
    <Skeleton className="h-32 w-full rounded-xl" />
    <Skeleton className="h-48 w-full rounded-xl" />
  </div>
)

// ── Main page ──────────────────────────────────────────────────────────────────

const MemberDashboardPage = () => {
  const [sessions, setSessions] = useState<SessionInstance[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [checkin, setCheckin] = useState<CheckinStatus>({ kind: "idle" })

  useEffect(() => {
    getSessions()
      .then((data) => {
        // Keep only upcoming (non-cancelled) sessions sorted ascending
        const upcoming = data
          .filter((s) => s.status !== "cancelled" && new Date(s.scheduled_at) >= new Date(Date.now() - 24 * 60 * 60 * 1000))
          .sort((a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime())
        setSessions(upcoming)
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
  const upcomingList = sessions?.slice(0, 5) ?? []

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
    <div className="px-4 py-6 max-w-2xl mx-auto space-y-6">
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
                  <SessionBadge iso={nextSession.scheduled_at} />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">
                      {formatDate(nextSession.scheduled_at)}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {formatTime(nextSession.scheduled_at)} &middot; {nextSession.duration_minutes} min
                      {nextSession.location !== null && ` \u00b7 ${nextSession.location}`}
                    </p>
                  </div>
                </div>
              )}

              {/* Check-in button — always in the card for thumb zone */}
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

          {/* Upcoming sessions list */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold">Upcoming Sessions</CardTitle>
            </CardHeader>
            <CardContent>
              {upcomingList.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No upcoming sessions scheduled.
                </p>
              ) : (
                <ul
                  className="divide-y divide-border"
                  aria-label="Upcoming sessions list"
                >
                  {upcomingList.map((session) => (
                    <UpcomingSessionRow key={session.id} session={session} />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

export default MemberDashboardPage
