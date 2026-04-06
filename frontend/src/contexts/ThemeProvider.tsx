import { createContext, useContext, useState, useEffect, useCallback } from "react"
import type { ReactNode } from "react"
import { getPreferences, updatePreferences } from "@/api/preferences"
import type { Theme } from "@/api/preferences"

// Re-export Theme so consumers don't need to import from two places
export type { Theme }

const STORAGE_KEY = "theme"

const resolveIsDark = (theme: Theme): boolean => {
  if (theme === "dark") return true
  if (theme === "light") return false
  return window.matchMedia("(prefers-color-scheme: dark)").matches
}

const applyThemeClass = (theme: Theme): void => {
  if (resolveIsDark(theme)) {
    document.documentElement.classList.add("dark")
  } else {
    document.documentElement.classList.remove("dark")
  }
}

type ThemeContextValue = {
  theme: Theme
  setTheme: (t: Theme) => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

type ThemeProviderProps = { children: ReactNode }

export const ThemeProvider = ({ children }: ThemeProviderProps) => {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? "system"
  )

  // Apply theme class whenever theme state changes
  useEffect(() => {
    applyThemeClass(theme)
  }, [theme])

  // Listen for OS colour-scheme changes when theme is "system"
  useEffect(() => {
    if (theme !== "system") return
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const handler = () => applyThemeClass("system")
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [theme])

  // On mount: reconcile with server preferences (silently ignore 401)
  useEffect(() => {
    getPreferences()
      .then((prefs) => {
        const local = (localStorage.getItem(STORAGE_KEY) as Theme | null) ?? "system"
        if (prefs.theme !== local) {
          localStorage.setItem(STORAGE_KEY, prefs.theme)
          setThemeState(prefs.theme)
        }
      })
      .catch(() => {
        // Not authenticated or network error — keep localStorage value
      })
  }, [])

  const setTheme = useCallback((t: Theme): void => {
    localStorage.setItem(STORAGE_KEY, t)
    setThemeState(t)
    applyThemeClass(t)
    // Fire-and-forget — persist to server; ignore errors silently
    updatePreferences(t).catch(() => undefined)
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export const useThemeContext = (): ThemeContextValue => {
  const ctx = useContext(ThemeContext)
  if (ctx === null) {
    throw new Error("useThemeContext must be used within a ThemeProvider")
  }
  return ctx
}
