import { useEffect, useState } from "react"
import { BrowserRouter, Routes, Route, useNavigate, Outlet } from "react-router-dom"
import { getMe, isApiError } from "@/api/auth"
import type { UserClaims } from "@/api/auth"
import AppShell from "@/components/AppShell"
import HomePage from "@/pages/HomePage"
import LoginPage from "@/pages/LoginPage"
import RegisterPage from "@/pages/RegisterPage"
import SessionsPage from "@/pages/SessionsPage"
import AttendancePage from "@/pages/AttendancePage"
import ProfilePage from "@/pages/ProfilePage"
import MembersPage from "@/pages/MembersPage"
import GradesPage from "@/pages/GradesPage"
import ReportsPage from "@/pages/ReportsPage"
import SettingsPage from "@/pages/SettingsPage"

// Wraps authenticated routes — fetches current user and renders AppShell.
// Redirects to /login on auth failure.
const AuthenticatedLayout = () => {
  const navigate = useNavigate()
  const [user, setUser] = useState<UserClaims | null>(null)

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch((err: unknown) => {
        if (isApiError(err) && (err.status === 401 || err.status === 403)) {
          navigate("/login", { replace: true })
        } else {
          navigate("/login", { replace: true })
        }
      })
  }, [navigate])

  if (user === null) {
    return null
  }

  return (
    <AppShell role={user.role}>
      <Outlet />
    </AppShell>
  )
}

const App = () => (
  <BrowserRouter>
    <Routes>
      {/* Public routes — no AppShell */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      {/* Authenticated routes — wrapped in AppShell */}
      <Route element={<AuthenticatedLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/attendance" element={<AttendancePage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/members" element={<MembersPage />} />
        <Route path="/grades" element={<GradesPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  </BrowserRouter>
)

export default App
