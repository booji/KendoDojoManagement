import { useEffect, useState, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { listMembers, createMember, formatMemberName, MEMBERSHIP_STATUSES } from "@/api/members"
import type { MemberListItem, MemberResponse, MembershipStatus, CreateMemberRequest } from "@/api/members"
import { isApiError } from "@/api/auth"
import { formatMemberDate, formatShortDate } from "@/lib/date"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Label } from "@/components/ui/label"
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
} from "@/components/ui/dialog"
import { PlusIcon, SearchIcon } from "lucide-react"
import { PageHeader } from "@/components/ui/page-header"
import { EmptyState } from "@/components/ui/empty-state"

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_VARIANTS: Record<MembershipStatus, "success" | "secondary" | "destructive" | "outline"> = {
  active: "success",
  inactive: "secondary",
  suspended: "destructive",
  archived: "outline",
}

const StatusBadge = ({ status }: { status: MembershipStatus }) => (
  <Badge variant={STATUS_VARIANTS[status]} aria-label={`Status: ${status}`}>
    {status.charAt(0).toUpperCase() + status.slice(1)}
  </Badge>
)

// ── Role badges ───────────────────────────────────────────────────────────────

const RoleBadges = ({ member }: { member: MemberResponse }) => (
  <div className="flex flex-wrap gap-1">
    {member.is_coach && (
      <Badge variant="secondary" aria-label="Coach">
        Coach
      </Badge>
    )}
    {member.is_first_aider && (
      <Badge variant="outline" aria-label="First Aider">
        First Aider
      </Badge>
    )}
  </div>
)

// ── Add Member modal ──────────────────────────────────────────────────────────

