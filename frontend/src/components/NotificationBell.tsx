import { Link } from "react-router-dom"
import { Bell } from "lucide-react"
import type { PendingGradeEntry } from "@/api/grades"
import {
  Popover,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover"
import { cn } from "@/lib/utils"

type NotificationBellProps = {
  items: PendingGradeEntry[]
  /** Where the bell sits: sets its colours and which way the popover opens. */
  placement?: "sidebar" | "topbar"
}

const NotificationBell = ({ items, placement = "sidebar" }: NotificationBellProps) => {
  const count = items.length
  const inSidebar = placement === "sidebar"
  return (
    <Popover>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={count > 0 ? `Notifications, ${count} pending` : "Notifications"}
            className={cn(
              "relative inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 transition-colors",
              inSidebar
                ? "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-sidebar-ring"
                : "text-foreground hover:bg-accent hover:text-accent-foreground focus-visible:ring-ring"
            )}
          />
        }
      >
        <Bell aria-hidden="true" className="size-4" />
        {count > 0 && (
          <span
            aria-hidden="true"
            className="min-w-4 rounded-full bg-primary px-1 text-center text-xs font-medium leading-4 text-primary-foreground"
          >
            {count}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent side={inSidebar ? "top" : "bottom"} align={inSidebar ? "start" : "end"}>
        <PopoverHeader>
          <PopoverTitle>Needs your action</PopoverTitle>
        </PopoverHeader>
        {count === 0 ? (
          <p className="text-muted-foreground">Nothing is waiting for you.</p>
        ) : (
          <ul className="flex flex-col">
            {items.map((item) => (
              <li key={item.id}>
                <Link
                  to="/admin/settings/grades"
                  className="flex flex-col rounded-md px-2 py-1.5 hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="font-medium">{item.member_name}</span>
                  <span className="text-muted-foreground">
                    Grade approval: {item.display_name}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  )
}

export default NotificationBell
