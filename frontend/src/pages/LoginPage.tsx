import { useState } from "react"
import { useNavigate, Link } from "react-router-dom"
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
import { loginWithPassword, performPasskeyLogin, isApiError } from "@/api/auth"

type Mode = "passkey" | "password"

const LoginPage = () => {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>("passkey")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

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
      navigate("/")
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

  const handlePasswordLogin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      await loginWithPassword({ email, password })
      navigate("/")
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

  const switchMode = (next: Mode) => {
    setError(null)
    setMode(next)
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>
            {mode === "passkey"
              ? "Sign in with your passkey"
              : "Sign in with email and password"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {mode === "passkey" ? (
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
                <button
                  type="button"
                  onClick={() => switchMode("password")}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  Use email and password instead
                </button>
              </p>
              <p className="text-center text-sm text-muted-foreground">
                No account yet?{" "}
                <Link to="/register" className="text-primary underline-offset-4 hover:underline">
                  Register
                </Link>
              </p>
            </form>
          ) : (
            <form onSubmit={handlePasswordLogin} className="flex flex-col gap-4">
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
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                />
              </div>
              {error !== null && (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              )}
              <Button type="submit" size="lg" disabled={loading} className="w-full">
                {loading ? "Signing in…" : "Sign in"}
              </Button>
              <p className="text-center text-sm text-muted-foreground">
                <button
                  type="button"
                  onClick={() => switchMode("passkey")}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  Use passkey instead
                </button>
              </p>
              <p className="text-center text-sm text-muted-foreground">
                No account yet?{" "}
                <Link to="/register" className="text-primary underline-offset-4 hover:underline">
                  Register
                </Link>
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default LoginPage
