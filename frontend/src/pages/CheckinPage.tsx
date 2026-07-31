import { useEffect, useRef, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { checkinViaToken } from "@/api/attendance"
import { Button } from "@/components/ui/button"

type PageState =
  | { kind: "loading" }
  | { kind: "success" }
  | { kind: "expired" }
  | { kind: "invalid" }
  | { kind: "cancelled" }
  | { kind: "error"; message: string }

const CheckinPage = () => {
  const { token } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const [state, setState] = useState<PageState>(() =>
    token ? { kind: "loading" } : { kind: "invalid" }
  )
  const hasFired = useRef(false)

  useEffect(() => {
    if (!token) return
    if (hasFired.current) return
    hasFired.current = true

    checkinViaToken(token)
      .then(() => {
        setState({ kind: "success" })
      })
      .catch((err: unknown) => {
        const status =
          typeof err === "object" && err !== null && "status" in err
            ? (err as { status: number }).status
            : 0

        if (status === 401) {
          navigate("/login", { replace: true })
        } else if (status === 410) {
          setState({ kind: "expired" })
        } else if (status === 404) {
          setState({ kind: "invalid" })
        } else if (status === 409) {
          setState({ kind: "cancelled" })
        } else {
          setState({ kind: "error", message: "Something went wrong. Please try again." })
        }
      })
  }, [token, navigate])

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

      {state.kind === "expired" && (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">Link expired</h1>
            <p className="text-muted-foreground">This check-in link has expired.</p>
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

      {state.kind === "invalid" && (
        <>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold">Invalid link</h1>
            <p className="text-muted-foreground">Invalid check-in link.</p>
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
            <p className="text-muted-foreground">This session has been cancelled.</p>
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

export default CheckinPage
