import { useEffect, useRef, useState } from "react"
import { getDojoSettings, updateDojoSettings, uploadDojoLogo } from "@/api/settings"
import type { DojoSettings } from "@/api/settings"
import { getSessionTypes, updateSessionTypeColour, createSessionType } from "@/api/sessions"
import type { SessionType } from "@/api/sessions"
import { useDojoSettings } from "@/contexts/DojoSettingsProvider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"

// ── WCAG luminance helpers ─────────────────────────────────────────────────────

// Parse a hex colour to [r, g, b] in 0–255
const hexToRgb = (hex: string): [number, number, number] | null => {
  const match = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
  if (!match) return null
  return [parseInt(match[1], 16), parseInt(match[2], 16), parseInt(match[3], 16)]
}

// Relative luminance per WCAG 2.1
const relativeLuminance = (r: number, g: number, b: number): number => {
  const toLinear = (c: number): number => {
    const s = c / 255
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)
}

// Returns true if the colour is too light (fails WCAG AA against white background)
const isTooLight = (hex: string): boolean => {
  const rgb = hexToRgb(hex)
  if (!rgb) return false
  const lum = relativeLuminance(...rgb)
  // Contrast ratio with white (L=1): (1 + 0.05) / (lum + 0.05)
  // AA requires >= 4.5 for normal text; flag if contrast < 4.5
  const contrastWithWhite = 1.05 / (lum + 0.05)
  return contrastWithWhite < 4.5
}

// ── Dojo Branding section ─────────────────────────────────────────────────────

type SaveStatus = "idle" | "saving" | "saved" | "error"

