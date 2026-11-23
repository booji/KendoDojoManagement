import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { formatMemberName, getMyMember, updateMyMember } from "@/api/members"
import type { MemberResponse, MyMemberUpdateRequest } from "@/api/members"
import { isApiError, getMe, performPasskeyAdd, signOutEverywhere } from "@/api/auth"
import { errorMessage } from "@/api/client"
import type { AccountClaims } from "@/api/auth"
import { listPasskeys, renamePasskey, deletePasskey, getSecurityStatus } from "@/api/passkeys"
import type { PasskeyRecord } from "@/api/passkeys"
import {
  getRecoveryStatus,
  generateRecoveryCodes,
  regenerateRecoveryCodes,
} from "@/api/recovery"
import type { RecoveryStatus } from "@/api/recovery"
import { myFederationMemberships } from "@/api/federations"
import FederationMembershipsCard from "@/components/FederationMembershipsCard"
import { useThemeContext } from "@/contexts/ThemeProvider"
import type { Theme } from "@/contexts/ThemeProvider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Pencil, Trash2, Check, X, ShieldAlert } from "lucide-react"
import { formatMemberDate } from "@/lib/date"
import { PageHeader } from "@/components/ui/page-header"
import { resetTour } from "@/lib/tourSeen"

// ── Form state ────────────────────────────────────────────────────────────────

type FormState = {
  first_name: string
  surname: string
  display_name: string
  dob: string
  emergency_contact_name: string
  emergency_contact_phone: string
}

const EMPTY_FORM: FormState = {
  first_name: "",
  surname: "",
  display_name: "",
  dob: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
}

const memberToForm = (m: MemberResponse): FormState => ({
  first_name: m.first_name,
  surname: m.surname,
  display_name: m.display_name ?? "",
  dob: "",
  emergency_contact_name: m.emergency_contact_name ?? "",
  emergency_contact_phone: m.emergency_contact_phone ?? "",
})

// ── Profile summary (read-only) ───────────────────────────────────────────────

const Field = ({ label, value }: { label: string; value: string | null | undefined }) => (
  <div className="space-y-0.5">
    <dt className="text-xs text-muted-foreground">{label}</dt>
    <dd className="text-sm">{value ?? "—"}</dd>
  </div>
)

