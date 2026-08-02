import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { performInviteRedemption } from "@/api/invites"

// Deliberately coarse-grained: the server makes unknown / expired / revoked /
// already-redeemed tokens indistinguishable from each other (same status
// code, same body, constant-time floor) so a bad actor probing invite links
// can't learn anything about their state. This page must not reintroduce
// that oracle by showing a more specific reason here — every failure path,
// including a cancelled WebAuthn ceremony, renders the same generic copy.
const GENERIC_FAILURE_MESSAGE = "This invite link is invalid or has expired."

type PageState =
  | { status: "idle" }
  | { status: "registering" }
  | { status: "success" }
  | { status: "invalid" }

const InviteLandingPage = () => {
  const navigate = useNavigate()
  const { token } = useParams<{ token: string }>()
  const [pageState, setPageState] = useState<PageState>({ status: "idle" })

  const handleRegister = async () => {
    if (!token) {
      setPageState({ status: "invalid" })
      return
    }

    setPageState({ status: "registering" })

    try {
      await performInviteRedemption(token)
      setPageState({ status: "success" })
    } catch {
      // Every failure — unknown/expired/revoked/already-redeemed token, a
      // cancelled ceremony, a network error — renders the same fixed generic
      // copy above. The underlying error is intentionally not inspected.
      setPageState({ status: "invalid" })
    }
  }

  const handleContinue = () => {
    navigate("/login")
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Complete your registration</CardTitle>
          <CardDescription>
            You&apos;ve been invited to register a passkey for secure, passwordless
            access.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {pageState.status === "success" && (
            <>
              <p className="text-sm text-green-700 dark:text-green-400" role="status">
                Passkey registered successfully.
              </p>
              <Button size="lg" className="w-full" onClick={handleContinue}>
                Go to login
              </Button>
            </>
          )}

          {pageState.status === "invalid" && (
            <p
              data-testid="invite-invalid"
              className="text-sm text-destructive"
              role="alert"
            >
              {GENERIC_FAILURE_MESSAGE}
            </p>
          )}

          {(pageState.status === "idle" || pageState.status === "registering") && (
            <>
              {pageState.status === "registering" && (
                <p
                  data-testid="invite-register-in-progress"
                  className="text-sm text-muted-foreground"
                  role="status"
                  aria-live="polite"
                >
                  Registering…
                </p>
              )}
              <Button
                size="lg"
                className="w-full"
                data-testid="invite-register-button"
                disabled={pageState.status === "registering"}
                onClick={() => void handleRegister()}
              >
                {pageState.status === "registering"
                  ? "Registering…"
                  : "Register passkey"}
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default InviteLandingPage
