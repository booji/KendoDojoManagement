import { useState } from "react"
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
import { redeemRecoveryCode } from "@/api/auth"
import { errorMessage } from "@/api/client"
import { storeRecoveryToken } from "@/lib/recoverySession"

const RecoveryRedeemPage = () => {
  const navigate = useNavigate()
  const [email, setEmail] = useState("")
  const [code, setCode] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setError(null)
    setLoading(true)

    try {
      const { access_token } = await redeemRecoveryCode(email, code)
      storeRecoveryToken(access_token)
      navigate("/passkey/register")
    } catch (err) {
      setError(errorMessage(err, "An unexpected error occurred"))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Redeem recovery code</CardTitle>
          <CardDescription>
            Enter your email and recovery code to regain access.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="recovery-email">Email</Label>
              <Input
                id="recovery-email"
                data-testid="recovery-email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="recovery-code">Recovery code</Label>
              <Input
                id="recovery-code"
                data-testid="recovery-code"
                type="text"
                placeholder="xxxx-xxxx-xxxx"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                autoComplete="off"
              />
            </div>
            {error !== null && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <Button
              type="submit"
              size="lg"
              disabled={loading}
              className="w-full"
              data-testid="recovery-submit"
            >
              {loading ? "Verifying…" : "Redeem recovery code"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

export default RecoveryRedeemPage
