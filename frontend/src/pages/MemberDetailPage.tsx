import { useEffect, useMemo, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { getMember, getMyMember, updateMember, eraseMember, formatMemberName } from "@/api/members"
import type { MemberResponse, MembershipStatus, UpdateMemberRequest } from "@/api/members"
import { getMe, isApiError } from "@/api/auth"
import type { UserClaims } from "@/api/auth"
import { setMemberGrade, proposeGrade, getGradeHistory, approveGrade, rejectGrade, ASSIGNABLE_GRADES } from "@/api/grades"
import type { GradeHistoryEntry } from "@/api/grades"
import { getMemberAttendanceHistory } from "@/api/attendance"
import type { AttendanceRecord } from "@/api/attendance"
import { formatMemberDate } from "@/lib/date"
import { memberFederationMemberships } from "@/api/federations"
import CopyButton from "@/components/CopyButton"
import FederationMembershipsCard from "@/components/FederationMembershipsCard"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { PageHeader } from "@/components/ui/page-header"
import { Badge } from "@/components/ui/badge"
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
import { ArrowLeftIcon, PencilIcon, ChevronDownIcon, ChevronUpIcon, Trash2Icon } from "lucide-react"
import { generateAdminRecoveryToken } from "@/api/recovery"

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_VARIANTS: Record<MembershipStatus, "success" | "secondary" | "destructive" | "outline"> = {
  active: "success",
  inactive: "secondary",
  suspended: "destructive",
  archived: "outline",
}

const StatusBadge = ({ status }: { status: MembershipStatus }) => (
  <Badge
    variant={STATUS_VARIANTS[status]}
    aria-label={`Membership status: ${status}`}
  >
    {status.charAt(0).toUpperCase() + status.slice(1)}
  </Badge>
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
  first_name: string
  surname: string
  display_name: string
  dob: string
  join_date: string
  membership_status: MembershipStatus
  is_coach: boolean
  is_first_aider: boolean
  emergency_contact_name: string
  emergency_contact_phone: string
}

const memberToForm = (m: MemberResponse): EditFormState => ({
  email: m.email,
  first_name: m.first_name,
  surname: m.surname,
  display_name: m.display_name ?? "",
  dob: "",
  join_date: m.join_date,
  membership_status: m.membership_status,
  is_coach: m.is_coach,
  is_first_aider: m.is_first_aider,
  emergency_contact_name: m.emergency_contact_name ?? "",
  emergency_contact_phone: m.emergency_contact_phone ?? "",
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
        <Label htmlFor="edit_first_name">First name *</Label>
        <Input
          id="edit_first_name"
          value={form.first_name}
          onChange={(e) => onChange("first_name", e.target.value)}
          required
          aria-required="true"
        />
      </div>

      <div className="space-y-1">
        <Label htmlFor="edit_surname">Surname *</Label>
        <Input
          id="edit_surname"
          value={form.surname}
          onChange={(e) => onChange("surname", e.target.value)}
          required
          aria-required="true"
        />
      </div>

      <div className="space-y-1 sm:col-span-2">
        <Label htmlFor="edit_display_name">Display name</Label>
        <Input
          id="edit_display_name"
          value={form.display_name}
          onChange={(e) => onChange("display_name", e.target.value)}
          placeholder="Optional — overrides first name + surname in lists"
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
            <SelectItem value="archived">Archived</SelectItem>
          </SelectContent>
        </Select>
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

  const [actionInProgress, setActionInProgress] = useState<string | null>(null)

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

  const handleApprove = async (entryId: string) => {
    setActionInProgress(entryId)
    try {
      const updated = await approveGrade(memberId, entryId)
      setHistory((prev) =>
        prev === null ? null : prev.map((e) => (e.id === updated.id ? updated : e))
      )
    } catch {
      // silently ignore — the button will re-enable
    } finally {
      setActionInProgress(null)
    }
  }

  const handleReject = async (entryId: string) => {
    setActionInProgress(entryId)
    try {
      await rejectGrade(memberId, entryId)
      setHistory((prev) =>
        prev === null ? null : prev.filter((e) => e.id !== entryId)
      )
    } catch {
      // silently ignore
    } finally {
      setActionInProgress(null)
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
                        <li key={entry.id} className="text-sm flex items-center gap-2 flex-wrap">
                          <span className="font-medium">{entry.display_name}</span>
                          {entry.status === "pending" && (
                            <Badge variant="warning">awaiting confirmation</Badge>
                          )}
                          <span className="text-muted-foreground text-xs">
                            {formatMemberDate(entry.promoted_at)}
                          </span>
                          {isAdmin && entry.status === "pending" && (
                            <span className="flex gap-1 ml-auto">
                              <button
                                onClick={() => void handleApprove(entry.id)}
                                disabled={actionInProgress === entry.id}
                                aria-label={`Approve ${entry.display_name}`}
                                className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 border border-green-200 hover:bg-green-200 disabled:opacity-50 dark:bg-green-900/30 dark:text-green-300"
                              >
                                Approve
                              </button>
                              <button
                                onClick={() => void handleReject(entry.id)}
                                disabled={actionInProgress === entry.id}
                                aria-label={`Reject ${entry.display_name}`}
                                className="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium bg-red-100 text-red-800 border border-red-200 hover:bg-red-200 disabled:opacity-50 dark:bg-red-900/30 dark:text-red-300"
                              >
                                Reject
                              </button>
                            </span>
                          )}
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
                      {formatMemberDate(record.checked_in_at)}
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

  const handleTokenClose = () => {
    setTokenOpen(false)
    setToken(null)
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
            {token !== null && (
              <CopyButton
                value={token}
                label="Copy token to clipboard"
                className="w-full sm:w-auto"
              />
            )}
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

  // Memoised so the card's load effect keys off the Member, not the render:
  // the adapter is a fresh object every call.
  const memberId = member?.id
  const federationStore = useMemo(
    () => (memberId === undefined ? null : memberFederationMemberships(memberId)),
    [memberId],
  )

  const [eraseDialogOpen, setEraseDialogOpen] = useState(false)
  const [eraseConfirmText, setEraseConfirmText] = useState("")
  const [erasing, setErasing] = useState(false)
  const [eraseError, setEraseError] = useState<string | null>(null)

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
  const isErased = member !== null && member.anonymised_at !== null

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
        first_name: form.first_name,
        surname: form.surname,
        display_name: form.display_name || null,
        join_date: form.join_date,
        membership_status: form.membership_status,
        is_coach: form.is_coach,
        is_first_aider: form.is_first_aider,
        emergency_contact_name: form.emergency_contact_name || null,
        emergency_contact_phone: form.emergency_contact_phone || null,
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

  const openEraseDialog = () => {
    setEraseConfirmText("")
    setEraseError(null)
    setEraseDialogOpen(true)
  }

  const closeEraseDialog = () => {
    setEraseDialogOpen(false)
    setEraseConfirmText("")
    setEraseError(null)
  }

  const handleErase = async () => {
    if (!id) return
    setErasing(true)
    setEraseError(null)
    try {
      const updated = await eraseMember(id)
      setMember(updated)
      closeEraseDialog()
    } catch (err) {
      setEraseError(isApiError(err) ? err.message : "Failed to erase member")
    } finally {
      setErasing(false)
    }
  }

  // Loading state
  if (member === null && loadError === null) {
    return (
      <div className="px-4 py-6 space-y-4">
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
      <div className="px-4 py-6">
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
    <div className="px-4 py-6 space-y-6">
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
      <PageHeader
        title={formatMemberName(member)}
        description={member.email}
        action={
          isAdmin && !editing ? (
            <div className="flex gap-2">
              {member.membership_status === "archived" && !isErased && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={openEraseDialog}
                  aria-label={`Delete ${formatMemberName(member)} permanently`}
                >
                  <Trash2Icon aria-hidden="true" />
                  Delete permanently
                </Button>
              )}
              {!isErased && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={startEdit}
                  aria-label={`Edit ${formatMemberName(member)}`}
                >
                  <PencilIcon aria-hidden="true" />
                  Edit
                </Button>
              )}
            </div>
          ) : null
        }
      />
      <div className="flex flex-wrap gap-2 -mt-4">
        <StatusBadge status={member.membership_status} />
        {member.is_coach && <Badge variant="secondary">Coach</Badge>}
        {member.is_first_aider && <Badge variant="outline">First Aider</Badge>}
      </div>

      {isErased && (
        <p className="text-xs text-muted-foreground" role="note">
          This member's personal data has been erased.
        </p>
      )}

      {/* Edit form */}
      {editing && form !== null && !isErased && (
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
              <Field label="First name" value={member.first_name} />
              <Field label="Surname" value={member.surname} />
              <Field label="Display name" value={member.display_name} />
              <Field label="Date of birth" value={member.dob !== null ? formatMemberDate(member.dob) : null} />
              <Field label="Join date" value={formatMemberDate(member.join_date)} />
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

          {federationStore !== null && (
            <FederationMembershipsCard store={federationStore} />
          )}

          <AttendanceHistoryCard memberId={member.id} />

          {isAdmin && (
            <RecoveryTokenCard memberId={member.id} memberName={formatMemberName(member)} />
          )}
        </>
      )}

      {/* Erase confirmation dialog */}
      <Dialog open={eraseDialogOpen} onOpenChange={(o) => { if (!o) closeEraseDialog() }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {formatMemberName(member)} permanently?</DialogTitle>
            <DialogDescription>
              This permanently erases this member's personal data (name, email, date of
              birth, emergency contact). This cannot be undone. Type{" "}
              <strong>{formatMemberName(member)}</strong> to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-1">
            <Label htmlFor="erase_confirm_input">Type the member's name to confirm</Label>
            <Input
              id="erase_confirm_input"
              value={eraseConfirmText}
              onChange={(e) => setEraseConfirmText(e.target.value)}
              placeholder={formatMemberName(member)}
              autoComplete="off"
            />
            {eraseError !== null && (
              <p className="text-sm text-destructive" role="alert">{eraseError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={closeEraseDialog}
              disabled={erasing}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleErase()}
              disabled={erasing || eraseConfirmText !== formatMemberName(member)}
              aria-label="Confirm delete member permanently"
            >
              {erasing ? "Deleting…" : "Delete permanently"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default MemberDetailPage
