import { Link, useLocation } from "react-router-dom"
import { cn } from "@/lib/utils"
import { useNavItems } from "@/hooks/useNavItems"
import BottomTabBar from "@/components/BottomTabBar"
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

const DojoLogo = () => (
  <div className="flex items-center gap-2 px-2 py-1">
    <div
      className="size-8 rounded-md bg-muted shrink-0"
      aria-hidden="true"
    />
    <span className="font-semibold text-sm truncate">My Dojo</span>
  </div>
)

const AppShell = ({ role, children }: AppShellProps) => {
  const navItems = useNavItems(role)
  const { pathname } = useLocation()

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

          {/* Footer placeholder — theme toggle will be added in issue #14 */}
          <SidebarFooter />
        </Sidebar>

        <SidebarInset>
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
