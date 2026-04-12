import { createContext, useContext, useEffect, useState } from "react"
import type { ReactNode } from "react"
import { getDojoSettings } from "@/api/settings"

type DojoSettingsContextValue = {
  dojoName: string
  logoUrl: string | null
  primaryColour: string
}

const DEFAULTS: DojoSettingsContextValue = {
  dojoName: "My Dojo",
  logoUrl: null,
  primaryColour: "#4F46E5",
}

const DojoSettingsContext = createContext<DojoSettingsContextValue>(DEFAULTS)

type DojoSettingsProviderProps = { children: ReactNode }

export const DojoSettingsProvider = ({ children }: DojoSettingsProviderProps) => {
  const [settings, setSettings] = useState<DojoSettingsContextValue>(DEFAULTS)

  useEffect(() => {
    getDojoSettings()
      .then((data) => {
        const next: DojoSettingsContextValue = {
          dojoName: data.dojo_name,
          logoUrl: data.logo_url,
          primaryColour: data.primary_colour,
        }
        setSettings(next)
        document.documentElement.style.setProperty("--primary", data.primary_colour)
      })
      .catch((err: unknown) => {
        // Silently ignore 401/403 (non-admin users) and network errors — keep defaults
        const status = (err as { status?: number }).status
        if (status !== 401 && status !== 403) {
          // Non-auth errors: still use defaults, no action needed
        }
      })
  }, [])

  return (
    <DojoSettingsContext.Provider value={settings}>
      {children}
    </DojoSettingsContext.Provider>
  )
}

export const useDojoSettings = (): DojoSettingsContextValue => useContext(DojoSettingsContext)
