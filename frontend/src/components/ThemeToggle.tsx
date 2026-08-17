import { Sun, Moon, Monitor } from "lucide-react"
import type { Theme } from "@/contexts/ThemeProvider"

type ThemeToggleProps = {
  theme: Theme
  setTheme: (t: Theme) => void
}

const CYCLE: Record<Theme, Theme> = {
  light: "dark",
  dark: "system",
  system: "light",
}

const LABELS: Record<Theme, string> = {
  light: "light",
  dark: "dark",
  system: "system",
}

const ThemeIcon = ({ theme }: { theme: Theme }) => {
  if (theme === "light") return <Sun aria-hidden="true" className="size-4" />
  if (theme === "dark") return <Moon aria-hidden="true" className="size-4" />
  return <Monitor aria-hidden="true" className="size-4" />
}

const ThemeToggle = ({ theme, setTheme }: ThemeToggleProps) => {
  const next = CYCLE[theme]

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={`Switch to ${LABELS[next]} theme`}
      className="inline-flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring transition-colors"
    >
      <ThemeIcon theme={theme} />
      <span className="sr-only">{LABELS[theme]} theme</span>
    </button>
  )
}

export default ThemeToggle