type AddMemberFormState = {
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

const defaultFormState = (): AddMemberFormState => ({
  email: "",
  first_name: "",
  surname: "",
  display_name: "",
  dob: "",
  join_date: new Date().toISOString().slice(0, 10),
  membership_status: "active",
  is_coach: false,
  is_first_aider: false,
  emergency_contact_name: "",
  emergency_contact_phone: "",
})

type AddMemberDialogProps = {
  open: boolean
  onClose: () => void
  onCreated: (member: MemberResponse) => void
}

const AddMemberDialog = ({ open, onClose, onCreated }: AddMemberDialogProps) => {
  const [form, setForm] = useState<AddMemberFormState>(defaultFormState)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      setForm(defaultFormState())
      setError(null)
      onClose()
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const payload: CreateMemberRequest = {
        email: form.email,
        first_name: form.first_name,
        surname: form.surname,
        display_name: form.display_name || null,
        dob: form.dob || undefined,
        join_date: form.join_date,
        membership_status: form.membership_status,
        is_coach: form.is_coach,
        is_first_aider: form.is_first_aider,
        emergency_contact_name: form.emergency_contact_name || null,
        emergency_contact_phone: form.emergency_contact_phone || null,
      }
      const created = await createMember(payload)
      onCreated(created)
      setForm(defaultFormState())
    } catch (err) {
      setError(isApiError(err) ? err.message : "Failed to create member")
    } finally {
      setSaving(false)
    }
  }

  const set = <K extends keyof AddMemberFormState>(key: K, value: AddMemberFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg overflow-y-auto max-h-[90vh]">
        <DialogHeader>
          <DialogTitle>Add Member</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} id="add-member-form" className="space-y-4 py-2">
          {/* Name */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label htmlFor="first_name">First name *</Label>
              <Input
                id="first_name"
                value={form.first_name}
                onChange={(e) => set("first_name", e.target.value)}
                required
                aria-required="true"
                placeholder="Jane"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="surname">Surname *</Label>
              <Input
                id="surname"
                value={form.surname}
                onChange={(e) => set("surname", e.target.value)}
                required
                aria-required="true"
                placeholder="Smith"
              />
            </div>
          </div>

          {/* Display name */}
          <div className="space-y-1">
            <Label htmlFor="display_name">Display name</Label>
            <Input
              id="display_name"
              value={form.display_name}
              onChange={(e) => set("display_name", e.target.value)}
              placeholder="Optional — overrides first name + surname in lists"
            />
          </div>

          {/* Email */}
          <div className="space-y-1">
            <Label htmlFor="email">Email *</Label>
            <Input
              id="email"
              type="email"
              value={form.email}
              onChange={(e) => set("email", e.target.value)}
              required
              aria-required="true"
              placeholder="jane@example.com"
            />
          </div>

          {/* DOB */}
          <div className="space-y-1">
            <Label htmlFor="dob">Date of birth</Label>
            <Input
              id="dob"
              type="date"
              value={form.dob}
              onChange={(e) => set("dob", e.target.value)}
            />
          </div>

          {/* Join date */}
          <div className="space-y-1">
            <Label htmlFor="join_date">Join date *</Label>
            <Input
              id="join_date"
              type="date"
              value={form.join_date}
              onChange={(e) => set("join_date", e.target.value)}
              required
              aria-required="true"
            />
          </div>

          {/* Status */}
          <div className="space-y-1">
            <Label htmlFor="membership_status_trigger">Status</Label>
            <Select
              value={form.membership_status}
              onValueChange={(v) => set("membership_status", v as MembershipStatus)}
            >
              <SelectTrigger
                id="membership_status_trigger"
                className="w-full"
                aria-label="Membership status"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {/* A new Member is never created archived. */}
                {MEMBERSHIP_STATUSES.filter((s) => s.value !== "archived").map(({ value, label }) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Emergency contact */}
          <div className="space-y-1">
            <Label htmlFor="emergency_contact_name">Emergency contact name</Label>
            <Input
              id="emergency_contact_name"
              value={form.emergency_contact_name}
              onChange={(e) => set("emergency_contact_name", e.target.value)}
              placeholder="Optional"
            />
          </div>

          <div className="space-y-1">
            <Label htmlFor="emergency_contact_phone">Emergency contact phone</Label>
            <Input
              id="emergency_contact_phone"
              type="tel"
              value={form.emergency_contact_phone}
              onChange={(e) => set("emergency_contact_phone", e.target.value)}
              placeholder="Optional"
            />
          </div>

          {/* Checkboxes */}
          <div className="flex flex-col gap-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                className="rounded"
                checked={form.is_coach}
                onChange={(e) => set("is_coach", e.target.checked)}
                aria-label="Is coach"
              />
              Coach
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input
                type="checkbox"
                className="rounded"
                checked={form.is_first_aider}
                onChange={(e) => set("is_first_aider", e.target.checked)}
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
        </form>

        <DialogFooter>
          <Button
            type="submit"
            form="add-member-form"
            disabled={saving}
            size="lg"
          >
            {saving ? "Saving…" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Member row (desktop table row) ────────────────────────────────────────────

type MemberRowProps = {
  member: MemberListItem
  onClick: () => void
}

const MemberRow = ({ member, onClick }: MemberRowProps) => (
  <tr
    className="border-b last:border-0 hover:bg-muted/50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    onClick={onClick}
    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick() }}
    tabIndex={0}
    role="row"
    aria-label={`View ${formatMemberName(member)}`}
  >
    <td className="py-3 pl-4 pr-2 font-medium">
      <div className="flex flex-col gap-0.5">
        <span>{formatMemberName(member)}</span>
        <span className="text-xs text-muted-foreground">{member.email}</span>
      </div>
    </td>
    <td className="py-3 px-2">
      <StatusBadge status={member.membership_status} />
    </td>
    <td className="py-3 px-2 text-muted-foreground">
      {member.current_grade ?? "—"}
    </td>
    <td className="py-3 px-2 hidden sm:table-cell">
      <RoleBadges member={member} />
    </td>
    <td className="py-3 pl-2 pr-4 text-sm text-muted-foreground hidden md:table-cell">
      {formatMemberDate(member.join_date)}
    </td>
  </tr>
)

// ── Member card (mobile) ──────────────────────────────────────────────────────

const MemberCard = ({ member, onClick }: MemberRowProps) => (
  <Card
    className="cursor-pointer hover:ring-ring/30 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
    onClick={onClick}
    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onClick() }}
    tabIndex={0}
    role="button"
    aria-label={`View ${formatMemberName(member)}`}
  >
    <CardContent className="py-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium truncate">{formatMemberName(member)}</p>
          <p className="text-xs text-muted-foreground truncate">{member.email}</p>
          <p className="text-xs text-muted-foreground truncate">{member.current_grade ?? "—"}</p>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <StatusBadge status={member.membership_status} />
            <RoleBadges member={member} />
          </div>
        </div>
        <span className="text-xs text-muted-foreground shrink-0">
          {formatShortDate(member.join_date)}
        </span>
      </div>
    </CardContent>
  </Card>
)