const ProfileSummary = ({
  member,
  onEdit,
}: {
  member: MemberResponse | null
  onEdit: () => void
}) => {
  if (member === null) {
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Personal Details</CardTitle>
          <Button variant="outline" size="sm" onClick={onEdit}>
            Set up profile
          </Button>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No profile set up yet.</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Personal Details</CardTitle>
          <p className="text-sm text-muted-foreground mt-0.5">{formatMemberName(member)}</p>
        </div>
        <Button variant="outline" size="sm" onClick={onEdit}>
          Edit
        </Button>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="First name" value={member.first_name} />
          <Field label="Surname" value={member.surname} />
          <Field label="Display name" value={member.display_name} />
          <Field label="Email" value={member.email} />
          <Field label="Date of birth" value={member.dob} />
          <Field label="Join date" value={member.join_date} />
          <Field label="Membership status" value={member.membership_status} />
          <Field label="Emergency contact" value={member.emergency_contact_name} />
          <Field label="Emergency contact phone" value={member.emergency_contact_phone} />
        </dl>
        {(member.is_coach || member.is_first_aider) && (
          <div className="flex gap-2 flex-wrap mt-4">
            {member.is_coach && <Badge>Coach</Badge>}
            {member.is_first_aider && <Badge>First aider</Badge>}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Passkey row ───────────────────────────────────────────────────────────────

type PasskeyRowProps = {
  passkey: PasskeyRecord
  isOnly: boolean
  onRename: (id: string, label: string) => Promise<void>
  onDelete: (id: string) => Promise<void>
}

const PasskeyRow = ({ passkey, isOnly, onRename, onDelete }: PasskeyRowProps) => {
  const [editing, setEditing] = useState(false)
  const [labelDraft, setLabelDraft] = useState(passkey.label)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [rowError, setRowError] = useState<string | null>(null)

  // Seed the draft when entering edit mode rather than syncing it in an effect —
  // the input only mounts while editing, so autoFocus handles the focus.
  const startEditing = () => {
    setLabelDraft(passkey.label)
    setEditing(true)
  }

  const handleSave = async () => {
    const trimmed = labelDraft.trim()
    if (!trimmed) return
    setSaving(true)
    setRowError(null)
    try {
      await onRename(passkey.id, trimmed)
      setEditing(false)
    } catch (err) {
      setRowError(isApiError(err) ? err.message : "Failed to rename passkey")
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    setRowError(null)
    try {
      await onDelete(passkey.id)
    } catch (err) {
      setRowError(isApiError(err) ? err.message : "Failed to delete passkey")
      setDeleting(false)
    }
  }

  return (
    <div className="flex flex-col gap-1 py-3 border-b last:border-b-0">
      <div className="flex items-center gap-2 flex-wrap">
        {editing ? (
          <>
            <Input
              autoFocus
              value={labelDraft}
              onChange={(e) => setLabelDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSave()
                if (e.key === "Escape") setEditing(false)
              }}
              className="h-8 text-sm flex-1 min-w-0"
              disabled={saving}
              aria-label="Passkey label"
            />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void handleSave()}
              disabled={saving || !labelDraft.trim()}
              aria-label="Save label"
              className="h-8 w-8 p-0"
            >
              <Check className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEditing(false)}
              disabled={saving}
              aria-label="Cancel rename"
              className="h-8 w-8 p-0"
            >
              <X className="h-4 w-4" />
            </Button>
          </>
        ) : (
          <>
            <span className="text-sm font-medium flex-1">{passkey.label}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={startEditing}
              aria-label="Rename passkey"
              className="h-8 w-8 p-0"
            >
              <Pencil className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void handleDelete()}
              disabled={isOnly || deleting}
              aria-label={isOnly ? "You need at least one passkey" : "Delete passkey"}
              title={isOnly ? "You need at least one passkey" : undefined}
              className="h-8 w-8 p-0 text-destructive hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>
      <div className="flex gap-4 flex-wrap">
        <span className="text-xs text-muted-foreground">
          Added {formatMemberDate(passkey.created_at)}
        </span>
        <span className="text-xs text-muted-foreground">
          Last used: {passkey.last_used_at !== null ? formatMemberDate(passkey.last_used_at) : "Never"}
        </span>
      </div>
      {rowError !== null && (
        <p className="text-xs text-destructive" role="alert">
          {rowError}
        </p>
      )}
    </div>
  )
}

// ── Sign out everywhere ───────────────────────────────────────────────────────

// Ends every sign-in of this Account, this device's included, then leaves for
// /login the way LogoutButton does. On failure nothing was signed out, so the
// user stays put with the error rather than landing on a login page while
// still signed in.
const SignOutEverywhere = () => {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // The safe choice takes focus, so Enter on open never signs anyone out.
  const cancelRef = useRef<HTMLButtonElement>(null)

  const close = () => {
    setOpen(false)
    setError(null)
  }

  const handleConfirm = async () => {
    setError(null)
    setWorking(true)
    try {
      await signOutEverywhere()
      navigate("/login", { replace: true })
    } catch (err) {
      setError(errorMessage(err, "Couldn't sign out everywhere"))
      setWorking(false)
    }
  }

  return (
    <div className="border-t pt-4">
      <p className="text-xs text-muted-foreground mb-2">Signed-in devices</p>
      <p className="text-sm mb-3">
        Sign out on every device where you are signed in, including this one.
      </p>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        Sign out everywhere
      </Button>

      <Dialog open={open} onOpenChange={(o) => { if (!o) close() }}>
        <DialogContent initialFocus={cancelRef}>
          <DialogHeader>
            <DialogTitle>Sign out everywhere?</DialogTitle>
            <DialogDescription>
              Every device signed in to your account, this one included, will need a
              passkey to sign in again.
            </DialogDescription>
          </DialogHeader>
          {error !== null && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button ref={cancelRef} variant="outline" onClick={close} disabled={working}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleConfirm()}
              disabled={working}
            >
              {working ? "Signing out…" : "Sign out everywhere"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ── Security card ─────────────────────────────────────────────────────────────

type PasskeyLoadState =
  | { status: "loading" }
  | { status: "ready"; passkeys: PasskeyRecord[]; passkeyCount: number; recovery: RecoveryStatus }
  | { status: "error"; message: string }

const SecurityCard = () => {
  const [state, setState] = useState<PasskeyLoadState>({ status: "loading" })
  const [addingPasskey, setAddingPasskey] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [nudgeOpen, setNudgeOpen] = useState(false)
  const [addingFromNudge, setAddingFromNudge] = useState(false)
  const [nudgeAddError, setNudgeAddError] = useState<string | null>(null)
  const [generatedCodes, setGeneratedCodes] = useState<string[] | null>(null)
  const [recoveryWorking, setRecoveryWorking] = useState(false)
  const [recoveryError, setRecoveryError] = useState<string | null>(null)

  const loadData = () => {
    Promise.all([listPasskeys(), getSecurityStatus(), getRecoveryStatus()])
      .then(([passkeys, status, recovery]) =>
        setState({ status: "ready", passkeys, passkeyCount: status.passkey_count, recovery })
      )
      .catch((err: unknown) => {
        setState({
          status: "error",
          message: isApiError(err) ? err.message : "Failed to load passkeys",
        })
      })
  }

  const handleGenerateCodes = async () => {
    setRecoveryWorking(true)
    setRecoveryError(null)
    try {
      const data = await generateRecoveryCodes()
      setGeneratedCodes(data.codes)
      const recovery = await getRecoveryStatus()
      setState((prev) => prev.status === "ready" ? { ...prev, recovery } : prev)
    } catch (err) {
      setRecoveryError(isApiError(err) ? err.message : "Failed to generate recovery codes")
    } finally {
      setRecoveryWorking(false)
    }
  }

  const handleRegenerateCodes = async () => {
    setRecoveryWorking(true)
    setRecoveryError(null)
    try {
      const data = await regenerateRecoveryCodes()
      setGeneratedCodes(data.codes)
      const recovery = await getRecoveryStatus()
      setState((prev) => prev.status === "ready" ? { ...prev, recovery } : prev)
    } catch (err) {
      setRecoveryError(isApiError(err) ? err.message : "Failed to regenerate recovery codes")
    } finally {
      setRecoveryWorking(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleRename = async (id: string, label: string) => {
    if (state.status !== "ready") return
    const prev = state.passkeys
    // Optimistic update
    setState({
      ...state,
      passkeys: prev.map((p) => (p.id === id ? { ...p, label } : p)),
    })
    try {
      const updated = await renamePasskey(id, label)
      setState({
        ...state,
        passkeys: prev.map((p) => (p.id === id ? updated : p)),
      })
    } catch (err) {
      // Revert
      setState({ ...state, passkeys: prev })
      throw err
    }
  }

  const handleDelete = async (id: string) => {
    if (state.status !== "ready") return
    const prev = state.passkeys
    const prevCount = state.passkeyCount
    // Optimistic removal
    setState({ ...state, passkeys: prev.filter((p) => p.id !== id), passkeyCount: prevCount - 1 })
    try {
      await deletePasskey(id)
    } catch (err) {
      // Revert
      setState({ ...state, passkeys: prev, passkeyCount: prevCount })
      throw err
    }
  }

  const handleAddPasskey = async () => {
    setAddError(null)
    setAddingPasskey(true)
    try {
      const result = await performPasskeyAdd()
      // Reload passkeys and security status
      loadData()
      if (result.show_nudge) {
        setNudgeOpen(true)
      }
    } catch (err) {
      setAddError(errorMessage(err, "Failed to register passkey"))
    } finally {
      setAddingPasskey(false)
    }
  }

  const handleNudgeAddPasskey = async () => {
    setNudgeAddError(null)
    setAddingFromNudge(true)
    try {
      await performPasskeyAdd()
      // Reload after adding
      loadData()
      setNudgeOpen(false)
    } catch (err) {
      setNudgeAddError(errorMessage(err, "Failed to register passkey"))
    } finally {
      setAddingFromNudge(false)
    }
  }

  return (
    <>
      <Card data-tour="security">
        <CardHeader>
          <CardTitle>Security</CardTitle>
        </CardHeader>
        <CardContent>
          {state.status === "loading" && (
            <div className="space-y-3">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          )}
          {state.status === "error" && (
            <p className="text-sm text-destructive" role="alert">
              {state.message}
            </p>
          )}
          {state.status === "ready" && (
            <div className="space-y-4">
              {state.passkeyCount === 1 && (
                <div
                  role="alert"
                  className="flex items-start gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3 text-sm"
                >
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="text-muted-foreground">
                    You have 1 passkey — consider adding a backup in case you lose access to
                    your device.
                  </span>
                </div>
              )}
              <div>
                <p className="text-xs text-muted-foreground mb-3">Passkeys</p>
                {state.passkeys.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No passkeys registered.</p>
                ) : (
                  <div>
                    {state.passkeys.map((pk) => (
                      <PasskeyRow
                        key={pk.id}
                        passkey={pk}
                        isOnly={state.passkeys.length === 1}
                        onRename={handleRename}
                        onDelete={handleDelete}
                      />
                    ))}
                  </div>
                )}
              </div>
              {addError !== null && (
                <p className="text-sm text-destructive" role="alert">
                  {addError}
                </p>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleAddPasskey()}
                disabled={addingPasskey}
              >
                {addingPasskey ? "Registering…" : "Add a passkey"}
              </Button>

              <div className="border-t pt-4">
                <p className="text-xs text-muted-foreground mb-2">Recovery codes</p>
                {state.recovery.has_set ? (
                  <p className="text-sm mb-3">
                    {state.recovery.unused_count} unused{" "}
                    {state.recovery.unused_count === 1 ? "code" : "codes"} remaining
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground mb-3">
                    No recovery codes generated
                  </p>
                )}
                {recoveryError !== null && (
                  <p className="text-sm text-destructive mb-2" role="alert">
                    {recoveryError}
                  </p>
                )}
                {state.recovery.has_set ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleRegenerateCodes()}
                    disabled={recoveryWorking}
                  >
                    {recoveryWorking ? "Working…" : "Regenerate"}
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void handleGenerateCodes()}
                    disabled={recoveryWorking}
                  >
                    {recoveryWorking ? "Working…" : "Generate codes"}
                  </Button>
                )}
              </div>
            </div>
          )}
          {/* Outside the load states: a failed passkey load must not hide it. */}
          {state.status !== "loading" && (
            <div className="mt-4">
              <SignOutEverywhere />
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={generatedCodes !== null} onOpenChange={(o) => { if (!o) setGeneratedCodes(null) }}>
        <DialogContent showCloseButton>
          <DialogHeader>
            <DialogTitle>Recovery codes</DialogTitle>
            <DialogDescription>
              Save these codes somewhere safe. Each code can only be used once.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md bg-muted p-4 font-mono text-sm space-y-1">
            {(generatedCodes ?? []).map((code) => (
              <p key={code}>{code}</p>
            ))}
          </div>
          <DialogFooter>
            <Button onClick={() => setGeneratedCodes(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={nudgeOpen} onOpenChange={setNudgeOpen}>
        <DialogContent showCloseButton>
          <DialogHeader>
            <DialogTitle>Add a backup passkey</DialogTitle>
            <DialogDescription>
              If you lose access to your only passkey, you won&apos;t be able to log in.
              Adding a second passkey on another device or password manager protects you
              from being locked out.
            </DialogDescription>
          </DialogHeader>
          {nudgeAddError !== null && (
            <p className="text-sm text-destructive" role="alert">
              {nudgeAddError}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setNudgeOpen(false)}
              disabled={addingFromNudge}
            >
              Maybe later
            </Button>
            <Button
              onClick={() => void handleNudgeAddPasskey()}
              disabled={addingFromNudge}
            >
              {addingFromNudge ? "Registering…" : "Add another passkey"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

type LoadState =
  | { status: "loading" }
  | { status: "ready"; member: MemberResponse | null; user: AccountClaims }
  | { status: "error"; message: string }

const SettingsPage = () => {
  const { theme, setTheme } = useThemeContext()
  const navigate = useNavigate()
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" })
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([getMyMember(), getMe()])
      .then(([member, user]) => {
        setLoadState({ status: "ready", member, user })
        setForm(member !== null ? memberToForm(member) : EMPTY_FORM)
      })
      .catch((err: unknown) => {
        setLoadState({
          status: "error",
          message: isApiError(err) ? err.message : "Failed to load your details",
        })
      })
  }, [])

  const handleEdit = () => {
    if (loadState.status === "ready") {
      setForm(loadState.member !== null ? memberToForm(loadState.member) : EMPTY_FORM)
    }
    setSaveError(null)
    setEditing(true)
  }

  const handleCancel = () => {
    setSaveError(null)
    setEditing(false)
  }

  const handleChange = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaveError(null)
    setSaving(true)

    const payload: MyMemberUpdateRequest = {
      first_name: form.first_name || undefined,
      surname: form.surname || undefined,
      display_name: form.display_name || null,
      emergency_contact_name: form.emergency_contact_name || null,
      emergency_contact_phone: form.emergency_contact_phone || null,
      ...(form.dob ? { dob: form.dob } : {}),
    }

    try {
      const updated = await updateMyMember(payload)
      setLoadState((prev) =>
        prev.status === "ready" ? { ...prev, member: updated } : prev
      )
      setEditing(false)
    } catch (err) {
      setSaveError(isApiError(err) ? err.message : "Failed to save your details")
    } finally {
      setSaving(false)
    }
  }

  if (loadState.status === "loading") {
    return (
      <div className="px-4 py-6 space-y-4">
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    )
  }

  if (loadState.status === "error") {
    return (
      <div className="px-4 py-6">
        <div className="mb-4">
          <PageHeader title="Settings" />
        </div>
        <p className="text-sm text-destructive" role="alert">
          {loadState.message}
        </p>
      </div>
    )
  }

  return (
    <div className="px-4 py-6 space-y-6">
      <PageHeader
        title="Settings"
        action={
          <Button
            variant="outline"
            onClick={() => {
              resetTour()
              navigate("/")
            }}
          >
            Take the tour
          </Button>
        }
      />

      {!editing ? (
        <ProfileSummary member={loadState.member} onEdit={handleEdit} />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Personal Details</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-5" aria-label="Personal details form">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <Label htmlFor="settings_first_name">First name</Label>
                  <Input
                    id="settings_first_name"
                    value={form.first_name}
                    onChange={(e) => handleChange("first_name", e.target.value)}
                    placeholder="Jane"
                    autoComplete="given-name"
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="settings_surname">Surname</Label>
                  <Input
                    id="settings_surname"
                    value={form.surname}
                    onChange={(e) => handleChange("surname", e.target.value)}
                    placeholder="Smith"
                    autoComplete="family-name"
                  />
                </div>

                <div className="space-y-1 sm:col-span-2">
                  <Label htmlFor="settings_display_name">Display name</Label>
                  <Input
                    id="settings_display_name"
                    value={form.display_name}
                    onChange={(e) => handleChange("display_name", e.target.value)}
                    placeholder="Optional — overrides first name + surname in lists"
                    autoComplete="nickname"
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="settings_dob">Date of birth</Label>
                  <Input
                    id="settings_dob"
                    type="date"
                    value={form.dob}
                    onChange={(e) => handleChange("dob", e.target.value)}
                    autoComplete="bday"
                  />
                  {form.dob === "" && (
                    <p className="text-xs text-muted-foreground">
                      Leave blank to keep your existing date of birth.
                    </p>
                  )}
                </div>

                <div className="space-y-1">
                  <Label htmlFor="settings_ec_name">Emergency contact name</Label>
                  <Input
                    id="settings_ec_name"
                    value={form.emergency_contact_name}
                    onChange={(e) => handleChange("emergency_contact_name", e.target.value)}
                    placeholder="Optional"
                    autoComplete="off"
                  />
                </div>

                <div className="space-y-1">
                  <Label htmlFor="settings_ec_phone">Emergency contact phone</Label>
                  <Input
                    id="settings_ec_phone"
                    type="tel"
                    value={form.emergency_contact_phone}
                    onChange={(e) => handleChange("emergency_contact_phone", e.target.value)}
                    placeholder="Optional"
                    autoComplete="off"
                  />
                </div>
              </div>

              {saveError !== null && (
                <p className="text-sm text-destructive" role="alert">
                  {saveError}
                </p>
              )}

              <div className="flex justify-end gap-3 pt-1">
                <Button
                  type="button"
                  variant="outline"
                  size="lg"
                  onClick={handleCancel}
                  disabled={saving}
                  className="w-full sm:w-auto"
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  size="lg"
                  disabled={saving}
                  className="w-full sm:w-auto"
                >
                  {saving ? "Saving…" : "Save changes"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <h2 className="font-heading text-base leading-snug font-medium">Appearance</h2>
        </CardHeader>
        <CardContent>
          <div role="group" aria-label="Theme" className="flex gap-2 flex-wrap">
            {(["light", "system", "dark"] as const).map((t: Theme) => (
              <button
                key={t}
                type="button"
                onClick={() => setTheme(t)}
                aria-pressed={theme === t}
                className={[
                  "rounded-md px-4 py-2 text-sm font-medium border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  theme === t
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-background text-foreground border-border hover:bg-accent hover:text-accent-foreground",
                ].join(" ")}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <SecurityCard />

      <FederationMembershipsCard store={myFederationMemberships} />
    </div>
  )
}

export default SettingsPage
