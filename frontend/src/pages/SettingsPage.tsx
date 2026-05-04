import { useCallback, useEffect, useRef, useState } from "react"
import { getMyMember, updateMyMember } from "@/api/members"
import type { MemberResponse, MyMemberUpdateRequest } from "@/api/members"
import { isApiError, getMe, performPasskeyRegistration } from "@/api/auth"
import type { UserClaims } from "@/api/auth"
import { listPasskeys, renamePasskey, deletePasskey, getSecurityStatus } from "@/api/passkeys"
import type { PasskeyRecord } from "@/api/passkeys"
import {
  listFederations,
  getMyFederations,
  addMyFederation,
  updateMyFederation,
  deleteMyFederation,
  createFederation,
  updateFederation,
  deactivateFederation,
} from "@/api/federations"
import type {
  FederationResponse,
  MemberFederationResponse,
  FederationCreateRequest,
} from "@/api/federations"
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
import { Pencil, Trash2, Check, X, ShieldAlert, Pin } from "lucide-react"

// ── Form state ────────────────────────────────────────────────────────────────

type FormState = {
  full_name: string
  dob: string
  emergency_contact_name: string
  emergency_contact_phone: string
  federation_number: string
}

const EMPTY_FORM: FormState = {
  full_name: "",
  dob: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
  federation_number: "",
}