// ── Main page ─────────────────────────────────────────────────────────────────

const MembersPage = () => {
  const navigate = useNavigate()
  const [members, setMembers] = useState<MemberListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<MembershipStatus | "all">("all")
  const [addOpen, setAddOpen] = useState(false)

  const load = useCallback(() => {
    setError(null)
    const params = {
      ...(statusFilter !== "all" ? { status: statusFilter } : {}),
      ...(search.trim() ? { search: search.trim() } : {}),
    }
    listMembers(params)
      .then(setMembers)
      .catch((err: unknown) => {
        setError(isApiError(err) ? err.message : "Failed to load members")
      })
  }, [statusFilter, search])

  // Load on filter/search change (debounced for search)
  useEffect(() => {
    const timer = setTimeout(load, search ? 300 : 0)
    return () => clearTimeout(timer)
  }, [load, search])

  const handleCreated = (member: MemberResponse) => {
    setAddOpen(false)
    // A new Member has no Promotion yet, so no current Grade.
    const row = { ...member, current_grade: null }
    setMembers((prev) => (prev !== null ? [row, ...prev] : [row]))
  }

  return (
    <div className="px-4 py-6">
      {/* Header */}
      <div className="mb-6">
        <PageHeader
          title="Members"
          action={
            <Button
              size="lg"
              onClick={() => setAddOpen(true)}
              aria-label="Add member"
            >
              <PlusIcon aria-hidden="true" />
              <span className="hidden sm:inline">Add member</span>
            </Button>
          }
        />
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-2 mb-6">
        <div className="relative flex-1">
          <SearchIcon
            className="absolute left-2.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground pointer-events-none"
            aria-hidden="true"
          />
          <Input
            className="pl-8"
            placeholder="Search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search members"
          />
        </div>

        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as MembershipStatus | "all")}
        >
          <SelectTrigger aria-label="Filter by status" className="w-full sm:w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {MEMBERSHIP_STATUSES.map(({ value, label }) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Error */}
      {error !== null && (
        <p className="text-sm text-destructive mb-4" role="alert">
          {error}
        </p>
      )}

      {/* Loading */}
      {members === null && error === null && (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
          ))}
        </div>
      )}

      {/* Empty */}
      {members !== null && members.length === 0 && (
        <EmptyState
          message="No members found"
          actionLabel={search !== "" || statusFilter !== "all" ? "Clear filters" : null}
          onAction={
            search !== "" || statusFilter !== "all"
              ? () => { setSearch(""); setStatusFilter("all") }
              : null
          }
        />
      )}

      {/* Desktop table */}
      {members !== null && members.length > 0 && (
        <>
          {/* Hidden on mobile */}
          <div className="hidden sm:block rounded-xl ring-1 ring-foreground/10 overflow-hidden">
            <table
              className="w-full text-sm"
              role="table"
              aria-label="Members list"
            >
              <thead className="bg-muted/50">
                <tr role="row">
                  <th className="py-2.5 pl-4 pr-2 text-left font-medium text-muted-foreground" scope="col">Name</th>
                  <th className="py-2.5 px-2 text-left font-medium text-muted-foreground" scope="col">Status</th>
                  <th className="py-2.5 px-2 text-left font-medium text-muted-foreground" scope="col">Current Grade</th>
                  <th className="py-2.5 px-2 text-left font-medium text-muted-foreground hidden sm:table-cell" scope="col">Roles</th>
                  <th className="py-2.5 pl-2 pr-4 text-left font-medium text-muted-foreground hidden md:table-cell" scope="col">Joined</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m) => (
                  <MemberRow
                    key={m.id}
                    member={m}
                    onClick={() => navigate(`/members/${m.id}`)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <ul className="sm:hidden space-y-3" aria-label="Members list">
            {members.map((m) => (
              <li key={m.id}>
                <MemberCard
                  member={m}
                  onClick={() => navigate(`/members/${m.id}`)}
                />
              </li>
            ))}
          </ul>
        </>
      )}

      <AddMemberDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={handleCreated}
      />
    </div>
  )
}

export default MembersPage
