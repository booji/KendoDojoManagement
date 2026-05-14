import { useEffect, useRef, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { getMember, getMyMember, updateMember, deactivateMember } from "@/api/members"
import type { MemberResponse, MembershipStatus, UpdateMemberRequest } from "@/api/members"
import { getMe, isApiError } from "@/api/auth"
import type { UserClaims } from "@/api/auth"
import { setMemberGrade, proposeGrade, getGradeHistory, ASSIGNABLE_GRADES } from "@/api/grades"
import type { GradeHistoryEntry } from "@/api/grades"
import { getMemberAttendanceHistory } from "@/api/attendance"
import type { AttendanceRecord } from "@/api/attendance"
import {
  listFederations,
  getMemberFederations,
  addMemberFederation,
  updateMemberFederation,
  deleteMemberFederation,
} from "@/api/federations"
import type { FederationResponse, MemberFederationResponse } from "@/api/federations"
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
import { ArrowLeftIcon, PencilIcon, ChevronDownIcon, ChevronUpIcon, ClipboardCopyIcon, CheckIcon, Trash2Icon } from "lucide-react"
import { generateAdminRecoveryToken } from "@/api/recovery"

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
  isOwnProfile: boolean
}

const GradeCard = ({ memberId, isAdmin, isOwnProfile }: GradeCardProps) => {
  const [history, setHistory] = useState<GradeHistoryEntry[] | null>(null)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  // Edit grade dialog state
  const [editOpen, setEditOpen] = useState(false)
  const [selectedGrade, setSelectedGrade] = useState<string>("")
  const [awardedAt, setAwardedAt] = useState<string>("")
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Propose grade dialog state
  const [proposeOpen, setProposeOpen] = useState(false)
  const [proposedGrade, setProposedGrade] = useState<string>("")
  const [proposedAt, setProposedAt] = useState<string>("")
  const [proposing, setProposing] = useState(false)
  const [proposeError, setProposeError] = useState<string | null>(null)

  useEffect(() => {
    getGradeHistory(memberId)
      .then(setHistory)
      .catch((err: unknown) => {
        setHistoryError(isApiError(err) ? err.message : "Failed to load grade history")
      })
  }, [memberId])

  const confirmedHistory = history !== null ? history.filter((e) => e.status === "confirmed") : null

  const currentGrade =
    confirmedHistory !== null && confirmedHistory.length > 0
      ? confirmedHistory.at(-1)!.display_name
      : "Mukyū"

  const openEditDialog = () => {
    setSelectedGrade("")
    setAwardedAt("")
    setSaveError(null)
    setEditOpen(true)
  }

  const openProposeDialog = () => {
    setProposedGrade("")
    setProposedAt("")
    setProposeError(null)
    setProposeOpen(true)
  }

  const handleSetGrade = async () => {
    if (!selectedGrade) return
    setSaving(true)
    setSaveError(null)
    try {
      const body: { grade: string; awarded_at?: string } = { grade: selectedGrade }
      if (awardedAt) body.awarded_at = new Date(awardedAt).toISOString()
      const result = await setMemberGrade(memberId, body)
      // Refetch full history to keep the list accurate
      const updated = await getGradeHistory(memberId)
      setHistory(updated)
      // If refetch somehow fails, at least append the new entry
      void result
      setEditOpen(false)
    } catch (err) {
      setSaveError(isApiError(err) ? err.message : "Failed to set grade")
    } finally {
      setSaving(false)
    }
  }

  const handleProposeGrade = async () => {
    if (!proposedGrade) return
    setProposing(true)
    setProposeError(null)
    try {
      const body: { grade: string; awarded_at?: string } = { grade: proposedGrade }
      if (proposedAt) body.awarded_at = new Date(proposedAt).toISOString()
      const result = await proposeGrade(memberId, body)
      void result
      const updated = await getGradeHistory(memberId)
      setHistory(updated)
      setProposeOpen(false)
    } catch (err) {
      setProposeError(isApiError(err) ? err.message : "Failed to propose grade")
    } finally {
      setProposing(false)
    }
  }

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Grade</CardTitle>
          <div className="flex gap-2">
            {isOwnProfile && (
              <Button
                variant="outline"
                size="sm"
                onClick={openProposeDialog}
                aria-label="Submit my grade"
              >
                Submit my grade
              </Button>
            )}
            {isAdmin && (
              <Button
                variant="outline"
                size="sm"
                onClick={openEditDialog}
                aria-label="Edit member grade"
              >
                <PencilIcon className="h-4 w-4 mr-1" aria-hidden="true" />
                Edit grade
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {historyError !== null ? (
            <p className="text-sm text-destructive" role="alert">{historyError}</p>
          ) : history === null ? (
            <Skeleton className="h-5 w-32" />
          ) : (
            <>
              <p className="text-sm font-medium">{currentGrade}</p>

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
                          {entry.status === "pending" && (
                            <span className="ml-2 inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 border-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-300">
                              awaiting confirmation
                            </span>
                          )}
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

      {/* Edit grade dialog */}
      <Dialog open={editOpen} onOpenChange={(o) => { if (!o) setEditOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Set grade</DialogTitle>
            <DialogDescription>
              Assign a confirmed grade to this member.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-1">
            <div className="space-y-1">
              <Label htmlFor="grade_select_trigger">Grade</Label>
              <Select value={selectedGrade} onValueChange={(v) => setSelectedGrade(v ?? "")}>
                <SelectTrigger id="grade_select_trigger" className="w-full" aria-label="Select grade">
                  <SelectValue placeholder="Select a grade…" />
                </SelectTrigger>
                <SelectContent>
                  {ASSIGNABLE_GRADES.map((g) => (
                    <SelectItem key={g.value} value={g.value}>
                      {g.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="awarded_at_input">Date awarded (optional)</Label>
              <Input
                id="awarded_at_input"
                type="date"
                value={awardedAt}
                onChange={(e) => setAwardedAt(e.target.value)}
                placeholder="Leave blank for today"
              />
            </div>

            {saveError !== null && (
              <p className="text-sm text-destructive" role="alert">{saveError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setEditOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleSetGrade()}
              disabled={saving || !selectedGrade}
              aria-label="Save grade"
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Propose grade dialog */}
      <Dialog open={proposeOpen} onOpenChange={(o) => { if (!o) setProposeOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Submit my grade</DialogTitle>
            <DialogDescription>
              Propose your own grade for admin confirmation.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-1">
            <div className="space-y-1">
              <Label htmlFor="propose_grade_select_trigger">Grade</Label>
              <Select value={proposedGrade} onValueChange={(v) => setProposedGrade(v ?? "")}>
                <SelectTrigger id="propose_grade_select_trigger" className="w-full" aria-label="Select grade to propose">
                  <SelectValue placeholder="Select a grade…" />
                </SelectTrigger>
                <SelectContent>
                  {ASSIGNABLE_GRADES.map((g) => (
                    <SelectItem key={g.value} value={g.value}>
                      {g.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label htmlFor="proposed_at_input">Date awarded (optional)</Label>
              <Input
                id="proposed_at_input"
                type="date"
                value={proposedAt}
                onChange={(e) => setProposedAt(e.target.value)}
                placeholder="Leave blank for today"
              />
            </div>

            {proposeError !== null && (
              <p className="text-sm text-destructive" role="alert">{proposeError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setProposeOpen(false)}
              disabled={proposing}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void handleProposeGrade()}
              disabled={proposing || !proposedGrade}
              aria-label="Submit grade proposal"
            >
              {proposing ? "Submitting…" : "Submit"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ── Attendance history card ───────────────────────────────────────────────────

type AttendanceHistoryCardProps = {
  memberId: string
}

const AttendanceHistoryCard = ({ memberId }: AttendanceHistoryCardProps) => {
  const [records, setRecords] = useState<AttendanceRecord[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    getMemberAttendanceHistory(memberId)
      .then(setRecords)
      .catch((err: unknown) => {
        setError(isApiError(err) ? err.message : "Failed to load attendance history")
      })
  }, [memberId])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Attendance History</CardTitle>
      </CardHeader>
      <CardContent>
        {error !== null ? (
          <p className="text-sm text-destructive" role="alert">{error}</p>
        ) : records === null ? (
          <div className="space-y-2">
            <Skeleton className="h-5 w-full" />
            <Skeleton className="h-5 w-3/4" />
          </div>
        ) : records.length === 0 ? (
          <p className="text-sm text-muted-foreground">No attendance records yet</p>
        ) : (
          <div>
            <button
              type="button"
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              aria-controls="attendance-history-list"
            >
              {open ? (
                <ChevronUpIcon className="h-3 w-3" aria-hidden="true" />
              ) : (
                <ChevronDownIcon className="h-3 w-3" aria-hidden="true" />
              )}
              {open ? "Hide" : "Show"} attendance ({records.length} sessions)
            </button>

            {open && (
              <ol
                id="attendance-history-list"
                className="mt-2 space-y-1 border-l-2 border-border pl-3"
              >
                {records.map((record) => (
                  <li key={record.id} className="text-sm">
                    <span className="font-mono text-xs">{record.session_id.slice(0, 8)}…</span>
                    <span className="text-muted-foreground ml-2 text-xs">
                      {new Date(record.checked_in_at).toLocaleDateString("default", {
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
      </CardContent>
    </Card>
  )
}

// ── Recovery token card ───────────────────────────────────────────────────────

type RecoveryTokenCardProps = {
  memberId: string
  memberName: string
}

const RecoveryTokenCard = ({ memberId, memberName }: RecoveryTokenCardProps) => {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [tokenOpen, setTokenOpen] = useState(false)
  const [token, setToken] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const handleConfirm = async () => {
    setError(null)
    setGenerating(true)
    try {
      const result = await generateAdminRecoveryToken(memberId)
      setToken(result.token)
      setConfirmOpen(false)
      setTokenOpen(true)
    } catch (err) {
      setError(isApiError(err) ? err.message : "Failed to generate recovery token")
      setConfirmOpen(false)
    } finally {
      setGenerating(false)
    }
  }

  const handleCopy = async () => {
    if (token === null) return
    try {
      await navigator.clipboard.writeText(token)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard API not available
    }
  }

  const handleTokenClose = () => {
    setTokenOpen(false)
    setToken(null)
    setCopied(false)
  }

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Account Recovery</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Generate a one-time recovery token to give to {memberName} if they are locked out of their account.
          </p>
          {error !== null && (
            <p className="text-sm text-destructive" role="alert">{error}</p>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => { setError(null); setConfirmOpen(true) }}
            aria-label={`Generate recovery token for ${memberName}`}
          >
            Generate recovery token
          </Button>
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={(o) => { if (!o) setConfirmOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Generate recovery token?</DialogTitle>
            <DialogDescription>
              This will create a one-time recovery token for {memberName}. The token will only be shown once — share it with the member in person.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={generating} aria-label="Cancel">
              Cancel
            </Button>
            <Button onClick={handleConfirm} disabled={generating} aria-label="Generate token">
              {generating ? "Generating…" : "Generate token"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={tokenOpen} onOpenChange={(o) => { if (!o) handleTokenClose() }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Recovery token</DialogTitle>
            <DialogDescription>
              This token will not be shown again. Share it with the member in person.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="rounded-md bg-muted px-4 py-3 font-mono text-sm break-all select-all" aria-label="Recovery token">
              {token}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopy}
              aria-label="Copy token to clipboard"
              className="w-full sm:w-auto"
            >
              {copied ? (
                <><CheckIcon className="mr-1.5 h-4 w-4" aria-hidden="true" />Copied</>
              ) : (
                <><ClipboardCopyIcon className="mr-1.5 h-4 w-4" aria-hidden="true" />Copy to clipboard</>
              )}
            </Button>
            <p className="text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-md px-3 py-2" role="note">
              Warning: This token will not be shown again. Store it securely and share it with the member in person.
            </p>
          </div>
          <DialogFooter>
            <Button onClick={handleTokenClose} aria-label="Close">Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

// ── Federations card ──────────────────────────────────────────────────────────

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

type FederationsCardProps = {
  memberId: string
}

const FederationsCard = ({ memberId }: FederationsCardProps) => {
  const [memberships, setMemberships] = useState<MemberFederationResponse[] | null>(null)
  const [federations, setFederations] = useState<FederationResponse[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FederationFormState>(EMPTY_FED_FORM)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Remove confirm dialog
  const [removeId, setRemoveId] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    Promise.all([getMemberFederations(memberId), listFederations()])
      .then(([mfs, feds]) => {
        setMemberships(mfs)
        setFederations(feds)
      })
      .catch((err: unknown) => {
        setLoadError(isApiError(err) ? err.message : "Failed to load federations")
      })
  }, [memberId])

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
        const updated = await updateMemberFederation(memberId, editingId, body)
        setMemberships((prev) =>
          prev !== null ? prev.map((m) => (m.id === editingId ? updated : m)) : [updated]
        )
      } else {
        const body: { federation_id: string; member_number: string; renewal_date?: string } = {
          federation_id: form.federation_id,
          member_number: form.member_number,
        }
        if (form.renewal_date) body.renewal_date = form.renewal_date
        const created = await addMemberFederation(memberId, body)
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
      await deleteMemberFederation(memberId, removeId)
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
                        <PencilIcon className="h-4 w-4" aria-hidden="true" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                        onClick={() => { setRemoveError(null); setRemoveId(mf.id) }}
                        aria-label={`Remove ${fed?.name ?? "federation"} membership`}
                      >
                        <Trash2Icon className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Add / Edit dialog */}
      <Dialog open={dialogOpen} onOpenChange={(o) => { if (!o) setDialogOpen(false) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingId !== null ? "Edit federation membership" : "Add federation membership"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-1">
            {/* Federation selector */}
            {editingId === null && (
              <div className="space-y-1">
                <Label htmlFor="fed_search">Federation</Label>
                <Input
                  id="fed_search"
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
              <Label htmlFor="fed_member_number">Member number</Label>
              <Input
                id="fed_member_number"
                value={form.member_number}
                onChange={(e) => setForm((prev) => ({ ...prev, member_number: e.target.value }))}
                placeholder="e.g. BKA-12345"
              />
            </div>

            <div className="space-y-1">
              <Label htmlFor="fed_renewal_date">Renewal date (optional)</Label>
              <Input
                id="fed_renewal_date"
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

      {/* Remove confirm dialog */}
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

// ── Page ──────────────────────────────────────────────────────────────────────

const MemberDetailPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [member, setMember] = useState<MemberResponse | null>(null)
  const [currentUser, setCurrentUser] = useState<UserClaims | null>(null)
  const [myMember, setMyMember] = useState<MemberResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<EditFormState | null>(null)
  const [editError, setEditError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const [deactivateOpen, setDeactivateOpen] = useState(false)
  const [deactivating, setDeactivating] = useState(false)

  useEffect(() => {
    if (!id) return
    Promise.all([getMember(id), getMe(), getMyMember()])
      .then(([m, u, mine]) => {
        setMember(m)
        setCurrentUser(u)
        setMyMember(mine)
      })
      .catch((err: unknown) => {
        setLoadError(isApiError(err) ? err.message : "Failed to load member")
      })
  }, [id])

  const isAdmin = currentUser?.role === "admin"
  const isOwnProfile = !isAdmin && member !== null && myMember !== null && member.id === myMember.id

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

          <GradeCard memberId={member.id} isAdmin={isAdmin} isOwnProfile={isOwnProfile} />

          <FederationsCard memberId={member.id} />

          <AttendanceHistoryCard memberId={member.id} />

          {isAdmin && (
            <RecoveryTokenCard memberId={member.id} memberName={member.full_name} />
          )}
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
