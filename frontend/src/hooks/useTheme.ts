import { useState, useEffect, useCallback } from "react"
import { updateTheme } from "@/api/auth"

export type Theme = "light" | "dark" | "system"

const STORAGE_KEY = "theme"

const resolveIsDark = (theme: Theme): boolean => {
  if (theme === "dark") return true
  if (theme === "light") return false
  return window.matchMedia("(prefers-color-scheme: dark)").matches
}

const applyTheme = (theme: Theme): void => {
  if (resolveIsDark(theme)) {
    document.documentElement.classList.add("dark")
  } else {
    document.documentElement.classList.remove("dark")
  }
}

export const useTheme = (): { theme: Theme; setTheme: (t: Theme) => void } => {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? "system"
  )

  // Apply theme to DOM on mount and whenever theme changes
  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  // Listen for OS colour-scheme changes when theme is "system"
  useEffect(() => {
    if (theme !== "system") return

    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const handler = () => applyTheme("system")
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [theme])

  const setTheme = useCallback((t: Theme): void => {
    localStorage.setItem(STORAGE_KEY, t)
    setThemeState(t)
    applyTheme(t)
    // Fire-and-forget — persist to server; ignore errors silently
    updateTheme(t).catch(() => undefined)
  }, [])

  return { theme, setTheme }
}
