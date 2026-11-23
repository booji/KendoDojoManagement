import { useEffect, useRef, useState } from "react"
import {
  getDojoSettings,
  updateDojoSettings,
  uploadDojoLogo,
  uploadDojoBackground,
} from "@/api/settings"
import type { DojoSettings } from "@/api/settings"
import { useDojoSettings } from "@/contexts/DojoSettingsProvider"
import { applyPrimaryColour } from "@/lib/primaryColour"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Section } from "@/components/ui/section"
import { Switch } from "@/components/ui/switch"

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

  // Login screen background upload
  const backgroundFileInputRef = useRef<HTMLInputElement>(null)
  const [backgroundSaveStatus, setBackgroundSaveStatus] = useState<SaveStatus>("idle")
  const [backgroundError, setBackgroundError] = useState<string | null>(null)
  const [backgroundPreview, setBackgroundPreview] = useState<string | null>(null)

  // Login screen toggles (auto-save)
  const [showBackground, setShowBackground] = useState(false)
  const [showLogo, setShowLogo] = useState(false)
  const [showName, setShowName] = useState(false)
  const [toggleError, setToggleError] = useState<string | null>(null)

  useEffect(() => {
    getDojoSettings()
      .then((data) => {
        setSettings(data)
        setDojoName(data.dojo_name)
        setPrimaryColour(data.primary_colour)
        setLogoPreview(data.logo_url)
        setBackgroundPreview(data.background_image_url)
        setShowBackground(data.login_show_background)
        setShowLogo(data.login_show_logo)
        setShowName(data.login_show_name)
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
      applyPrimaryColour(primaryColour)
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

  const handleBackgroundChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const objectUrl = URL.createObjectURL(file)
    setBackgroundPreview(objectUrl)
    setBackgroundSaveStatus("saving")
    setBackgroundError(null)
    try {
      const result = await uploadDojoBackground(file)
      setBackgroundPreview(result.background_image_url)
      refreshContext()
      setBackgroundSaveStatus("saved")
      setTimeout(() => setBackgroundSaveStatus("idle"), 2000)
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to upload background"
      setBackgroundError(msg)
      setBackgroundSaveStatus("error")
    } finally {
      URL.revokeObjectURL(objectUrl)
    }
  }

  const handleRemoveBackground = async () => {
    setBackgroundSaveStatus("saving")
    setBackgroundError(null)
    try {
      await updateDojoSettings({ background_image_url: null })
      setBackgroundPreview(null)
      refreshContext()
      setBackgroundSaveStatus("saved")
      setTimeout(() => setBackgroundSaveStatus("idle"), 2000)
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to remove background"
      setBackgroundError(msg)
      setBackgroundSaveStatus("error")
    }
  }

  const handleToggleShowBackground = async (checked: boolean) => {
    setShowBackground(checked)
    setToggleError(null)
    try {
      await updateDojoSettings({ login_show_background: checked })
      refreshContext()
    } catch (err: unknown) {
      setShowBackground(!checked)
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setToggleError(msg)
    }
  }

  const handleToggleShowLogo = async (checked: boolean) => {
    setShowLogo(checked)
    setToggleError(null)
    try {
      await updateDojoSettings({ login_show_logo: checked })
      refreshContext()
    } catch (err: unknown) {
      setShowLogo(!checked)
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setToggleError(msg)
    }
  }

  const handleToggleShowName = async (checked: boolean) => {
    setShowName(checked)
    setToggleError(null)
    try {
      await updateDojoSettings({ login_show_name: checked })
      refreshContext()
    } catch (err: unknown) {
      setShowName(!checked)
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setToggleError(msg)
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
        <p className="text-sm text-muted-foreground">
          Choose a brand hue; the app derives accessible light- and dark-theme
          shades from it automatically, so any colour is fine.
        </p>
        {colourError !== null && (
          <p className="text-sm text-destructive" role="alert">
            {colourError}
          </p>
        )}
      </div>

      {/* Login Screen */}
      <div className="space-y-4 border-t border-border pt-6">
        <h3 className="text-sm font-semibold">Login Screen</h3>

        {/* Background image upload */}
        <div className="space-y-2">
          <Label htmlFor="background-upload">Background Image</Label>
          {backgroundPreview !== null && (
            <div className="mb-2">
              <img
                src={backgroundPreview}
                alt="Login background preview"
                className="h-24 w-full max-w-sm rounded-md object-cover border border-border"
              />
            </div>
          )}
          <div className="flex gap-2 items-center flex-wrap">
            <Input
              id="background-upload"
              ref={backgroundFileInputRef}
              type="file"
              accept="image/*"
              onChange={(e) => void handleBackgroundChange(e)}
              aria-label="Upload login screen background"
              className="flex-1 min-h-[44px] cursor-pointer file:cursor-pointer"
            />
            {backgroundPreview !== null && (
              <Button
                type="button"
                variant="outline"
                onClick={() => void handleRemoveBackground()}
                disabled={backgroundSaveStatus === "saving"}
                aria-label="Remove login screen background"
                className="min-h-[44px] shrink-0"
              >
                Remove
              </Button>
            )}
            {backgroundSaveStatus === "saving" && (
              <span className="text-sm text-muted-foreground" aria-live="polite">
                Saving…
              </span>
            )}
            {backgroundSaveStatus === "saved" && (
              <span className="text-sm text-green-600 dark:text-green-400" aria-live="polite">
                Saved!
              </span>
            )}
          </div>
          {backgroundError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {backgroundError}
            </p>
          )}
        </div>

        {/* Auto-saving visibility toggles */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Switch
              id="login-show-background"
              checked={showBackground}
              onCheckedChange={(v) => void handleToggleShowBackground(v)}
            />
            <Label htmlFor="login-show-background">Show background image on login screen</Label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="login-show-logo"
              checked={showLogo}
              onCheckedChange={(v) => void handleToggleShowLogo(v)}
            />
            <Label htmlFor="login-show-logo">Show logo on login screen</Label>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="login-show-name"
              checked={showName}
              onCheckedChange={(v) => void handleToggleShowName(v)}
            />
            <Label htmlFor="login-show-name">Show dojo name on login screen</Label>
          </div>
          {toggleError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {toggleError}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Check-in Window section ───────────────────────────────────────────────────

const MAX_WINDOW_MINUTES = 1440

// Validates a check-in window field: must be a non-negative integer <= 1440.
const validateWindowMinutes = (value: string): string | null => {
  if (value.trim() === "") return "Required"
  const n = Number(value)
  if (!Number.isInteger(n) || n < 0) return "Must be a non-negative whole number"
  if (n > MAX_WINDOW_MINUTES) return `Must be ${MAX_WINDOW_MINUTES} or less`
  return null
}

const CheckinWindowSection = () => {
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [beforeMinutes, setBeforeMinutes] = useState("60")
  const [afterMinutes, setAfterMinutes] = useState("120")
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle")
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    getDojoSettings()
      .then((data) => {
        setBeforeMinutes(String(data.checkin_window_before_minutes))
        setAfterMinutes(String(data.checkin_window_after_minutes))
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

  const beforeError = validateWindowMinutes(beforeMinutes)
  const afterError = validateWindowMinutes(afterMinutes)

  const handleSave = async () => {
    if (beforeError !== null || afterError !== null) return
    setSaveStatus("saving")
    setSaveError(null)
    try {
      await updateDojoSettings({
        checkin_window_before_minutes: Number(beforeMinutes),
        checkin_window_after_minutes: Number(afterMinutes),
      })
      setSaveStatus("saved")
      setTimeout(() => setSaveStatus("idle"), 2000)
    } catch (err: unknown) {
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setSaveError(msg)
      setSaveStatus("error")
    }
  }

  if (loading) {
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

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Controls how early or late members can check in to a session by default.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="checkin-window-before">Opens before session (minutes)</Label>
          <Input
            id="checkin-window-before"
            type="number"
            min={0}
            max={MAX_WINDOW_MINUTES}
            value={beforeMinutes}
            onChange={(e) => setBeforeMinutes(e.target.value)}
            aria-label="Check-in window opens before session, in minutes"
          />
          {beforeError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {beforeError}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="checkin-window-after">Closes after session starts (minutes)</Label>
          <Input
            id="checkin-window-after"
            type="number"
            min={0}
            max={MAX_WINDOW_MINUTES}
            value={afterMinutes}
            onChange={(e) => setAfterMinutes(e.target.value)}
            aria-label="Check-in window closes after session starts, in minutes"
          />
          {afterError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {afterError}
            </p>
          )}
        </div>
      </div>
      <div className="flex justify-end">
        <Button
          onClick={() => void handleSave()}
          disabled={saveStatus === "saving" || beforeError !== null || afterError !== null}
          aria-label="Save check-in window"
          className="min-h-[44px]"
        >
          {saveStatus === "saving" ? "Saving…" : saveStatus === "saved" ? "Saved!" : "Save"}
        </Button>
      </div>
      {saveError !== null && (
        <p className="text-sm text-destructive" role="alert">
          {saveError}
        </p>
      )}
    </div>
  )
}
// ── Page ──────────────────────────────────────────────────────────────────────

const AdminGeneralSettingsPage = () => (
  <>
    <Section heading="Dojo Branding">
      <DojoBrandingSection />
    </Section>

    <Section heading="Check-in Window">
      <CheckinWindowSection />
    </Section>
  </>
)

export default AdminGeneralSettingsPage
