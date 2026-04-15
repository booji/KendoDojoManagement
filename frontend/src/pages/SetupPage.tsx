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

const SetupPage = () => {
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(true)

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
        // If we can't determine setup status, redirect to login
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
      navigate("/", { replace: true })
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

  if (checking) {
    return null
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
