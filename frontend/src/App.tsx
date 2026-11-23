import { useEffect, useState } from "react"
import { BrowserRouter, Routes, Route, Navigate, useNavigate, Outlet, useOutletContext } from "react-router-dom"
import { getMe } from "@/api/auth"
import { markSessionEstablished } from "@/api/client"
import type { AccountClaims } from "@/api/auth"
import { checkSetupAvailable } from "@/api/setup"
import { getMyMember } from "@/api/accounts"
import { ThemeProvider } from "@/contexts/ThemeProvider"
import { DojoSettingsProvider, useDojoSettings } from "@/contexts/DojoSettingsProvider"
import AppShell from "@/components/AppShell"
import DevicePasskeyPrompt from "@/components/DevicePasskeyPrompt"
import HomePage from "@/pages/HomePage"
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
import AdminGeneralSettingsPage from "@/pages/AdminGeneralSettingsPage"
import AdminSessionTypesPage from "@/pages/AdminSessionTypesPage"
import AdminFederationsPage from "@/pages/AdminFederationsPage"
import AdminInvitesPage from "@/pages/AdminInvitesPage"
import InviteLandingPage from "@/pages/InviteLandingPage"
import SessionCheckinPage from "@/pages/SessionCheckinPage"
import SetupPage from "@/pages/SetupPage"
import RecoveryRedeemPage from "@/pages/RecoveryRedeemPage"
import PasskeyRegisterPage from "@/pages/PasskeyRegisterPage"
import SessionDetailPage from "@/pages/SessionDetailPage"
import OnboardingPage from "@/pages/OnboardingPage"

type LayoutContext = { user: AccountClaims }

// Wraps authenticated routes — fetches current user and renders AppShell.
// Redirects to /login on auth failure.
const AuthenticatedLayout = () => {
  const { refresh } = useDojoSettings()
  const navigate = useNavigate()
  const [user, setUser] = useState<AccountClaims | null>(null)

  useEffect(() => {
    getMe()
      .then((me) => {
        // From here a 401 means the session ended rather than "never signed
        // in", which is what lets apiFetch route it to /login (#387).
        markSessionEstablished()
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
      <DevicePasskeyPrompt />
    </AppShell>
  )
}

// Wraps admin-only routes — redirects non-admins to /.
const RequireAdmin = () => {
  const { user } = useOutletContext<LayoutContext>()
  return user.role === "admin" ? <Outlet context={{ user } satisfies LayoutContext} /> : <Navigate to="/" replace />
}

// Wraps profile-required routes — redirects to /onboarding if profile is incomplete.
const RequireProfile = () => {
  const { user } = useOutletContext<LayoutContext>()
  const [ready, setReady] = useState(false)
  const [redirect, setRedirect] = useState(false)

  useEffect(() => {
    getMyMember()
      .then((member) => {
        const incomplete =
          member === null ||
          !member.first_name ||
          !member.surname ||
          !member.dob
        setRedirect(incomplete)
        setReady(true)
      })
      .catch(() => {
        // On error, allow through — don't block the user
        setReady(true)
      })
  }, [])

  if (!ready) return null
  if (redirect) return <Navigate to="/onboarding" replace />
  return <Outlet context={{ user } satisfies LayoutContext} />
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
          <Route path="/invite/:token" element={<InviteLandingPage />} />

          {/* Authenticated routes — wrapped in AppShell */}
          <Route element={<AuthenticatedLayout />}>
            {/* Onboarding: authenticated but NOT profile-gated */}
            <Route path="/onboarding" element={<OnboardingPage />} />

            {/* Profile-required routes */}
            <Route element={<RequireProfile />}>
              <Route path="/" element={<HomePage />} />
              <Route path="/sessions" element={<SessionsPage />} />
              <Route path="/sessions/:id" element={<SessionDetailPage />} />
              <Route path="/attendance" element={<AttendancePage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/checkin/session/:id" element={<SessionCheckinPage />} />

              {/* Admin-only routes */}
              <Route element={<RequireAdmin />}>
                <Route path="/members" element={<MembersPage />} />
                <Route path="/members/:id" element={<MemberDetailPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/admin/settings" element={<AdminSettingsPage />}>
                  <Route index element={<Navigate to="general" replace />} />
                  <Route path="general" element={<AdminGeneralSettingsPage />} />
                  <Route path="session-types" element={<AdminSessionTypesPage />} />
                  <Route path="federations" element={<AdminFederationsPage />} />
                  <Route path="invites" element={<AdminInvitesPage />} />
                  <Route path="grades" element={<GradesPage />} />
                </Route>
              </Route>
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </DojoSettingsProvider>
  </ThemeProvider>
)

export default App
