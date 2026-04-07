import { useEffect, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { getMember, updateMember, deactivateMember } from "@/api/members"
import type { MemberResponse, MembershipStatus, UpdateMemberRequest } from "@/api/members"
import { getMe, isApiError } from "@/api/auth"
import type { UserClaims } from "@/api/auth"
import { promoteMember, getGradeHistory } from "@/api/grades"
import type { GradeHistoryEntry } from "@/api/grades"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog"
import { ArrowLeftIcon, PencilIcon, ChevronDownIcon, ChevronUpIcon } from "lucide-react"

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_CLASSES: Record<MembershipStatus, string> = {
  active: "bg-green-100 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-300",
  inactive: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-400",
  suspended: "bg-red-100 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-400",
}

const StatusBadge = ({ status }: { status: MembershipStatus }) => (
  <span
    className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${STATUS_CLASSES[status]}`}
    aria-label={`Membership status: ${status}`}
  >
    {status.charAt(0).toUpperCase() + status.slice(1)}
  </span>
)

// ── Read-only field ───────────────────────────────────────────────────────────

const Field = ({ label, value }: { label: string; value: string | null | boolean }) => {
  const display =
    value === null || value === undefined
      ? "—"
      : typeof value === "boolean"
        ? value ? "Yes" : "No"
        : value

  return (
    <div className="space-y-0.5">
      <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
        {label}
      </p>
      <p className="text-sm">{display as string}</p>
    </div>
  )
}

// ── Edit form ─────────────────────────────────────────────────────────────────

type EditFormState = {
  email: string
  full_name: string
  dob: string
  join_date: string
  membership_status: MembershipStatus
  is_coach: boolean
  is_first_aider: boolean
  emergency_contact_name: string
  emergency_contact_phone: string
  federation_number: string
  parental_consent_obtained: boolean
}

const memberToForm = (m: MemberResponse): EditFormState => ({
  email: m.email,
  full_name: m.full_name,
  dob: "",  // dob not returned by API — leave blank to avoid overwriting
  join_date: m.join_date,
  membership_status: m.membership_status,
  is_coach: m.is_coach,
  is_first_aider: m.is_first_aider,
  emergency_contact_name: m.emergency_contact_name ?? "",
  emergency_contact_phone: m.emergency_contact_phone ?? "",
  federation_number: m.federation_number ?? "",
  parental_consent_obtained: m.parental_consent_obtained,
})

type EditFormProps = {
  form: EditFormState
  saving: boolean
  error: string | null
  onSubmit: (e: React.FormEvent) => void
  onChange: <K extends keyof EditFormState>(key: K, value: EditFormState[K]) => void
  onCancel: () => void
}

const EditForm = ({ form, saving, error, onSubmit, onChange, onCancel }: EditFormProps) => (
  <form onSubmit={onSubmit} className="space-y-4" aria-label="Edit member form">
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div className="space-y-1">
        <Label htmlFor="edit_full_name">Full name *</Label>
        <Input
          id="edit_full_name"
          value={form.full_name}
          onChange={(e) => onChange("full_name", e.target.value)}
          required
          aria-required="true"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_email">Email *</Label>
        <Input
          id="edit_email"
          type="email"
          value={form.email}
          onChange={(e) => onChange("email", e.target.value)}
          required
          aria-required="true"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_dob">Date of birth</Label>
        <Input
          id="edit_dob"
          type="date"
          value={form.dob}
          onChange={(e) => onChange("dob", e.target.value)}
          placeholder="Leave blank to keep unchanged"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_join_date">Join date *</Label>
        <Input
          id="edit_join_date"
          type="date"
          value={form.join_date}
          onChange={(e) => onChange("join_date", e.target.value)}
          required
          aria-required="true"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_status_trigger">Status</Label>
        <Select
          value={form.membership_status}
          onValueChange={(v) => onChange("membership_status", v as MembershipStatus)}
        >
          <SelectTrigger id="edit_status_trigger" className="w-full" aria-label="Membership status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
            <SelectItem value="suspended">Suspended</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_federation_number">Federation number</Label>
        <Input
          id="edit_federation_number"
          value={form.federation_number}
          onChange={(e) => onChange("federation_number", e.target.value)}
          placeholder="Optional"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_ec_name">Emergency contact name</Label>
        <Input
          id="edit_ec_name"
          value={form.emergency_contact_name}
          onChange={(e) => onChange("emergency_contact_name", e.target.value)}
          placeholder="Optional"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_ec_phone">Emergency contact phone</Label>
        <Input
          id="edit_ec_phone"
          type="tel"
          value={form.emergency_contact_phone}
          onChange={(e) => onChange("emergency_contact_phone", e.target.value)}
          placeholder="Optional"
        />
      </div>
    </div>

    <div className="flex flex-col gap-2">
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          className="rounded"
          checked={form.is_coach}
          onChange={(e) => onChange("is_coach", e.target.checked)}
          aria-label="Is coach"
        />
        Coach
      </label>
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          className="rounded"
          checked={form.is_first_aider}
          onChange={(e) => onChange("is_first_aider", e.target.checked)}
          aria-label="Is first aider"
        />
        First Aider
      </label>
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          className="rounded"
          checked={form.parental_consent_obtained}
          onChange={(e) => onChange("parental_consent_obtained", e.target.checked)}
          aria-label="Parental consent obtained"
        />
        Parental consent obtained
      </label>
    </div>

    {error !== null && (
      <p className="text-sm text-destructive" role="alert">
        {error}
      </p>
    )}

    <div className="flex flex-col-reverse sm:flex-row gap-2 sm:justify-end pt-2">
      <Button
        type="button"
        variant="outline"
        onClick={onCancel}
        disabled={saving}
        aria-label="Cancel editing"
      >
        Cancel
      </Button>
      <Button
        type="submit"
        disabled={saving}
        aria-label="Save changes"
      >
        {saving ? "Saving…" : "Save changes"}
      </Button>
    </div>
  </form>
)

// ── Deactivate confirm dialog ─────────────────────────────────────────────────

type DeactivateDialogProps = {
  open: boolean
  memberName: string
  onConfirm: () => void
  onClose: () => void
  loading: boolean
}

const DeactivateDialog = ({ open, memberName, onConfirm, onClose, loading }: DeactivateDialogProps) => (
  <Dialog open={open} onOpenChange={(o) => { if (!o) onClose() }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Deactivate member</DialogTitle>
        <DialogDescription>
          This will set {memberName}&apos;s status to inactive. You can re-activate them later.
        </DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button
          variant="outline"
          onClick={onClose}
          disabled={loading}
          aria-label="Cancel deactivation"
        >
          Cancel
        </Button>
        <Button
          variant="destructive"
          onClick={onConfirm}
          disabled={loading}
        >
          {loading ? "Confirming…" : "Confirm"}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
)

// ── Grade card ────────────────────────────────────────────────────────────────

type GradeCardProps = {
  memberId: string
  isAdmin: boolean
}

const GradeCard = ({ memberId, isAdmin }: GradeCardProps) => {
  const [history, setHistory] = useState<GradeHistoryEntry[] | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [promoting, setPromoting] = useState(false)
  const [promoteError, setPromoteError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  useEffect(() => {
    getGradeHistory(memberId)
      .then(setHistory)
      .catch((err: unknown) => {
        setHistoryError(isApiError(err) ? err.message : "Failed to load grade history")
      })
  }, [memberId])

  const currentGrade =
    history !== null && history.length > 0
      ? history[history.length - 1].display_name
      : "Mukyū"

  const handlePromote = async () => {
    setPromoteError(null)
    setPromoting(true)
    try {
      const result = await promoteMember(memberId)
      setHistory((prev) => (prev !== null ? [...prev, result] : [result]))
    } catch (err) {
      setPromoteError(isApiError(err) ? err.message : "Failed to promote member")
    } finally {
      setPromoting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Grade</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {historyError !== null ? (
          <p className="text-sm text-destructive" role="alert">{historyError}</p>
        ) : history === null ? (
          <Skeleton className="h-5 w-32" />
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm font-medium">{currentGrade}</p>
              {isAdmin && (
                <Button
                  size="sm"
                  onClick={handlePromote}
                  disabled={promoting}
                  aria-label="Promote member"
                >
                  {promoting ? "Promoting…" : "Promote"}
                </Button>
              )}
            </div>

            {promoteError !== null && (
              <p className="text-sm text-destructive" role="alert">{promoteError}</p>
            )}

            {history.length > 0 && (
              <div>
                <button
                  type="button"
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setHistoryOpen((o) => !o)}
                  aria-expanded={historyOpen}
                  aria-controls="grade-history-list"
                >
                  {historyOpen ? (
                    <ChevronUpIcon className="h-3 w-3" aria-hidden="true" />
                  ) : (
                    <ChevronDownIcon className="h-3 w-3" aria-hidden="true" />
                  )}
                  {historyOpen ? "Hide" : "Show"} grade history ({history.length})
                </button>

                {historyOpen && (
                  <ol
                    id="grade-history-list"
                    className="mt-2 space-y-1 border-l-2 border-border pl-3"
                  >
                    {history.map((entry) => (
                      <li key={entry.id} className="text-sm">
                        <span className="font-medium">{entry.display_name}</span>
                        <span className="text-muted-foreground ml-2 text-xs">
                          {new Date(entry.promoted_at).toLocaleDateString("default", {
                            day: "numeric",
                            month: "long",
                            year: "numeric",
                          })}
                        </span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

const MemberDetailPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [member, setMember] = useState<MemberResponse | null>(null)
  const [currentUser, setCurrentUser] = useState<UserClaims | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<EditFormState | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const [deactivateOpen, setDeactivateOpen] = useState(false)
  const [deactivating, setDeactivating] = useState(false)

  useEffect(() => {
    if (!id) return
    Promise.all([getMember(id), getMe()])
      .then(([m, u]) => {
        setMember(m)
        setCurrentUser(u)
      })
      .catch((err: unknown) => {
        setLoadError(isApiError(err) ? err.message : "Failed to load member")
      })
  }, [id])

  const isAdmin = currentUser?.role === "admin"

  const startEdit = () => {
    if (member === null) return
    setForm(memberToForm(member))
    setEditError(null)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setForm(null)
    setEditError(null)
  }

  const handleFormChange = <K extends keyof EditFormState>(key: K, value: EditFormState[K]) => {
    setForm((prev) => (prev !== null ? { ...prev, [key]: value } : prev))
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!id || form === null) return
    setEditError(null)
    setSaving(true)
    try {
      const payload: UpdateMemberRequest = {
        email: form.email,
        full_name: form.full_name,
        join_date: form.join_date,
        membership_status: form.membership_status,
        is_coach: form.is_coach,
        is_first_aider: form.is_first_aider,
        emergency_contact_name: form.emergency_contact_name || null,
        emergency_contact_phone: form.emergency_contact_phone || null,
        federation_number: form.federation_number || null,
        parental_consent_obtained: form.parental_consent_obtained,
        ...(form.dob ? { dob: form.dob } : {}),
      }
      const updated = await updateMember(id, payload)
      setMember(updated)
      setEditing(false)
      setForm(null)
    } catch (err) {
      setEditError(isApiError(err) ? err.message : "Failed to save changes")
    } finally {
      setSaving(false)
    }
  }

  const handleDeactivate = async () => {
    if (!id) return
    setDeactivating(true)
    try {
      const updated = await deactivateMember(id)
      setMember(updated)
      setDeactivateOpen(false)
    } catch (err) {
      // Deactivation errors surface in the load error area
      setLoadError(isApiError(err) ? err.message : "Failed to deactivate member")
      setDeactivateOpen(false)
    } finally {
      setDeactivating(false)
    }
  }

  // Loading state
  if (member === null && loadError === null) {
    return (
      <div className="px-4 py-6 max-w-2xl mx-auto space-y-4">
        <Skeleton className="h-6 w-24" />
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    )
  }

  // Error state
  if (loadError !== null) {
    return (
      <div className="px-4 py-6 max-w-2xl mx-auto">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate("/members")}
          aria-label="Back to members list"
          className="mb-4"
        >
          <ArrowLeftIcon aria-hidden="true" />
          Back
        </Button>
        <p className="text-sm text-destructive" role="alert">
          {loadError}
        </p>
      </div>
    )
  }

  if (member === null) return null

  return (
    <div className="px-4 py-6 max-w-2xl mx-auto space-y-6">
      {/* Back nav */}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => navigate("/members")}
        aria-label="Back to members list"
      >
        <ArrowLeftIcon aria-hidden="true" />
        Back
      </Button>

      {/* Name + status header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{member.full_name}</h1>
          <p className="text-sm text-muted-foreground mt-0.5">{member.email}</p>
          <div className="flex flex-wrap gap-2 mt-2">
            <StatusBadge status={member.membership_status} />
            {member.is_minor && (
              <span
                className="inline-flex items-center rounded-full border border-yellow-200 bg-yellow-100 px-2.5 py-0.5 text-xs font-medium text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300"
                aria-label="Minor — parental consent required"
              >
                Minor
              </span>
            )}
            {member.is_coach && (
              <span className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium bg-secondary text-secondary-foreground">
                Coach
              </span>
            )}
            {member.is_first_aider && (
              <span className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium text-foreground">
                First Aider
              </span>
            )}
          </div>
        </div>

        {/* Admin actions */}
        {isAdmin && !editing && (
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={startEdit}
              aria-label={`Edit ${member.full_name}`}
            >
              <PencilIcon aria-hidden="true" />
              Edit
            </Button>
            {member.membership_status !== "inactive" && (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setDeactivateOpen(true)}
              >
                Deactivate
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Edit form */}
      {editing && form !== null && (
        <Card>
          <CardHeader>
            <CardTitle>Edit member</CardTitle>
          </CardHeader>
          <CardContent>
            <EditForm
              form={form}
              saving={saving}
              error={editError}
              onSubmit={handleSave}
              onChange={handleFormChange}
              onCancel={cancelEdit}
            />
          </CardContent>
        </Card>
      )}

      {/* Read-only details */}
      {!editing && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Membership details</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field label="Join date" value={new Date(member.join_date).toLocaleDateString("default", { day: "numeric", month: "long", year: "numeric" })} />
              <Field label="Federation number" value={member.federation_number} />
              <Field label="Parental consent" value={member.parental_consent_obtained} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Emergency contact</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field label="Name" value={member.emergency_contact_name} />
              <Field label="Phone" value={member.emergency_contact_phone} />
            </CardContent>
          </Card>

          <GradeCard memberId={member.id} isAdmin={isAdmin} />
        </>
      )}

      {/* Deactivate confirm */}
      <DeactivateDialog
        open={deactivateOpen}
        memberName={member.full_name}
        onConfirm={handleDeactivate}
        onClose={() => setDeactivateOpen(false)}
        loading={deactivating}
      />
    </div>
  )
}

export default MemberDetailPage
