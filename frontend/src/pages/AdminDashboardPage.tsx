import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

type AdminDashboard = {
  active_members: number
  sessions_this_week: number
  attendance_rate: number
  attendance_trend: number
}

const fetchAdminDashboard = async (): Promise<AdminDashboard> => {
  const res = await fetch("/api/dashboard/admin", { credentials: "include" })
  if (!res.ok) {
    throw new Error(`Failed to fetch dashboard: ${res.status}`)
  }
  return res.json() as Promise<AdminDashboard>
}

const TrendIndicator = ({ trend }: { trend: number }) => {
  const pct = Math.round(Math.abs(trend) * 100)
  if (trend > 0) {
    return (
      <span className="flex items-center gap-1 text-green-600 dark:text-green-400" aria-label={`Trending up ${pct}%`}>
        <TrendingUp className="h-5 w-5" aria-hidden="true" />
        <span>+{pct}%</span>
      </span>
    )
  }
  if (trend < 0) {
    return (
      <span className="flex items-center gap-1 text-red-600 dark:text-red-400" aria-label={`Trending down ${pct}%`}>
        <TrendingDown className="h-5 w-5" aria-hidden="true" />
        <span>-{pct}%</span>
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1 text-muted-foreground" aria-label="No change">
      <Minus className="h-5 w-5" aria-hidden="true" />
      <span>±0%</span>
    </span>
  )
}

const DashboardSkeletons = () => (
  <div className="grid grid-cols-2 md:grid-cols-4 gap-4" aria-busy="true" aria-label="Loading dashboard">
    {Array.from({ length: 4 }).map((_, i) => (
      <Card key={i}>
        <CardHeader className="pb-2">
          <Skeleton className="h-4 w-24" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-8 w-16" />
        </CardContent>
      </Card>
    ))}
  </div>
)

const AdminDashboardPage = () => {
  const navigate = useNavigate()
  const [dashboard, setDashboard] = useState<AdminDashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    fetchAdminDashboard()
      .then((data) => {
        setDashboard(data)
        setError(null)
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load dashboard")
      })
      .finally(() => {
        setLoading(false)
      })
  }

  useEffect(() => {
    load()
    const interval = setInterval(load, 30_000)
    const handleVisibility = () => {
      if (document.visibilityState === "visible") load()
    }
    document.addEventListener("visibilitychange", handleVisibility)
    return () => {
      clearInterval(interval)
      document.removeEventListener("visibilitychange", handleVisibility)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="px-4 py-6 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <Button
          size="lg"
          onClick={() => void navigate("/sessions/new")}
          aria-label="Create a new session"
          className="min-h-[44px]"
        >
          Create Session
        </Button>
      </div>

      {loading && <DashboardSkeletons />}

      {!loading && error !== null && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}

      {!loading && dashboard !== null && (
        <div
          className="grid grid-cols-2 md:grid-cols-4 gap-4"
          aria-label="Dashboard statistics"
        >
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Active Members
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold tabular-nums">
                {dashboard.active_members}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Sessions This Week
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold tabular-nums">
                {dashboard.sessions_this_week}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Attendance Rate
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold tabular-nums">
                {Math.round(dashboard.attendance_rate * 100)}%
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Attendance Trend
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">
                <TrendIndicator trend={dashboard.attendance_trend} />
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}

export default AdminDashboardPage
