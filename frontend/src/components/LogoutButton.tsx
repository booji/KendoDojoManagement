import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { LogOut } from "lucide-react"
import { logout } from "@/api/auth"
import { cn } from "@/lib/utils"

type LogoutButtonProps = {
  className?: string
  labelClassName?: string
}

// Shared sign-out control for the desktop sidebar footer (next to ThemeToggle)
// and the mobile "More" sheet. Calls the backend logout endpoint, then
// navigates to /login with `replace` so browser Back can't restore an
// authenticated view. On a network failure the session cookie was never
// cleared server-side, so we deliberately do NOT navigate away — that would
// strand the user on a login screen that still has a live, authenticated
// session. Instead we surface an inline error and leave them where they are.
const LogoutButton = ({ className, labelClassName }: LogoutButtonProps) => {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleLogout = async () => {
    setError(null)
    setLoading(true)
    try {
      await logout()
      navigate("/login", { replace: true })
    } catch {
      setError("Couldn't sign out. Check your connection and try again.")
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handleLogout}
        disabled={loading}
        aria-label="Log out"
        className={cn(
          "inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring transition-colors disabled:pointer-events-none disabled:opacity-50",
          className
        )}
      >
        <LogOut aria-hidden="true" className="size-4" />
        <span className={cn("group-data-[collapsible=icon]:hidden", labelClassName)}>
          Log out
        </span>
      </button>
      {error !== null && (
        <p className="px-2 text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

export default LogoutButton
