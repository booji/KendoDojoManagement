import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { MoreHorizontalIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import type { NavItem } from "@/hooks/useNavItems"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"

type BottomTabBarProps = {
  primaryItems: NavItem[]
  overflowItems: NavItem[]
}

const BottomTabBar = ({ primaryItems, overflowItems }: BottomTabBarProps) => {
  const { pathname } = useLocation()
  const [sheetOpen, setSheetOpen] = useState(false)

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href)

  return (
    <>
      <nav
        aria-label="Main navigation"
        className="md:hidden fixed bottom-0 inset-x-0 z-40 flex border-t bg-background"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        {primaryItems.map((item) => {
          const active = isActive(item.href)
          return (
            <Link
              key={item.href}
              to={item.href}
              aria-label={item.label}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex flex-1 flex-col items-center justify-center gap-0.5 min-h-[44px] min-w-[44px] py-2 text-xs font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                active
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <item.icon className="size-5 shrink-0" aria-hidden="true" />
              <span>{item.label}</span>
            </Link>
          )
        })}

        {overflowItems.length > 0 && (
          <button
            type="button"
            aria-label="More navigation items"
            aria-expanded={sheetOpen}
            onClick={() => setSheetOpen(true)}
            className={cn(
              "flex flex-1 flex-col items-center justify-center gap-0.5 min-h-[44px] min-w-[44px] py-2 text-xs font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              "text-muted-foreground hover:text-foreground"
            )}
          >
            <MoreHorizontalIcon className="size-5 shrink-0" aria-hidden="true" />
            <span>More</span>
          </button>
        )}
      </nav>

      {overflowItems.length > 0 && (
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent side="bottom" showCloseButton>
            <SheetHeader>
              <SheetTitle>More</SheetTitle>
            </SheetHeader>
            <nav
              aria-label="More navigation items"
              className="flex flex-col gap-1 pb-4 px-4"
            >
              {overflowItems.map((item) => {
                const active = isActive(item.href)
                return (
                  <Link
                    key={item.href}
                    to={item.href}
                    aria-label={item.label}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setSheetOpen(false)}
                    className={cn(
                      "flex items-center gap-3 rounded-md px-3 min-h-[44px] text-sm font-medium transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      active
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    )}
                  >
                    <item.icon className="size-5 shrink-0" aria-hidden="true" />
                    {item.label}
                  </Link>
                )
              })}
            </nav>
          </SheetContent>
        </Sheet>
      )}
    </>
  )
}

export default BottomTabBar
