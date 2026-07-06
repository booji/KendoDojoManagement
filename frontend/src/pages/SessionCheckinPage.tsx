import { useEffect, useRef, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { checkIn } from "@/api/attendance"
import { Button } from "@/components/ui/button"

type PageState =
  | { kind: "loading" }
  | { kind: "success" }
  | { kind: "already-checked-in" }
  | { kind: "cancelled" }
  | { kind: "not-found" }
  | { kind: "too-early"; opensAt: string }
  | { kind: "closed"; closesAt: string }
  | { kind: "error"; message: string }

// Formats an ISO datetime as a short, human-readable local time, e.g.
// "6:00 PM" or, if not today, "Mon, Jul 6, 6:00 PM". Falls back to the raw
// string if it can't be parsed.
const formatBoundaryTime = (iso: string): string => {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  return date.toLocaleString(undefined, {
    weekday: sameDay ? undefined : "short",
    month: sameDay ? undefined : "short",
    day: sameDay ? undefined : "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

// Tokenless check-in page reached from the member iCal feed (issue #191).
// Reuses the visual layout of the token-based CheckinPage, but drives
// POST /sessions/{id}/checkin directly instead of consuming a single-use
// token.
const SessionCheckinPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [state, setState] = useState<PageState>({ kind: "loading" })
  const hasFired = useRef(false)

  useEffect(() => {
    if (!id) {
      setState({ kind: "not-found" })
      return
    }
    if (hasFired.current) return
    hasFired.current = true

    checkIn(id)
      .then(() => {
        setState({ kind: "success" })
      })
      .catch((err: unknown) => {
        const status =
          typeof err === "object" && err !== null && "status" in err
            ? (err as { status: number }).status
            : 0
        const message =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : ""

        const reason =
          typeof err === "object" && err !== null && "reason" in err
            ? String((err as { reason: unknown }).reason)
            : ""
        const boundary =
          typeof err === "object" && err !== null && "boundary" in err
            ? String((err as { boundary: unknown }).boundary)
            : ""

        if (status === 401) {
          navigate("/login", { replace: true })
        } else if (status === 404) {
          setState({ kind: "not-found" })
        } else if (status === 403 && reason === "too_early") {
          setState({ kind: "too-early", opensAt: boundary })
        } else if (status === 403 && reason === "closed") {
          setState({ kind: "closed", closesAt: boundary })
        } else if (status === 409 && message === "Already checked in") {
          setState({ kind: "already-checked-in" })
        } else if (status === 409) {
          setState({ kind: "cancelled" })
        } else {
          setState({ kind: "error", message: "Something went wrong. Please try again." })
        }
      })
  }, [id, navigate])

  // Centered full-screen layout — thumb-friendly, works at 375px
  return (
    <div className="flex min-h-[80vh] flex-col items-center justify-center px-6 text-center gap-6">
      {state.kind === "loading" && (
        <p className="text-lg text-muted-foreground" aria-live="polite">
          Checking you in…
        </p>
      )}

      {state.kind === "success" && (
        <>
          <div className="space-y-2">
            <p className="text-5xl" aria-hidden="true">
              ✓
            </p>
            <h1 className="text-3xl font-bold tracking-tight">You&apos;re checked in!</h1>
            <p className="text-muted-foreground">Your attendance has been recorded.</p>
          </div>
          <Button
            size="lg"
            className="min-h-[56px] w-full max-w-xs text-base"
            onClick={() => navigate("/sessions")}
            aria-label="Back to sessions"
          >
            Back to Sessions
          </Button>
        </>
      )}

      {state.kind === "already-checked-in" && (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">Already checked in</h1>
            <p className="text-muted-foreground">You&apos;ve already been checked in to this session.</p>
          </div>
          <Button
            size="lg"
            variant="outline"
            className="min-h-[56px] w-full max-w-xs"
            onClick={() => navigate("/sessions")}
          >
            Go to Sessions
          </Button>
        </>
      )}

      {state.kind === "cancelled" && (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">Session cancelled</h1>
            <p className="text-muted-foreground">This session is no longer taking place.</p>
          </div>
          <Button
            size="lg"
            variant="outline"
            className="min-h-[56px] w-full max-w-xs"
            onClick={() => navigate("/sessions")}
          >
            Go to Sessions
          </Button>
        </>
      )}

      {state.kind === "not-found" && (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">Session not found</h1>
            <p className="text-muted-foreground">This check-in link is not valid.</p>
          </div>
          <Button
            size="lg"
            variant="outline"
            className="min-h-[56px] w-full max-w-xs"
            onClick={() => navigate("/sessions")}
          >
            Go to Sessions
          </Button>
        </>
      )}

      {state.kind === "too-early" && (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">Check-in not open yet</h1>
            <p className="text-muted-foreground">
              Check-in opens at {formatBoundaryTime(state.opensAt)}. Please come back then.
            </p>
          </div>
          <Button
            size="lg"
            variant="outline"
            className="min-h-[56px] w-full max-w-xs"
            onClick={() => navigate("/sessions")}
          >
            Go to Sessions
          </Button>
        </>
      )}

      {state.kind === "closed" && (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">Check-in closed</h1>
            <p className="text-muted-foreground">
              Check-in closed at {formatBoundaryTime(state.closesAt)}.
            </p>
          </div>
          <Button
            size="lg"
            variant="outline"
            className="min-h-[56px] w-full max-w-xs"
            onClick={() => navigate("/sessions")}
          >
            Go to Sessions
          </Button>
        </>
      )}

      {state.kind === "error" && (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">Error</h1>
            <p className="text-muted-foreground">{state.message}</p>
          </div>
          <Button
            size="lg"
            variant="outline"
            className="min-h-[56px] w-full max-w-xs"
            onClick={() => navigate("/sessions")}
          >
            Go to Sessions
          </Button>
        </>
      )}
    </div>
  )
}

export default SessionCheckinPage
