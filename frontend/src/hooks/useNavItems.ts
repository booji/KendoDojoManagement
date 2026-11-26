import {
  LayoutDashboardIcon,
  CalendarDaysIcon,
  ClipboardListIcon,
  UserIcon,
  UsersIcon,
  BarChartIcon,
  SettingsIcon,
  type LucideIcon,
} from "lucide-react"

// UserIcon used by MEMBER_NAV_ITEMS (My Profile)

export type NavItem = {
  label: string
  /** Shorter text for the 375px bottom tab bar; its accessible name stays label. */
  tabLabel?: string
  href: string
  icon: LucideIcon
}

const MEMBER_NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboardIcon },
  { label: "Sessions", href: "/sessions", icon: CalendarDaysIcon },
  { label: "My Attendance", tabLabel: "Attendance", href: "/attendance", icon: ClipboardListIcon },
  { label: "My Profile", href: "/profile", icon: UserIcon },
]

const ADMIN_NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboardIcon },
  { label: "Members", href: "/members", icon: UsersIcon },
  { label: "Sessions", href: "/sessions", icon: CalendarDaysIcon },
  { label: "My Attendance", tabLabel: "Attendance", href: "/attendance", icon: ClipboardListIcon },
  { label: "Reports", href: "/reports", icon: BarChartIcon },
  { label: "Settings", href: "/settings", icon: UserIcon },
  { label: "Admin Settings", href: "/admin/settings", icon: SettingsIcon },
]

export const useNavItems = (role: "member" | "admin"): NavItem[] =>
  role === "admin" ? ADMIN_NAV_ITEMS : MEMBER_NAV_ITEMS
