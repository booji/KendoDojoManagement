import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"
import { useNavItems } from "@/hooks/useNavItems"
import { useThemeContext } from "@/contexts/ThemeProvider"
import { useDojoSettings } from "@/contexts/DojoSettingsProvider"
import BottomTabBar from "@/components/BottomTabBar"
import ThemeToggle from "@/components/ThemeToggle"
import LogoutButton from "@/components/LogoutButton"
import NotificationBell from "@/components/NotificationBell"
import { useNotifications } from "@/hooks/useNotifications"
import {
  SidebarProvider,
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarGroup,
  SidebarGroupContent,
  SidebarInset,
} from "@/components/ui/sidebar"
import { TooltipProvider } from "@/components/ui/tooltip"

// Admin has 7 items; bottom bar shows 4 primaries + "More" for the rest.
// Member has 4 items; all fit in the bottom bar.
const PRIMARY_COUNT = 4

type AppShellProps = {
  role: "member" | "admin"
  children: React.ReactNode
}

const DojoLogo = () => {
  const { dojoName, logoUrl } = useDojoSettings()
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      {logoUrl !== null ? (
        <img
          src={logoUrl}
          alt={dojoName}
          className="size-8 rounded-md object-cover shrink-0"
        />
      ) : (
        <img src="/logo.svg" alt="" className="size-8 shrink-0" />
      )}
      <span className="font-semibold text-sm truncate">{dojoName}</span>
    </div>
  )
}

const AppShell = ({ role, children }: AppShellProps) => {
  const navItems = useNavItems(role)
  const { pathname } = useLocation()
  const { theme, setTheme } = useThemeContext()
  // One poller shared by the desktop and mobile bells.
  const notifications = useNotifications(role)
  const showBell = role === "admin"

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href)

  const primaryItems = navItems.slice(0, PRIMARY_COUNT)
  const overflowItems = navItems.slice(PRIMARY_COUNT)

  return (
    <TooltipProvider>
      <SidebarProvider>
        {/* Desktop sidebar — hidden on mobile via CSS inside Sidebar */}
        <Sidebar collapsible="icon">
          <SidebarHeader>
            <DojoLogo />
          </SidebarHeader>

          <SidebarContent>
            <SidebarGroup>
              <SidebarGroupContent>
                <SidebarMenu>
                  {navItems.map((item) => {
                    const active = isActive(item.href)
                    return (
                      <SidebarMenuItem key={item.href}>
                        <SidebarMenuButton
                          isActive={active}
                          tooltip={item.label}
                          render={
                            <Link
                              to={item.href}
                              aria-label={item.label}
                              data-tour={`nav-${item.href}`}
                              aria-current={active ? "page" : undefined}
                              className={cn(
                                "focus-visible:ring-2 focus-visible:ring-sidebar-ring"
                              )}
                            />
                          }
                        >
                          <item.icon aria-hidden="true" />
                          <span>{item.label}</span>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    )
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          </SidebarContent>

          <SidebarFooter>
            {/* Destructive action leftmost, safe action rightmost (macOS HIG). */}
            <div className="flex items-center justify-between gap-2">
              <LogoutButton />
              <div className="flex items-center gap-1">
                {showBell && <NotificationBell items={notifications} />}
                <ThemeToggle theme={theme} setTheme={setTheme} />
              </div>
            </div>
          </SidebarFooter>
        </Sidebar>

        <SidebarInset>
          {/* Mobile top bar: the app has no other header on mobile. */}
          {showBell && (
            <header className="sticky top-0 z-40 flex h-11 items-center justify-end border-b bg-background px-2 md:hidden">
              <NotificationBell items={notifications} placement="topbar" />
            </header>
          )}
          {/* Page content — add bottom padding on mobile to clear the tab bar */}
          <div className="flex flex-col min-h-full pb-[calc(64px+env(safe-area-inset-bottom))] md:pb-0">
            {children}
          </div>
        </SidebarInset>

        {/* Mobile bottom tab bar */}
        <BottomTabBar
          primaryItems={primaryItems}
          overflowItems={overflowItems}
        />
      </SidebarProvider>
    </TooltipProvider>
  )
}

export default AppShell
