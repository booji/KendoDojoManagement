import { useEffect, useState } from "react"
import { NavLink, Outlet } from "react-router-dom"
import { getVersion } from "@/api/settings"
import { PageHeader } from "@/components/ui/page-header"
import { cn } from "@/lib/utils"

// Each Admin Settings sub-page is its own route (#610); future types get a
// sub-page here rather than a section on an existing one.
const SUB_PAGES = [
  { label: "General", to: "general" },
  { label: "Session Types", to: "session-types" },
  { label: "Federations", to: "federations" },
  { label: "Invites", to: "invites" },
  { label: "Grades", to: "grades" },
]

// ── Version (#556) ─────────────────────────────────────────────────────────────

// Nothing renders until the Version arrives: a failed fetch leaves no line
// rather than an error, since it is only there for bug reports.
const VersionLine = () => {
  const [version, setVersion] = useState<string | null>(null)

  useEffect(() => {
    getVersion()
      .then((data) => setVersion(data.version))
      .catch(() => {})
  }, [])

  if (version === null) return null
  return <p className="text-xs text-muted-foreground">Version {version}</p>
}

// ── Layout ────────────────────────────────────────────────────────────────────

// A horizontally scrolling strip on mobile, a vertical list beside the
// content on desktop. NavLink sets aria-current="page" on the current one.
const SubNav = () => (
  <nav aria-label="Admin Settings sections" className="-mx-4 overflow-x-auto px-4 md:mx-0 md:px-0">
    <ul className="flex gap-1 md:flex-col">
      {SUB_PAGES.map((p) => (
        <li key={p.to} className="shrink-0">
          <NavLink
            to={p.to}
            data-tour={`admin-settings-${p.to}`}
            className={({ isActive }) =>
              cn(
                "flex min-h-[44px] items-center whitespace-nowrap rounded-md px-3 text-sm hover:bg-muted",
                isActive ? "bg-muted font-medium text-foreground" : "text-muted-foreground",
              )
            }
          >
            {p.label}
          </NavLink>
        </li>
      ))}
    </ul>
  </nav>
)

const AdminSettingsPage = () => (
  <div className="px-4 py-6 space-y-6">
    <PageHeader title="Admin Settings" />

    <div className="flex flex-col gap-6 md:flex-row md:gap-8">
      <div className="md:w-48 md:shrink-0">
        <SubNav />
      </div>
      <div className="min-w-0 flex-1 space-y-8">
        <Outlet />
      </div>
    </div>

    <VersionLine />
  </div>
)

export default AdminSettingsPage