const memberToForm = (m: MemberResponse): FormState => ({
  full_name: m.full_name ?? "",
  dob: "",  // dob is not returned by the API — leave blank to avoid overwriting
  emergency_contact_name: m.emergency_contact_name ?? "",
  emergency_contact_phone: m.emergency_contact_phone ?? "",
  federation_number: m.federation_number ?? "",
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
        <CardTitle>Personal Details</CardTitle>
        <Button variant="outline" size="sm" onClick={onEdit}>
          Edit
        </Button>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Full name" value={member.full_name} />
          <Field label="Email" value={member.email} />
          <Field label="Date of birth" value={null} />
          <Field label="Join date" value={member.join_date} />
          <Field label="Membership status" value={member.membership_status} />
          <Field label="Federation number" value={member.federation_number} />
          <Field label="Emergency contact" value={member.emergency_contact_name} />
          <Field label="Emergency contact phone" value={member.emergency_contact_phone} />
        </dl>
        {(member.is_coach || member.is_first_aider || member.is_minor) && (
          <div className="flex gap-2 flex-wrap mt-4">
            {member.is_coach && <Badge>Coach</Badge>}
            {member.is_first_aider && <Badge>First aider</Badge>}
            {member.is_minor && <Badge variant="secondary">Minor</Badge>}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Date formatting ───────────────────────────────────────────────────────────

const formatDate = (iso: string): string => {
  const d = new Date(iso)
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
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
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) {
      setLabelDraft(passkey.label)
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [editing, passkey.label])

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
              ref={inputRef}
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
              onClick={() => setEditing(true)}
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
          Added {formatDate(passkey.created_at)}
        </span>
        <span className="text-xs text-muted-foreground">
          Last used: {passkey.last_used_at !== null ? formatDate(passkey.last_used_at) : "Never"}
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

// ── Security card ─────────────────────────────────────────────────────────────

type PasskeyLoadState =
  | { status: "loading" }
  | { status: "ready"; passkeys: PasskeyRecord[]; passkeyCount: number }
  | { status: "error"; message: string }

const SecurityCard = () => {
  const [state, setState] = useState<PasskeyLoadState>({ status: "loading" })
  const [addingPasskey, setAddingPasskey] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [nudgeOpen, setNudgeOpen] = useState(false)
  const [addingFromNudge, setAddingFromNudge] = useState(false)
  const [nudgeAddError, setNudgeAddError] = useState<string | null>(null)

  const loadData = () => {
    Promise.all([listPasskeys(), getSecurityStatus()])
      .then(([passkeys, status]) =>
        setState({ status: "ready", passkeys, passkeyCount: status.passkey_count })
      )
      .catch((err: unknown) => {
        setState({
          status: "error",
          message: isApiError(err) ? err.message : "Failed to load passkeys",
        })
      })
  }

  useEffect(() => {
    loadData()
  // eslint-disable-next-line react-hooks/exhaustive-deps
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
      const me = await getMe()
      const result = await performPasskeyRegistration(me.email)
      // Reload passkeys and security status
      loadData()
      if (result.show_nudge) {
        setNudgeOpen(true)
      }
    } catch (err) {
      setAddError(isApiError(err) ? err.message : "Failed to register passkey")
    } finally {
      setAddingPasskey(false)
    }
  }

  const handleNudgeAddPasskey = async () => {
    setNudgeAddError(null)
    setAddingFromNudge(true)
    try {
      const me = await getMe()
      await performPasskeyRegistration(me.email)
      // Reload after adding
      loadData()
      setNudgeOpen(false)
    } catch (err) {
      setNudgeAddError(isApiError(err) ? err.message : "Failed to register passkey")
    } finally {
      setAddingFromNudge(false)
    }
  }

  return (
    <>
      <Card>
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
            </div>
          )}
        </CardContent>
      </Card>

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

// ── Federations card (self-service) ───────────────────────────────────────────

type FederationFormState = {
  federation_id: string
  member_number: string
  renewal_date: string
  search: string
}

const EMPTY_FED_FORM: FederationFormState = {
  federation_id: "",
  member_number: "",
  renewal_date: "",
  search: "",
}

type RenewalBadgeProps = { status: "expiring_soon" | "expired" | null }

const RenewalBadge = ({ status }: RenewalBadgeProps) => {
  if (status === "expired") {
    return (
      <span className="inline-flex items-center rounded-full border border-red-200 bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800 dark:bg-red-900/30 dark:border-red-800 dark:text-red-400">
        Expired
      </span>
    )
  }
  if (status === "expiring_soon") {
    return (
      <span className="inline-flex items-center rounded-full border border-amber-200 bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:border-amber-800 dark:text-amber-400">
        Expiring soon
      </span>
    )
  }
  return null
}

const FederationsCard = () => {
  const [memberships, setMemberships] = useState<MemberFederationResponse[] | null>(null)
  const [federations, setFederations] = useState<FederationResponse[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FederationFormState>(EMPTY_FED_FORM)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [removeId, setRemoveId] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    Promise.all([getMyFederations(), listFederations()])
      .then(([mfs, feds]) => {
        setMemberships(mfs)
        setFederations(feds.filter((f) => f.is_active))
      })
      .catch((err: unknown) => {
        setLoadError(isApiError(err) ? err.message : "Failed to load federations")
      })
  }, [])

  const fedMap = new Map(federations.map((f) => [f.id, f]))

  const filteredFederations = form.search.trim()
    ? federations.filter(
        (f) =>
          f.name.toLowerCase().includes(form.search.toLowerCase()) ||
          (f.abbreviation ?? "").toLowerCase().includes(form.search.toLowerCase())
      )
    : federations

  const openAdd = () => {
    setForm(EMPTY_FED_FORM)
    setEditingId(null)
    setSaveError(null)
    setDialogOpen(true)
    setTimeout(() => searchRef.current?.focus(), 50)
  }

  const openEdit = (mf: MemberFederationResponse) => {
    setForm({
      federation_id: mf.federation_id,
      member_number: mf.member_number,
      renewal_date: mf.renewal_date ?? "",
      search: fedMap.get(mf.federation_id)?.name ?? "",
    })
    setEditingId(mf.id)
    setSaveError(null)
    setDialogOpen(true)
  }

  const handleSave = async () => {
    if (!form.federation_id || !form.member_number.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      if (editingId !== null) {
        const body: { member_number?: string; renewal_date?: string | null } = {
          member_number: form.member_number,
          renewal_date: form.renewal_date || null,
        }
        const updated = await updateMyFederation(editingId, body)
        setMemberships((prev) =>
          prev !== null ? prev.map((m) => (m.id === editingId ? updated : m)) : [updated]
        )
      } else {
        const body: { federation_id: string; member_number: string; renewal_date?: string } = {
          federation_id: form.federation_id,
          member_number: form.member_number,
        }
        if (form.renewal_date) body.renewal_date = form.renewal_date
        const created = await addMyFederation(body)
        setMemberships((prev) => (prev !== null ? [...prev, created] : [created]))
      }
      setDialogOpen(false)
    } catch (err) {
      setSaveError(isApiError(err) ? err.message : "Failed to save")
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async () => {
    if (removeId === null) return
    setRemoving(true)
    setRemoveError(null)
    try {
      await deleteMyFederation(removeId)
      setMemberships((prev) => (prev !== null ? prev.filter((m) => m.id !== removeId) : []))
      setRemoveId(null)
    } catch (err) {
      setRemoveError(isApiError(err) ? err.message : "Failed to remove")
    } finally {
      setRemoving(false)
    }
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Federations</CardTitle>
          <Button variant="outline" size="sm" onClick={openAdd} aria-label="Add federation membership">
            Add
          </Button>
        </CardHeader>
        <CardContent>
          {loadError !== null ? (
            <p className="text-sm text-destructive" role="alert">{loadError}</p>
          ) : memberships === null ? (
            <div className="space-y-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-3/4" />
            </div>
          ) : memberships.length === 0 ? (
            <p className="text-sm text-muted-foreground">No federation memberships yet.</p>
          ) : (
            <ul className="divide-y divide-border">
              {memberships.map((mf) => {
                const fed = fedMap.get(mf.federation_id)
                return (
                  <li key={mf.id} className="py-3 flex flex-wrap items-start justify-between gap-2">
                    <div className="space-y-0.5 min-w-0">
                      <p className="text-sm font-medium">{fed?.name ?? mf.federation_id}</p>
                      <p className="text-xs text-muted-foreground">
                        Member #{mf.member_number}
                        {mf.renewal_date !== null && (
                          <> · Renews {mf.renewal_date}</>
                        )}
                      </p>
                      <RenewalBadge status={mf.renewal_status} />
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0"
                        onClick={() => openEdit(mf)}
                        aria-label={`Edit ${fed?.name ?? "federation"} membership`}
                      >
                        <Pencil className="h-4 w-4" aria-hidden="true" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                        onClick={() => { setRemoveError(null); setRemoveId(mf.id) }}
                        aria-label={`Remove ${fed?.name ?? "federation"} membership`}
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={(o) => { if (!o) setDialogOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingId !== null ? "Edit federation membership" : "Add federation membership"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            {editingId === null && (
              <div className="space-y-1">
                <Label htmlFor="settings_fed_search">Federation</Label>
                <Input
                  id="settings_fed_search"
                  ref={searchRef}
                  placeholder="Search federations…"
                  value={form.search}
                  onChange={(e) => setForm((prev) => ({ ...prev, search: e.target.value, federation_id: "" }))}
                  autoComplete="off"
                />
                {filteredFederations.length > 0 && (
                  <ul className="mt-1 max-h-48 overflow-y-auto rounded-md border border-border bg-popover text-sm shadow-sm">
                    {filteredFederations.map((f) => (
                      <li key={f.id}>
                        <button
                          type="button"
                          className={[
                            "w-full text-left px-3 py-2 hover:bg-accent hover:text-accent-foreground transition-colors flex items-center gap-2",
                            form.federation_id === f.id ? "bg-accent text-accent-foreground font-medium" : "",
                          ].join(" ")}
                          onClick={() =>
                            setForm((prev) => ({ ...prev, federation_id: f.id, search: f.name }))
                          }
                        >
                          {f.is_pinned && (
                            <span className="text-xs text-muted-foreground shrink-0">★</span>
                          )}
                          <span className="flex-1 min-w-0 truncate">{f.name}</span>
                          {f.abbreviation !== null && (
                            <span className="text-xs text-muted-foreground shrink-0">{f.abbreviation}</span>
                          )}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {filteredFederations.length === 0 && form.search.trim() !== "" && (
                  <p className="text-xs text-muted-foreground mt-1">No federations match your search.</p>
                )}
              </div>
            )}
            {editingId !== null && (
              <div className="space-y-0.5">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Federation</p>
                <p className="text-sm">{fedMap.get(form.federation_id)?.name ?? form.federation_id}</p>
              </div>
            )}

            <div className="space-y-1">
              <Label htmlFor="settings_fed_member_number">Member number</Label>
              <Input
                id="settings_fed_member_number"
                value={form.member_number}
                onChange={(e) => setForm((prev) => ({ ...prev, member_number: e.target.value }))}
                placeholder="e.g. BKA-12345"
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="settings_fed_renewal_date">Renewal date (optional)</Label>
              <Input
                id="settings_fed_renewal_date"
                type="date"
                value={form.renewal_date}
                onChange={(e) => setForm((prev) => ({ ...prev, renewal_date: e.target.value }))}
              />
            </div>

            {saveError !== null && (
              <p className="text-sm text-destructive" role="alert">{saveError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDialogOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleSave()}
              disabled={saving || !form.federation_id || !form.member_number.trim()}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={removeId !== null} onOpenChange={(o) => { if (!o) setRemoveId(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove federation membership</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove this federation membership? This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {removeError !== null && (
            <p className="text-sm text-destructive" role="alert">{removeError}</p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRemoveId(null)}
              disabled={removing}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleRemove()}
              disabled={removing}
            >
              {removing ? "Removing…" : "Remove"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ── Admin Federation Catalogue ────────────────────────────────────────────────

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

  // Debounce search
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
          {/* Filters */}
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
              <p className="text-sm text-muted-foreground">No federations found.</p>
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

      {/* Add / Edit modal */}
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

// ── Page ──────────────────────────────────────────────────────────────────────

type LoadState =
  | { status: "loading" }
  | { status: "ready"; member: MemberResponse | null; user: UserClaims }
  | { status: "error"; message: string }

const SettingsPage = () => {
  const { theme, setTheme } = useThemeContext()
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
      full_name: form.full_name || undefined,
      emergency_contact_name: form.emergency_contact_name || null,
      emergency_contact_phone: form.emergency_contact_phone || null,
      federation_number: form.federation_number || null,
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
      <div className="px-4 py-6 max-w-2xl mx-auto space-y-4">
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    )
  }

  if (loadState.status === "error") {
    return (
      <div className="px-4 py-6 max-w-2xl mx-auto">
        <h1 className="text-xl font-semibold mb-4">Settings</h1>
        <p className="text-sm text-destructive" role="alert">
          {loadState.message}
        </p>
      </div>
    )
  }

  const isAdmin = loadState.status === "ready" && loadState.user.role === "admin"

  return (
    <div className={["px-4 py-6 mx-auto space-y-6", isAdmin ? "max-w-5xl" : "max-w-2xl"].join(" ")}>
      <h1 className="text-xl font-semibold">Settings</h1>

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
                <div className="space-y-1 sm:col-span-2">
                  <Label htmlFor="settings_full_name">Full name</Label>
                  <Input
                    id="settings_full_name"
                    value={form.full_name}
                    onChange={(e) => handleChange("full_name", e.target.value)}
                    placeholder="Your full name"
                    autoComplete="name"
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
                  <Label htmlFor="settings_federation_number">Federation number</Label>
                  <Input
                    id="settings_federation_number"
                    value={form.federation_number}
                    onChange={(e) => handleChange("federation_number", e.target.value)}
                    placeholder="Optional"
                  />
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

      <FederationsCard />

      {loadState.status === "ready" && loadState.user.role === "admin" && (
        <AdminFederationCatalogue />
      )}
    </div>
  )
}

export default SettingsPage
