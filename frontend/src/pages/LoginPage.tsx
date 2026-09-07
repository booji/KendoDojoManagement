import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
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
import { performPasskeyLogin } from "@/api/auth"
import { errorMessage } from "@/api/client"
import { getBranding } from "@/api/settings"
import type { DojoBranding } from "@/api/settings"

const LoginPage = () => {
  const [email, setEmail] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [branding, setBranding] = useState<DojoBranding | null>(null)

  useEffect(() => {
    getBranding()
      .then((data) => setBranding(data))
      .catch(() => {
        // Tolerate failure silently — fall back to the bare card.
      })
  }, [])

  const handlePasskeyLogin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)

    if (!navigator.credentials) {
      setError("Passkeys are not supported on this browser/device")
      return
    }

    setLoading(true)
    try {
      await performPasskeyLogin(email)
      // A full load, not navigate(): login has just issued the theme cookie,
      // and only a fresh document lets the pre-paint script in index.html read
      // it. A client-side transition would keep the pre-login theme until the
      // user happened to reload (#324).
      window.location.assign("/")
    } catch (err) {
      setError(errorMessage(err, "An unexpected error occurred"))
    } finally {
      setLoading(false)
    }
  }

  const hasBackground = branding?.background_image_url != null
  const hasLogo = branding?.logo_url != null
  const hasName = branding?.dojo_name != null

  return (
    <div className="relative flex min-h-screen items-center justify-center px-4 py-8">
      {hasBackground && (
        <>
          <div
            className="fixed inset-0 -z-20 bg-cover bg-center"
            style={{ backgroundImage: `url(${branding?.background_image_url})` }}
            aria-hidden="true"
          />
          <div className="fixed inset-0 -z-10 bg-black/40" aria-hidden="true" />
        </>
      )}
      <div className="flex w-full max-w-sm flex-col items-center gap-4">
        {hasLogo && (
          <img
            src={branding?.logo_url ?? undefined}
            alt="Dojo logo"
            className="h-16 w-16 rounded-md object-cover"
          />
        )}
        {hasName && (
          <h1
            className={
              hasBackground
                ? "text-center text-2xl font-semibold text-white"
                : "text-center text-2xl font-semibold"
            }
          >
            {branding?.dojo_name}
          </h1>
        )}
        <Card className="w-full">
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
            <CardDescription>Sign in with your passkey</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handlePasskeyLogin} className="flex flex-col gap-4">
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
                {loading ? "Signing in…" : "Sign in with passkey"}
              </Button>
              <p className="text-center text-sm text-muted-foreground">
                No account yet?{" "}
                <Link to="/register" className="text-primary underline-offset-4 hover:underline">
                  Register
                </Link>
              </p>
              <p className="text-center text-sm text-muted-foreground">
                <Link to="/recovery/redeem" className="text-primary underline-offset-4 hover:underline">
                  Use a recovery code
                </Link>
              </p>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default LoginPage