const DojoBrandingSection = () => {
  const { refresh: refreshContext } = useDojoSettings()
  const [settings, setSettings] = useState<DojoSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Dojo name
  const [dojoName, setDojoName] = useState("")
  const [nameSaveStatus, setNameSaveStatus] = useState<SaveStatus>("idle")
  const [nameError, setNameError] = useState<string | null>(null)

  // Primary colour
  const [primaryColour, setPrimaryColour] = useState("#4F46E5")
  const [colourSaveStatus, setColourSaveStatus] = useState<SaveStatus>("idle")
  const [colourError, setColourError] = useState<string | null>(null)

  // Logo upload
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [logoSaveStatus, setLogoSaveStatus] = useState<SaveStatus>("idle")
  const [logoError, setLogoError] = useState<string | null>(null)
  const [logoPreview, setLogoPreview] = useState<string | null>(null)

  useEffect(() => {
    getDojoSettings()
      .then((data) => {
        setSettings(data)
        setDojoName(data.dojo_name)
        setPrimaryColour(data.primary_colour)
        setLogoPreview(data.logo_url)
      })
      .catch((err: unknown) => {
        const msg =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : "Failed to load settings"
        setLoadError(msg)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const handleSaveName = async () => {
    setNameSaveStatus("saving")
    setNameError(null)
    try {
      const updated = await updateDojoSettings({ dojo_name: dojoName })
      setSettings(updated)
      refreshContext()
      setNameSaveStatus("saved")
      setTimeout(() => setNameSaveStatus("idle"), 2000)
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setNameError(msg)
      setNameSaveStatus("error")
    }
  }

  const handleSaveColour = async () => {
    setColourSaveStatus("saving")
    setColourError(null)
    try {
      const updated = await updateDojoSettings({ primary_colour: primaryColour })
      setSettings(updated)
      document.documentElement.style.setProperty("--primary", primaryColour)
      refreshContext()
      setColourSaveStatus("saved")
      setTimeout(() => setColourSaveStatus("idle"), 2000)
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setColourError(msg)
      setColourSaveStatus("error")
    }
  }

  const handleLogoChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    // Show local preview immediately
    const objectUrl = URL.createObjectURL(file)
    setLogoPreview(objectUrl)
    setLogoSaveStatus("saving")
    setLogoError(null)
    try {
      const result = await uploadDojoLogo(file)
      setLogoPreview(result.logo_url)
      refreshContext()
      setLogoSaveStatus("saved")
      setTimeout(() => setLogoSaveStatus("idle"), 2000)
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to upload logo"
      setLogoError(msg)
      setLogoSaveStatus("error")
    } finally {
      URL.revokeObjectURL(objectUrl)
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    )
  }

  if (loadError !== null || settings === null) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {loadError ?? "Failed to load settings"}
      </p>
    )
  }

  const colourWarning = isTooLight(primaryColour)

  return (
    <div className="space-y-8">
      {/* Dojo name */}
      <div className="space-y-2">
        <Label htmlFor="dojo-name">Dojo Name</Label>
        <div className="flex gap-2">
          <Input
            id="dojo-name"
            type="text"
            value={dojoName}
            onChange={(e) => setDojoName(e.target.value)}
            aria-label="Dojo name"
            className="flex-1"
          />
          <Button
            onClick={() => void handleSaveName()}
            disabled={nameSaveStatus === "saving" || dojoName.trim() === ""}
            aria-label="Save dojo name"
            className="min-h-[44px] shrink-0"
          >
            {nameSaveStatus === "saving"
              ? "Saving…"
              : nameSaveStatus === "saved"
              ? "Saved!"
              : "Save"}
          </Button>
        </div>
        {nameError !== null && (
          <p className="text-sm text-destructive" role="alert">
            {nameError}
          </p>
        )}
      </div>

      {/* Logo upload */}
      <div className="space-y-2">
        <Label htmlFor="logo-upload">Dojo Logo</Label>
        {logoPreview !== null && (
          <div className="mb-2">
            <img
              src={logoPreview}
              alt="Dojo logo preview"
              className="size-16 rounded-md object-cover border border-border"
            />
          </div>
        )}
        <div className="flex gap-2 items-center flex-wrap">
          <Input
            id="logo-upload"
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={(e) => void handleLogoChange(e)}
            aria-label="Upload dojo logo"
            className="flex-1 min-h-[44px] cursor-pointer file:cursor-pointer"
          />
          {logoSaveStatus === "saving" && (
            <span className="text-sm text-muted-foreground" aria-live="polite">
              Uploading…
            </span>
          )}
          {logoSaveStatus === "saved" && (
            <span className="text-sm text-green-600 dark:text-green-400" aria-live="polite">
              Uploaded!
            </span>
          )}
        </div>
        {logoError !== null && (
          <p className="text-sm text-destructive" role="alert">
            {logoError}
          </p>
        )}
      </div>

      {/* Primary colour */}
      <div className="space-y-2">
        <Label htmlFor="primary-colour">Primary Colour</Label>
        <div className="flex gap-2 items-center">
          <Input
            id="primary-colour"
            type="color"
            value={primaryColour}
            onChange={(e) => setPrimaryColour(e.target.value)}
            aria-label="Primary colour"
            className="h-11 w-16 cursor-pointer rounded-md border border-input p-1 shrink-0"
          />
          <span className="text-sm font-mono text-muted-foreground">{primaryColour}</span>
          <Button
            onClick={() => void handleSaveColour()}
            disabled={colourSaveStatus === "saving"}
            aria-label="Save primary colour"
            className="min-h-[44px] ml-auto shrink-0"
          >
            {colourSaveStatus === "saving"
              ? "Saving…"
              : colourSaveStatus === "saved"
              ? "Saved!"
              : "Save"}
          </Button>
        </div>
        {colourWarning && (
          <p className="text-sm text-amber-600 dark:text-amber-400" role="status">
            Warning: this colour may have insufficient contrast for WCAG 2.1 AA compliance when used as text on a light background.
          </p>
        )}
        {colourError !== null && (
          <p className="text-sm text-destructive" role="alert">
            {colourError}
          </p>
        )}
      </div>
    </div>
  )
}

// ── Session Types section ─────────────────────────────────────────────────────

const SessionTypesSection = () => {
  const [sessionTypes, setSessionTypes] = useState<SessionType[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveErrors, setSaveErrors] = useState<Record<string, string | null>>({})
  const [saveStatuses, setSaveStatuses] = useState<Record<string, SaveStatus>>({})
  const [newName, setNewName] = useState("")
  const [addStatus, setAddStatus] = useState<"idle" | "saving" | "error">("idle")
  const [addError, setAddError] = useState<string | null>(null)

  useEffect(() => {
    getSessionTypes()
      .then((types) => {
        setSessionTypes(types)
      })
      .catch((err: unknown) => {
        const msg =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : "Failed to load session types"
        setLoadError(msg)
      })
  }, [])

  const handleAddSessionType = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setAddStatus("saving")
    setAddError(null)
    try {
      const created = await createSessionType(name)
      setSessionTypes((prev) => (prev !== null ? [...prev, created] : [created]))
      setNewName("")
      setAddStatus("idle")
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to add session type"
      setAddError(msg)
      setAddStatus("error")
    }
  }

  const handleColourChange = async (id: string, colour: string) => {
    setSaveStatuses((prev) => ({ ...prev, [id]: "saving" }))
    setSaveErrors((prev) => ({ ...prev, [id]: null }))
    try {
      const updated = await updateSessionTypeColour(id, colour)
      setSessionTypes((prev) =>
        prev !== null ? prev.map((t) => (t.id === id ? updated : t)) : prev
      )
      setSaveStatuses((prev) => ({ ...prev, [id]: "saved" }))
      setTimeout(() => setSaveStatuses((prev) => ({ ...prev, [id]: "idle" })), 2000)
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setSaveErrors((prev) => ({ ...prev, [id]: msg }))
      setSaveStatuses((prev) => ({ ...prev, [id]: "error" }))
    }
  }

  if (sessionTypes === null && loadError === null) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-10 w-full" />
      </div>
    )
  }

  if (loadError !== null) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {loadError}
      </p>
    )
  }

  const addForm = (
    <form onSubmit={(e) => void handleAddSessionType(e)} className="flex gap-2 items-start pt-2">
      <Input
        value={newName}
        onChange={(e) => setNewName(e.target.value)}
        placeholder="New session type name"
        aria-label="New session type name"
        className="flex-1"
        disabled={addStatus === "saving"}
      />
      <Button type="submit" disabled={addStatus === "saving" || newName.trim() === ""}>
        {addStatus === "saving" ? "Adding…" : "Add"}
      </Button>
      {addError !== null && (
        <p className="text-sm text-destructive" role="alert">{addError}</p>
      )}
    </form>
  )

  if (sessionTypes !== null && sessionTypes.length === 0) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">No session types configured.</p>
        {addForm}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {(sessionTypes ?? []).map((t) => {
        const status = saveStatuses[t.id] ?? "idle"
        const error = saveErrors[t.id] ?? null
        return (
          <div key={t.id} className="space-y-1">
            <Label htmlFor={`session-type-colour-${t.id}`}>{t.name}</Label>
            <div className="flex gap-2 items-center">
              <Input
                id={`session-type-colour-${t.id}`}
                type="color"
                value={t.colour ?? "#4F46E5"}
                onChange={(e) => void handleColourChange(t.id, e.target.value)}
                aria-label={`Colour for ${t.name}`}
                className="h-11 w-16 cursor-pointer rounded-md border border-input p-1 shrink-0"
              />
              <span className="text-sm font-mono text-muted-foreground">
                {t.colour ?? "default"}
              </span>
              {status === "saving" && (
                <span className="text-sm text-muted-foreground ml-auto" aria-live="polite">
                  Saving…
                </span>
              )}
              {status === "saved" && (
                <span className="text-sm text-green-600 dark:text-green-400 ml-auto" aria-live="polite">
                  Saved!
                </span>
              )}
            </div>
            {error !== null && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
          </div>
        )
      })}
      {addForm}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

const AdminSettingsPage = () => (
  <div className="px-4 py-6 max-w-2xl mx-auto space-y-8">
    <h1 className="text-xl font-semibold">Admin Settings</h1>

    <section aria-labelledby="branding-heading">
      <h2
        id="branding-heading"
        className="text-base font-semibold mb-4 pb-2 border-b border-border"
      >
        Dojo Branding
      </h2>
      <DojoBrandingSection />
    </section>

    <section aria-labelledby="session-types-heading">
      <h2
        id="session-types-heading"
        className="text-base font-semibold mb-4 pb-2 border-b border-border"
      >
        Session Types
      </h2>
      <SessionTypesSection />
    </section>
  </div>
)

export default AdminSettingsPage
