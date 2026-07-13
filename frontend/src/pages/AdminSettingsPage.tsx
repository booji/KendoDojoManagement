import { useCallback, useEffect, useRef, useState } from "react"
import {
  getDojoSettings,
  updateDojoSettings,
  uploadDojoLogo,
  uploadDojoBackground,
} from "@/api/settings"
import type { DojoSettings } from "@/api/settings"
import {
  getSessionTypes,
  updateSessionTypeColour,
  createSessionType,
  deleteSessionType,
} from "@/api/sessions"
import type { SessionType } from "@/api/sessions"
import { useDojoSettings } from "@/contexts/DojoSettingsProvider"
import {
  listFederations,
  createFederation,
  updateFederation,
  deactivateFederation,
} from "@/api/federations"
import type { FederationResponse, FederationCreateRequest } from "@/api/federations"
import { isApiError } from "@/api/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { PageHeader } from "@/components/ui/page-header"
import { Section } from "@/components/ui/section"
import { EmptyState } from "@/components/ui/empty-state"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Pencil, Pin, Trash2 } from "lucide-react"

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

// ── Session Types section ─────────────────────────────────────────────────────

export const SessionTypesSection = () => {
  const [sessionTypes, setSessionTypes] = useState<SessionType[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveErrors, setSaveErrors] = useState<Record<string, string | null>>({})
  const [saveStatuses, setSaveStatuses] = useState<Record<string, SaveStatus>>({})
  const [newName, setNewName] = useState("")
  const [addStatus, setAddStatus] = useState<"idle" | "saving" | "error">("idle")
  const [addError, setAddError] = useState<string | null>(null)

  // Deletion: which type is pending confirmation, plus in-flight/error state.
  const [pendingDelete, setPendingDelete] = useState<SessionType | null>(null)
  const [deleteStatus, setDeleteStatus] = useState<"idle" | "deleting">("idle")
  const [deleteError, setDeleteError] = useState<string | null>(null)

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

  const handleConfirmDelete = async () => {
    if (pendingDelete === null) return
    const target = pendingDelete
    setDeleteStatus("deleting")
    setDeleteError(null)
    try {
      await deleteSessionType(target.id)
      setSessionTypes((prev) =>
        prev !== null ? prev.filter((t) => t.id !== target.id) : prev
      )
      setPendingDelete(null)
    } catch (err: unknown) {
      // On 409 the type is still referenced — keep it in the list and show why.
      const msg =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to delete session type"
      setDeleteError(msg)
    } finally {
      setDeleteStatus("idle")
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
        <EmptyState message="No session types configured." />
        {addForm}
      </div>
    )
  }

  return (
    <>
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
              <div className="ml-auto flex items-center gap-2">
                {status === "saving" && (
                  <span className="text-sm text-muted-foreground" aria-live="polite">
                    Saving…
                  </span>
                )}
                {status === "saved" && (
                  <span className="text-sm text-green-600 dark:text-green-400" aria-live="polite">
                    Saved!
                  </span>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-9 w-9 p-0 text-muted-foreground hover:text-destructive"
                  onClick={() => {
                    setDeleteError(null)
                    setPendingDelete(t)
                  }}
                  aria-label={`Delete ${t.name}`}
                >
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
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

      <Dialog
        open={pendingDelete !== null}
        onOpenChange={(o) => {
          if (!o && deleteStatus !== "deleting") {
            setPendingDelete(null)
            setDeleteError(null)
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete session type</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            Delete <span className="font-medium text-foreground">{pendingDelete?.name}</span>?
            This cannot be undone.
          </p>
          {deleteError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {deleteError}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setPendingDelete(null)
                setDeleteError(null)
              }}
              disabled={deleteStatus === "deleting"}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleConfirmDelete()}
              disabled={deleteStatus === "deleting"}
            >
              {deleteStatus === "deleting" ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ── Federation Catalogue ──────────────────────────────────────────────────────

const FED_TYPES = ["National", "Regional Body", "Global Body", "Special Status"] as const
const FED_GROUPINGS = ["Africa", "Asia", "Europe", "Oceania", "Pan-Am", "Global"] as const

type CatalogueFedForm = {
  name: string
  abbreviation: string
  iso_code: string
  website: string
  continental_grouping: string
  type: string
  is_pinned: boolean
  is_active: boolean
}

const EMPTY_CAT_FORM: CatalogueFedForm = {
  name: "",
  abbreviation: "",
  iso_code: "",
  website: "",
  continental_grouping: "",
  type: "",
  is_pinned: false,
  is_active: true,
}

const isValidUrl = (s: string): boolean => {
  if (!s) return true
  try {
    const u = new URL(s)
    return u.protocol === "https:" || u.protocol === "http:"
  } catch {
    return false
  }
}

type CatalogueLoadState =
  | { status: "loading" }
  | { status: "ready"; federations: FederationResponse[] }
  | { status: "error"; message: string }

const AdminFederationCatalogue = () => {
  const [catState, setCatState] = useState<CatalogueLoadState>({ status: "loading" })
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [typeFilter, setTypeFilter] = useState("")
  const [groupingFilter, setGroupingFilter] = useState("")

  const [modalOpen, setModalOpen] = useState(false)
  const [editingFed, setEditingFed] = useState<FederationResponse | null>(null)
  const [catForm, setCatForm] = useState<CatalogueFedForm>(EMPTY_CAT_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [formSaving, setFormSaving] = useState(false)

  const [toggleError, setToggleError] = useState<string | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  const loadFederations = useCallback(() => {
    setCatState({ status: "loading" })
    listFederations({
      search: debouncedSearch || undefined,
      type: typeFilter || undefined,
      continental_grouping: groupingFilter || undefined,
    })
      .then((feds) => setCatState({ status: "ready", federations: feds }))
      .catch((err: unknown) => {
        setCatState({
          status: "error",
          message: isApiError(err) ? err.message : "Failed to load federations",
        })
      })
  }, [debouncedSearch, typeFilter, groupingFilter])

  useEffect(() => {
    loadFederations()
  }, [loadFederations])

  const openAdd = () => {
    setCatForm(EMPTY_CAT_FORM)
    setEditingFed(null)
    setFormError(null)
    setModalOpen(true)
  }

  const openEdit = (fed: FederationResponse) => {
    setCatForm({
      name: fed.name,
      abbreviation: fed.abbreviation ?? "",
      iso_code: fed.iso_code ?? "",
      website: fed.website ?? "",
      continental_grouping: fed.continental_grouping ?? "",
      type: fed.type ?? "",
      is_pinned: fed.is_pinned,
      is_active: fed.is_active,
    })
    setEditingFed(fed)
    setFormError(null)
    setModalOpen(true)
  }

  const handleFormSave = async () => {
    if (!catForm.name.trim()) {
      setFormError("Name is required")
      return
    }
    if (!isValidUrl(catForm.website)) {
      setFormError("Website must be a valid URL (e.g. https://example.org)")
      return
    }
    setFormSaving(true)
    setFormError(null)
    try {
      const body: FederationCreateRequest = {
        name: catForm.name.trim(),
        abbreviation: catForm.abbreviation.trim() || undefined,
        iso_code: catForm.iso_code.trim() || undefined,
        website: catForm.website.trim() || undefined,
        continental_grouping: catForm.continental_grouping || undefined,
        type: catForm.type || undefined,
        is_pinned: catForm.is_pinned,
        is_active: catForm.is_active,
      }
      if (editingFed !== null) {
        await updateFederation(editingFed.id, body)
      } else {
        await createFederation(body)
      }
      setModalOpen(false)
      loadFederations()
    } catch (err) {
      setFormError(isApiError(err) ? err.message : "Failed to save")
    } finally {
      setFormSaving(false)
    }
  }

  const handleTogglePin = async (fed: FederationResponse) => {
    setToggleError(null)
    try {
      await updateFederation(fed.id, { is_pinned: !fed.is_pinned })
      loadFederations()
    } catch (err) {
      setToggleError(isApiError(err) ? err.message : "Failed to update pin")
    }
  }

  const handleToggleActive = async (fed: FederationResponse) => {
    setToggleError(null)
    try {
      if (fed.is_active) {
        await deactivateFederation(fed.id)
      } else {
        await updateFederation(fed.id, { is_active: true })
      }
      loadFederations()
    } catch (err) {
      setToggleError(isApiError(err) ? err.message : "Failed to update status")
    }
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 flex-wrap">
          <CardTitle>Federation Catalogue</CardTitle>
          <Button variant="outline" size="sm" onClick={openAdd}>
            Add federation
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Input
              placeholder="Search by name or abbreviation…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 min-w-48"
              aria-label="Search federations"
            />
            <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v ?? "")}>
              <SelectTrigger className="w-44" aria-label="Filter by type">
                <SelectValue placeholder="All types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All types</SelectItem>
                {FED_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>{t}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={groupingFilter} onValueChange={(v) => setGroupingFilter(v ?? "")}>
              <SelectTrigger className="w-44" aria-label="Filter by region">
                <SelectValue placeholder="All regions" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">All regions</SelectItem>
                {FED_GROUPINGS.map((g) => (
                  <SelectItem key={g} value={g}>{g}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {toggleError !== null && (
            <p className="text-sm text-destructive" role="alert">{toggleError}</p>
          )}

          {catState.status === "loading" && (
            <div className="space-y-2">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          )}

          {catState.status === "error" && (
            <p className="text-sm text-destructive" role="alert">{catState.message}</p>
          )}

          {catState.status === "ready" && (
            catState.federations.length === 0 ? (
              <EmptyState message="No federations found." />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Abbr.</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Region</TableHead>
                      <TableHead>Website</TableHead>
                      <TableHead className="text-center">Pinned</TableHead>
                      <TableHead className="text-center">Active</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {catState.federations.map((fed) => (
                      <TableRow
                        key={fed.id}
                        className={!fed.is_active ? "opacity-50" : undefined}
                      >
                        <TableCell className="font-medium max-w-48 truncate">
                          <span className="flex items-center gap-1.5">
                            {fed.name}
                            {!fed.is_active && (
                              <Badge variant="secondary" className="text-xs">Inactive</Badge>
                            )}
                          </span>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {fed.abbreviation ?? "—"}
                        </TableCell>
                        <TableCell>{fed.type ?? "—"}</TableCell>
                        <TableCell>{fed.continental_grouping ?? "—"}</TableCell>
                        <TableCell className="max-w-40">
                          {fed.website !== null && /^https?:\/\//i.test(fed.website) ? (
                            <a
                              href={fed.website}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-primary underline-offset-4 hover:underline truncate block max-w-36"
                              title={fed.website}
                            >
                              {fed.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}
                            </a>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-center">
                          <button
                            type="button"
                            onClick={() => void handleTogglePin(fed)}
                            aria-label={fed.is_pinned ? "Unpin federation" : "Pin federation"}
                            className={[
                              "inline-flex items-center justify-center rounded p-1 transition-colors hover:bg-accent",
                              fed.is_pinned
                                ? "text-primary"
                                : "text-muted-foreground",
                            ].join(" ")}
                          >
                            <Pin className="h-4 w-4" aria-hidden="true" />
                          </button>
                        </TableCell>
                        <TableCell className="text-center">
                          <Switch
                            checked={fed.is_active}
                            onCheckedChange={() => void handleToggleActive(fed)}
                            aria-label={fed.is_active ? "Deactivate federation" : "Reactivate federation"}
                          />
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0"
                            onClick={() => openEdit(fed)}
                            aria-label={`Edit ${fed.name}`}
                          >
                            <Pencil className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )
          )}
        </CardContent>
      </Card>

      <Dialog open={modalOpen} onOpenChange={(o) => { if (!o) setModalOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingFed !== null ? "Edit federation" : "Add federation"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            <div className="space-y-1">
              <Label htmlFor="cat_fed_name">Name <span className="text-destructive">*</span></Label>
              <Input
                id="cat_fed_name"
                value={catForm.name}
                onChange={(e) => setCatForm((p) => ({ ...p, name: e.target.value }))}
                placeholder="e.g. British Kendo Association"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="cat_fed_abbr">Abbreviation</Label>
                <Input
                  id="cat_fed_abbr"
                  value={catForm.abbreviation}
                  onChange={(e) => setCatForm((p) => ({ ...p, abbreviation: e.target.value }))}
                  placeholder="e.g. BKA"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="cat_fed_iso">ISO code</Label>
                <Input
                  id="cat_fed_iso"
                  value={catForm.iso_code}
                  onChange={(e) => setCatForm((p) => ({ ...p, iso_code: e.target.value }))}
                  placeholder="e.g. GB"
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="cat_fed_website">Website</Label>
              <Input
                id="cat_fed_website"
                type="url"
                value={catForm.website}
                onChange={(e) => setCatForm((p) => ({ ...p, website: e.target.value }))}
                placeholder="https://example.org"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="cat_fed_type">Type</Label>
                <Select
                  value={catForm.type}
                  onValueChange={(v) => setCatForm((p) => ({ ...p, type: v ?? "" }))}
                >
                  <SelectTrigger id="cat_fed_type" className="w-full">
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">None</SelectItem>
                    {FED_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>{t}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="cat_fed_grouping">Region</Label>
                <Select
                  value={catForm.continental_grouping}
                  onValueChange={(v) => setCatForm((p) => ({ ...p, continental_grouping: v ?? "" }))}
                >
                  <SelectTrigger id="cat_fed_grouping" className="w-full">
                    <SelectValue placeholder="Select region" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">None</SelectItem>
                    {FED_GROUPINGS.map((g) => (
                      <SelectItem key={g} value={g}>{g}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <Switch
                  id="cat_fed_pinned"
                  checked={catForm.is_pinned}
                  onCheckedChange={(v) => setCatForm((p) => ({ ...p, is_pinned: v }))}
                />
                <Label htmlFor="cat_fed_pinned">Pinned</Label>
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  id="cat_fed_active"
                  checked={catForm.is_active}
                  onCheckedChange={(v) => setCatForm((p) => ({ ...p, is_active: v }))}
                />
                <Label htmlFor="cat_fed_active">Active</Label>
              </div>
            </div>
            {formError !== null && (
              <p className="text-sm text-destructive" role="alert">{formError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setModalOpen(false)}
              disabled={formSaving}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleFormSave()}
              disabled={formSaving || !catForm.name.trim()}
            >
              {formSaving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

const AdminSettingsPage = () => (
  <div className="px-4 py-6 space-y-8">
    <PageHeader title="Admin Settings" />

    <Section heading="Dojo Branding">
      <DojoBrandingSection />
    </Section>

    <Section heading="Check-in Window">
      <CheckinWindowSection />
    </Section>

    <Section heading="Session Types">
      <SessionTypesSection />
    </Section>

    <Section heading="Federations">
      <AdminFederationCatalogue />
    </Section>
  </div>
)

export default AdminSettingsPage
