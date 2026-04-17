import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { performPasskeyRegistration, isApiError } from "@/api/auth"
import { isRecoverySession, clearRecoveryToken, getRecoveryToken } from "@/lib/recoverySession"

// Decode JWT email claim so we can pre-fill it for the WebAuthn call
const emailFromToken = (token: string | null): string | null => {
  if (!token) return null
  try {
    const payload = JSON.parse(atob(token.split(".")[1])) as Record<string, unknown>
    return typeof payload.email === "string" ? payload.email : null
  } catch {
    return null
  }
}

type PageState =
  | { status: "idle" }
  | { status: "registering" }
  | { status: "success" }
  | { status: "error"; message: string }

const PasskeyRegisterPage = () => {
  const navigate = useNavigate()
  const [recoveryActive] = useState(() => isRecoverySession())
  const [email] = useState(() => emailFromToken(getRecoveryToken()))
  const [pageState, setPageState] = useState<PageState>({ status: "idle" })

  // If no recovery session and we somehow land here, bounce to login
  useEffect(() => {
    if (!recoveryActive) {
      navigate("/login", { replace: true })
    }
  }, [recoveryActive, navigate])

  const handleRegister = async () => {
    if (!email) {
      setPageState({ status: "error", message: "Could not determine email from recovery token." })
      return
    }

    setPageState({ status: "registering" })

    try {
      await performPasskeyRegistration(email)
      clearRecoveryToken()
      setPageState({ status: "success" })
    } catch (err) {
      setPageState({
        status: "error",
        message: isApiError(err) ? err.message : "Passkey registration failed",
      })
    }
  }

  const handleContinue = () => {
    navigate("/")
  }

  if (!recoveryActive) {
    return null
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-8">
      <div className="w-full max-w-sm flex flex-col gap-4">
        {/* Recovery session banner — always shown on this page */}
        <div
          data-testid="recovery-session-banner"
          className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
          role="alert"
        >
          You&apos;re using a recovery session &mdash; please register your passkey to restore full
          access.
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Register your passkey</CardTitle>
            <CardDescription>
              Create a passkey for <strong>{email}</strong> to restore secure access to your
              account.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {pageState.status === "success" ? (
              <>
                <p className="text-sm text-green-700 dark:text-green-400" role="status">
                  Passkey registered successfully.
                </p>

                {/* Stale passkey recommendation — shown after successful registration via recovery */}
                <div
                  data-testid="stale-passkey-recommendation"
                  className="rounded-lg border border-border bg-muted px-4 py-3 text-sm text-muted-foreground"
                  role="note"
                >
                  You may have stale passkeys from before. Consider reviewing your passkeys and
                  removing any you no longer need.
                </div>

                <Button size="lg" className="w-full" onClick={handleContinue}>
                  Go to dashboard
                </Button>
              </>
            ) : (
              <>
                {pageState.status === "error" && (
                  <p className="text-sm text-destructive" role="alert">
                    {pageState.message}
                  </p>
                )}
                <Button
                  size="lg"
                  className="w-full"
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
    </div>
  )
}

export default PasskeyRegisterPage
