import { useEffect, useState } from "react"
import { BrowserRouter, Routes, Route, Navigate, useNavigate, Outlet, useOutletContext } from "react-router-dom"
import { getMe } from "@/api/auth"
import type { UserClaims } from "@/api/auth"
import { checkSetupAvailable } from "@/api/setup"
import { ThemeProvider } from "@/contexts/ThemeProvider"
import { DojoSettingsProvider, useDojoSettings } from "@/contexts/DojoSettingsProvider"
import AppShell from "@/components/AppShell"
import AdminDashboardPage from "@/pages/AdminDashboardPage"
import MemberDashboardPage from "@/pages/MemberDashboardPage"
import LoginPage from "@/pages/LoginPage"
import RegisterPage from "@/pages/RegisterPage"
import SessionsPage from "@/pages/SessionsPage"
import AttendancePage from "@/pages/AttendancePage"
import ProfilePage from "@/pages/ProfilePage"
import MembersPage from "@/pages/MembersPage"
import MemberDetailPage from "@/pages/MemberDetailPage"
import GradesPage from "@/pages/GradesPage"
import ReportsPage from "@/pages/ReportsPage"
import SettingsPage from "@/pages/SettingsPage"
import AdminSettingsPage from "@/pages/AdminSettingsPage"
import CheckinPage from "@/pages/CheckinPage"
import SetupPage from "@/pages/SetupPage"
import RecoveryRedeemPage from "@/pages/RecoveryRedeemPage"
import PasskeyRegisterPage from "@/pages/PasskeyRegisterPage"
import SessionDetailPage from "@/pages/SessionDetailPage"

type LayoutContext = { user: UserClaims }

// Renders the correct dashboard based on user role
const DashboardRoute = () => {
  const { user } = useOutletContext<LayoutContext>()
  return user.role === "admin" ? <AdminDashboardPage /> : <MemberDashboardPage />
}

// Wraps authenticated routes — fetches current user and renders AppShell.
// Redirects to /login on auth failure.
const AuthenticatedLayout = () => {
  const { refresh } = useDojoSettings()
  const navigate = useNavigate()
  const [user, setUser] = useState<UserClaims | null>(null)

  useEffect(() => {
    getMe()
      .then((me) => {
        setUser(me)
        refresh()
      })
      .catch(() => {
        checkSetupAvailable()
          .then((available) => {
            navigate(available ? "/setup" : "/login", { replace: true })
          })
          .catch(() => {
            navigate("/login", { replace: true })
          })
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate])

  if (user === null) {
    return null
  }

  return (
    <AppShell role={user.role}>
      <Outlet context={{ user } satisfies LayoutContext} />
    </AppShell>
  )
}

// Wraps admin-only routes — redirects non-admins to /.
const RequireAdmin = () => {
  const { user } = useOutletContext<LayoutContext>()
  return user.role === "admin" ? <Outlet context={{ user } satisfies LayoutContext} /> : <Navigate to="/" replace />
}

const App = () => (
  <ThemeProvider>
    <DojoSettingsProvider>
      <BrowserRouter>
        <Routes>
          {/* Public routes — no AppShell */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/setup" element={<SetupPage />} />
          <Route path="/recovery/redeem" element={<RecoveryRedeemPage />} />
          <Route path="/passkey/register" element={<PasskeyRegisterPage />} />

          {/* Authenticated routes — wrapped in AppShell */}
          <Route element={<AuthenticatedLayout />}>
            <Route path="/" element={<DashboardRoute />} />
            <Route path="/sessions" element={<SessionsPage />} />
            <Route path="/sessions/:id" element={<SessionDetailPage />} />
            <Route path="/attendance" element={<AttendancePage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/checkin/:token" element={<CheckinPage />} />

            {/* Admin-only routes */}
            <Route element={<RequireAdmin />}>
              <Route path="/members" element={<MembersPage />} />
              <Route path="/members/:id" element={<MemberDetailPage />} />
              <Route path="/grades" element={<GradesPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/admin/settings" element={<AdminSettingsPage />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </DojoSettingsProvider>
  </ThemeProvider>
)

export default App
