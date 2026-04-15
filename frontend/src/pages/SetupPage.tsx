import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { checkSetupAvailable, performSetupPasskeyRegistration } from "@/api/setup"
import { isApiError } from "@/api/auth"
import { generateRecoveryCodes } from "@/api/recovery"

type SetupStep = "passkey" | "recovery"

const SetupPage = () => {
  const navigate = useNavigate()
  const [step, setStep] = useState<SetupStep>("passkey")
  const [email, setEmail] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(true)

  // Recovery codes step state
  const [codes, setCodes] = useState<string[]>([])
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)

  useEffect(() => {
    checkSetupAvailable()
      .then((available) => {
        if (!available) {
          navigate("/login", { replace: true })
        } else {
          setChecking(false)
        }
      })
      .catch(() => {
        navigate("/login", { replace: true })
      })
  }, [navigate])

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)

    if (!navigator.credentials) {
      setError("Passkeys are not supported on this browser/device")
      return
    }

    setLoading(true)
    try {
      await performSetupPasskeyRegistration(email)
      setStep("recovery")
    } catch (err) {
      if (isApiError(err)) {
        setError(err.message)
      } else {
        setError("An unexpected error occurred")
      }
    } finally {
      setLoading(false)
    }
  }

  const handleGenerate = async () => {
    setGenerateError(null)
    setGenerating(true)
    try {
      const result = await generateRecoveryCodes()
      setCodes(result.codes)
    } catch (err) {
      setGenerateError(isApiError(err) ? err.message : "Failed to generate codes")
    } finally {
      setGenerating(false)
    }
  }

  if (checking) {
    return null
  }

  if (step === "recovery") {
    return (
      <div className="flex min-h-screen items-center justify-center px-4 py-8">
        <Card className="w-full max-w-sm">
          <CardHeader>
            <CardTitle>Save your recovery codes</CardTitle>
            <CardDescription>
              Recovery codes let you access your account if you ever lose your passkey.
              Generate and save them now — they won't be shown again.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {codes.length === 0 ? (
              <>
                {generateError !== null && (
                  <p className="text-sm text-destructive" role="alert">
                    {generateError}
                  </p>
                )}
                <Button onClick={handleGenerate} disabled={generating} className="w-full">
                  {generating ? "Generating…" : "Generate recovery codes"}
                </Button>
                <button
                  type="button"
                  onClick={() => navigate("/", { replace: true })}
                  className="text-sm text-muted-foreground underline underline-offset-4 text-center"
                >
                  Skip for now
                </button>
              </>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-2 font-mono text-sm">
                  {codes.map((code) => (
                    <span key={code} className="rounded bg-muted px-2 py-1 text-center">
                      {code}
                    </span>
                  ))}
                </div>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={acknowledged}
                    onChange={(e) => setAcknowledged(e.target.checked)}
                    className="h-4 w-4"
                  />
                  I have saved my recovery codes
                </label>
                <Button
                  onClick={() => navigate("/", { replace: true })}
                  disabled={!acknowledged}
                  className="w-full"
                >
                  Continue
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Welcome to Kendo Dojo</CardTitle>
          <CardDescription>
            No accounts exist yet. Create your admin passkey to get started.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            {error !== null && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" size="lg" disabled={loading} className="w-full">
              {loading ? "Setting up…" : "Create admin passkey"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export default SetupPage
