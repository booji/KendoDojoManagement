import { createContext, useCallback, useContext, useEffect, useState } from "react"
import type { ReactNode } from "react"
import { getDojoSettings } from "@/api/settings"
import { applyPrimaryColour } from "@/lib/primaryColour"

type DojoSettingsContextValue = {
  dojoName: string
  logoUrl: string | null
  primaryColour: string
  refresh: () => void
}

const DEFAULTS: DojoSettingsContextValue = {
  dojoName: "My Dojo",
  logoUrl: null,
  primaryColour: "#4F46E5",
  refresh: () => undefined,
}

const DojoSettingsContext = createContext<DojoSettingsContextValue>(DEFAULTS)

type DojoSettingsProviderProps = { children: ReactNode }

export const DojoSettingsProvider = ({ children }: DojoSettingsProviderProps) => {
  const [dojoName, setDojoName] = useState(DEFAULTS.dojoName)
  const [logoUrl, setLogoUrl] = useState<string | null>(DEFAULTS.logoUrl)
  const [primaryColour, setPrimaryColour] = useState(DEFAULTS.primaryColour)

  const applySettings = useCallback((data: { dojo_name: string; logo_url: string | null; primary_colour: string }) => {
    setDojoName(data.dojo_name)
    setLogoUrl(data.logo_url)
    setPrimaryColour(data.primary_colour)
    applyPrimaryColour(data.primary_colour)
  }, [])

  const refresh = useCallback(() => {
    getDojoSettings()
      .then(applySettings)
      .catch(() => {
        // Silently ignore 401/403 (non-member users) and network errors
      })
  }, [applySettings])

  useEffect(() => {
    refresh()
  }, [refresh])

  return (
    <DojoSettingsContext.Provider value={{ dojoName, logoUrl, primaryColour, refresh }}>
      {children}
    </DojoSettingsContext.Provider>
  )
}

export const useDojoSettings = (): DojoSettingsContextValue => useContext(DojoSettingsContext)
