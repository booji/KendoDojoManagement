import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeSanitize from "rehype-sanitize"
import {
  getSessions,
  getSessionTypes,
  createSession,
  createSessionTemplate,
  createSessionType,
} from "@/api/sessions"
import type { SessionInstance, SessionType } from "@/api/sessions"
import { getMe } from "@/api/auth"
import {
  checkIn,
  getCheckinToken,
  getSessionAttendance,
  markAttended,
  removeAttendance,
  addVisitor,
} from "@/api/attendance"
import type { AttendanceRecord } from "@/api/attendance"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Checkbox } from "@/components/ui/checkbox"
import { ChevronDownIcon, ChevronUpIcon } from "lucide-react"

// Returns the Monday of the week containing the given date (local time)
const startOfWeek = (date: Date): Date => {
  const d = new Date(date)
  const day = d.getDay() // 0=Sun, 1=Mon, …
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

const weekLabel = (weekStart: Date): string => {
  const day = weekStart.getDate()
  const month = weekStart.toLocaleString("default", { month: "short" })
  return `Week of ${day} ${month}`
}

// Group sessions by the Monday of their week, preserving order
const groupByWeek = (
  sessions: SessionInstance[]
): { label: string; sessions: SessionInstance[] }[] => {
  const map = new Map<string, { label: string; sessions: SessionInstance[] }>()
  for (const s of sessions) {
    const date = new Date(`${s.date}T${s.start_time}`)
    const monday = startOfWeek(date)
    const key = monday.toISOString()
    if (!map.has(key)) {
      map.set(key, { label: weekLabel(monday), sessions: [] })
    }
    map.get(key)!.sessions.push(s)
  }
  return Array.from(map.values())
}

const formatTime = (startTime: string): string => {
  return startTime
}

const formatDate = (date: string): string => {
  const d = new Date(`${date}T00:00:00`)
  return d.toLocaleDateString("default", { weekday: "short", day: "numeric", month: "short" })
}

// Per-session check-in UI state
type CheckinState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success" }
  | { kind: "error"; message: string }

type ShareState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "url"; url: string }
  | { kind: "error"; message: string }

type SessionCardActionsProps = {
  session: SessionInstance
  isAdmin: boolean
}

const SessionCardActions = ({ session, isAdmin }: SessionCardActionsProps) => {
  const [checkinState, setCheckinState] = useState<CheckinState>({ kind: "idle" })
  const [shareState, setShareState] = useState<ShareState>({ kind: "idle" })

  const handleCheckIn = async () => {
    setCheckinState({ kind: "loading" })
    try {
      await checkIn(session.id)
      setCheckinState({ kind: "success" })
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to check in"
      setCheckinState({ kind: "error", message })
    }
  }

  const handleShare = async () => {
    setShareState({ kind: "loading" })
    try {
      const tokenData = await getCheckinToken(session.id)
      const url = `${window.location.origin}/checkin/${tokenData.token}`
      setShareState({ kind: "url", url })
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to get check-in link"
      setShareState({ kind: "error", message })
    }
  }

  return (
    <div className="mt-3 space-y-2">
      {/* Check-in button — full width, thumb-friendly */}
      {checkinState.kind === "success" ? (
        <div
          className="flex items-center justify-center w-full min-h-[48px] rounded-md bg-green-100 text-green-800 font-medium text-sm dark:bg-green-900/30 dark:text-green-300"
          role="status"
          aria-live="polite"
        >
          Checked in!
        </div>
      ) : (
        <Button
          size="lg"
          className="w-full min-h-[48px]"
          onClick={handleCheckIn}
          disabled={checkinState.kind === "loading"}
          aria-label="Check in to this session"
        >
          {checkinState.kind === "loading" ? "Checking in…" : "Check In"}
        </Button>
      )}
      {checkinState.kind === "error" && (
        <p className="text-xs text-destructive" role="alert">
          {checkinState.message}
        </p>
      )}

      {/* Admin-only: share check-in link */}
      {isAdmin && (
        <>
          {shareState.kind === "url" ? (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">Share this check-in link:</p>
              <Input
                readOnly
                value={shareState.url}
                aria-label="Check-in link"
                onFocus={(e) => e.target.select()}
                className="text-xs"
              />
            </div>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={handleShare}
              disabled={shareState.kind === "loading"}
              aria-label="Share check-in link for this session"
            >
              {shareState.kind === "loading" ? "Getting link…" : "Share check-in link"}
            </Button>
          )}
          {shareState.kind === "error" && (
            <p className="text-xs text-destructive" role="alert">
              {shareState.message}
            </p>
          )}

          <SessionAttendancePanel sessionId={session.id} />
        </>
      )}
    </div>
  )
}

// ── Session attendance panel (admin only) ─────────────────────────────────────

type AttendancePanelState =
  | { kind: "closed" }
  | { kind: "loading" }
  | { kind: "loaded"; records: AttendanceRecord[] }
  | { kind: "error"; message: string }

type SessionAttendancePanelProps = {
  sessionId: string
}

const SessionAttendancePanel = ({ sessionId }: SessionAttendancePanelProps) => {
  const [panel, setPanel] = useState<AttendancePanelState>({ kind: "closed" })
  const [memberIdInput, setMemberIdInput] = useState("")
  const [markingError, setMarkingError] = useState<string | null>(null)
  const [marking, setMarking] = useState(false)
  const [visitorInput, setVisitorInput] = useState("")
  const [addingVisitor, setAddingVisitor] = useState(false)
  const [visitorError, setVisitorError] = useState<string | null>(null)

  const open = panel.kind !== "closed"

  const load = async () => {
    setPanel({ kind: "loading" })
    try {
      const records = await getSessionAttendance(sessionId)
      setPanel({ kind: "loaded", records })
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to load attendance"
      setPanel({ kind: "error", message })
    }
  }

  const toggle = () => {
    if (open) {
      setPanel({ kind: "closed" })
    } else {
      void load()
    }
  }

  const handleRemove = async (memberId: string) => {
    try {
      await removeAttendance(sessionId, memberId)
      setPanel((prev) =>
        prev.kind === "loaded"
          ? { kind: "loaded", records: prev.records.filter((r) => r.member_id !== memberId) }
          : prev
      )
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to remove"
      setMarkingError(message)
    }
  }

  const handleMarkAttended = async (e: React.FormEvent) => {
    e.preventDefault()
    const id = memberIdInput.trim()
    if (!id) return
    setMarkingError(null)
    setMarking(true)
    try {
      const record = await markAttended(sessionId, id)
      setPanel((prev) =>
        prev.kind === "loaded"
          ? { kind: "loaded", records: [...prev.records, record] }
          : prev
      )
      setMemberIdInput("")
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to mark attended"
      setMarkingError(message)
    } finally {
      setMarking(false)
    }
  }

  const handleAddVisitor = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = visitorInput.trim()
    if (!name) return
    setVisitorError(null)
    setAddingVisitor(true)
    try {
      const record = await addVisitor(sessionId, name)
      setPanel((prev) =>
        prev.kind === "loaded"
          ? { kind: "loaded", records: [...prev.records, record] }
          : prev
      )
      setVisitorInput("")
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to add visitor"
      setVisitorError(message)
    } finally {
      setAddingVisitor(false)
    }
  }

  return (
    <div className="mt-2 border-t pt-3">
      <button
        type="button"
        className="flex w-full items-center justify-between text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
        onClick={toggle}
        aria-expanded={open}
        aria-controls="attendance-panel"
      >
        <span>Attendance</span>
        {open ? (
          <ChevronUpIcon className="h-4 w-4" aria-hidden="true" />
        ) : (
          <ChevronDownIcon className="h-4 w-4" aria-hidden="true" />
        )}
      </button>

      {open && (
        <div id="attendance-panel" className="mt-3 space-y-4">
          {panel.kind === "loading" && (
            <div className="space-y-2">
              <Skeleton className="h-5 w-full" />
              <Skeleton className="h-5 w-3/4" />
            </div>
          )}

          {panel.kind === "error" && (
            <p className="text-xs text-destructive" role="alert">{panel.message}</p>
          )}

          {panel.kind === "loaded" && (
            <>
              {panel.records.length === 0 ? (
                <p className="text-xs text-muted-foreground">No attendees yet</p>
              ) : (
                <ul className="space-y-1" aria-label="Attendance list">
                  {panel.records.map((record) => (
                    <li
                      key={record.id}
                      className="flex items-center justify-between gap-2 text-xs"
                    >
                      <span className="truncate font-mono min-w-0">
                        {record.visitor_name !== null
                          ? record.visitor_name
                          : record.member_id !== null
                            ? record.member_id.slice(0, 8) + "…"
                            : "Unknown"}
                      </span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {record.visitor_name !== null && (
                          <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
                            Visitor
                          </span>
                        )}
                        {record.member_id !== null && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2 text-xs text-destructive hover:text-destructive"
                            onClick={() => void handleRemove(record.member_id!)}
                            aria-label={`Remove attendance for ${record.member_id?.slice(0, 8)}`}
                          >
                            Remove
                          </Button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {/* Mark member attended */}
              <form onSubmit={(e) => void handleMarkAttended(e)} className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Mark member attended
                </p>
                <div className="flex gap-2">
                  <Input
                    placeholder="Member ID"
                    value={memberIdInput}
                    onChange={(e) => setMemberIdInput(e.target.value)}
                    className="min-h-[44px] flex-1 text-sm"
                    aria-label="Member ID to mark attended"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={marking || memberIdInput.trim() === ""}
                    className="min-h-[44px] shrink-0"
                    aria-label="Mark member attended"
                  >
                    {marking ? "…" : "Mark Attended"}
                  </Button>
                </div>
                {markingError !== null && (
                  <p className="text-xs text-destructive" role="alert">{markingError}</p>
                )}
              </form>

              {/* Add visitor */}
              <form onSubmit={(e) => void handleAddVisitor(e)} className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Add visitor
                </p>
                <div className="flex gap-2">
                  <Input
                    placeholder="Visitor name"
                    value={visitorInput}
                    onChange={(e) => setVisitorInput(e.target.value)}
                    className="min-h-[44px] flex-1 text-sm"
                    aria-label="Visitor name"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={addingVisitor || visitorInput.trim() === ""}
                    className="min-h-[44px] shrink-0"
                    aria-label="Add visitor"
                  >
                    {addingVisitor ? "…" : "Add Visitor"}
                  </Button>
                </div>
                {visitorError !== null && (
                  <p className="text-xs text-destructive" role="alert">{visitorError}</p>
                )}
              </form>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Markdown preview field ─────────────────────────────────────────────────────

type MarkdownFieldProps = {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  preview: boolean
  onTogglePreview: () => void
  placeholder?: string
}

const MarkdownField = ({
  id,
  label,
  value,
  onChange,
  preview,
  onTogglePreview,
  placeholder,
}: MarkdownFieldProps) => (
  <div className="space-y-1.5">
    <div className="flex items-center justify-between gap-2">
      <Label htmlFor={id}>{label}</Label>
      <button
        type="button"
        className="text-xs text-muted-foreground hover:text-foreground transition-colors underline-offset-2 hover:underline"
        onClick={onTogglePreview}
      >
        {preview ? "Edit" : "Preview"}
      </button>
    </div>
    {preview ? (
      <div className="min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm prose prose-sm max-w-none">
        {value.trim() ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{value}</ReactMarkdown>
        ) : (
          <span className="text-muted-foreground italic">Nothing to preview</span>
        )}
      </div>
    ) : (
      <Textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="min-h-[80px]"
      />
    )}
  </div>
)

// ── Day-of-week selector ───────────────────────────────────────────────────────

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

type DayPickerProps = {
  selected: number[]
  onChange: (days: number[]) => void
}

const DayPicker = ({ selected, onChange }: DayPickerProps) => (
  <div className="flex flex-wrap gap-3" role="group" aria-label="Recurrence days">
    {DAY_LABELS.map((label, idx) => {
      const checked = selected.includes(idx)
      return (
        <label
          key={idx}
          className="flex items-center gap-1.5 cursor-pointer select-none min-h-[44px]"
        >
          <Checkbox
            checked={checked}
            onCheckedChange={(v) => {
              if (v) {
                onChange([...selected, idx].sort((a, b) => a - b))
              } else {
                onChange(selected.filter((d) => d !== idx))
              }
            }}
          />
          <span className="text-sm">{label}</span>
        </label>
      )
    })}
  </div>
)

// ── Create session dialog ──────────────────────────────────────────────────────

type CreateDialogProps = {
  sessionTypes: SessionType[]
  onCreated: (session: SessionInstance) => void
  onRefresh: () => void
}

const CreateSessionDialog = ({ sessionTypes, onCreated, onRefresh }: CreateDialogProps) => {
  const [open, setOpen] = useState(false)
  const [isRecurring, setIsRecurring] = useState(false)

  // Session type
  const [typeId, setTypeId] = useState("")
  const [newTypeName, setNewTypeName] = useState("")
  const [showNewTypeInput, setShowNewTypeInput] = useState(false)
  const [creatingType, setCreatingType] = useState(false)
  const [localTypes, setLocalTypes] = useState<SessionType[]>(sessionTypes)

  // Common fields
  const [time, setTime] = useState("")
  const [duration, setDuration] = useState("90")
  const [location, setLocation] = useState("")
  const [info, setInfo] = useState("")
  const [coachNotes, setCoachNotes] = useState("")
  const [infoPreview, setInfoPreview] = useState(false)
  const [coachNotesPreview, setCoachNotesPreview] = useState(false)

  // One-off
  const [date, setDate] = useState("")

  // Recurring
  const [recurringTitle, setRecurringTitle] = useState("")
  const [startDate, setStartDate] = useState("")
  const [selectedDays, setSelectedDays] = useState<number[]>([])
  const [intervalWeeks, setIntervalWeeks] = useState<1 | 2>(1)

  // Form state
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  // Keep localTypes in sync when prop changes (e.g. initial load)
  useEffect(() => {
    setLocalTypes(sessionTypes)
  }, [sessionTypes])

  const reset = () => {
    setIsRecurring(false)
    setTypeId("")
    setNewTypeName("")
    setShowNewTypeInput(false)
    setCreatingType(false)
    setTime("")
    setDuration("90")
    setLocation("")
    setInfo("")
    setCoachNotes("")
    setInfoPreview(false)
    setCoachNotesPreview(false)
    setDate("")
    setRecurringTitle("")
    setStartDate("")
    setSelectedDays([])
    setIntervalWeeks(1)
    setSubmitting(false)
    setFormError(null)
  }

  const handleAddType = async () => {
    const name = newTypeName.trim()
    if (!name) return
    setCreatingType(true)
    try {
      const newType = await createSessionType(name)
      setLocalTypes((prev) => [...prev, newType])
      setTypeId(newType.id)
      setNewTypeName("")
      setShowNewTypeInput(false)
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to create session type"
      setFormError(message)
    } finally {
      setCreatingType(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    const mins = parseInt(duration, 10)
    if (!typeId) {
      setFormError("Please select a session type.")
      return
    }
    if (!time) {
      setFormError("Start time is required.")
      return
    }
    if (isNaN(mins) || mins < 1) {
      setFormError("Duration must be a positive number.")
      return
    }

    if (!isRecurring) {
      if (!date) {
        setFormError("Date is required.")
        return
      }
      setSubmitting(true)
      try {
        const created = await createSession({
          session_type_id: typeId,
          date,
          start_time: time,
          duration_minutes: mins,
          location: location.trim() || null,
          info: info.trim() || null,
          coach_notes: coachNotes.trim() || null,
        })
        onCreated(created)
        setOpen(false)
        reset()
      } catch (err) {
        const message =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : "Failed to create session"
        setFormError(message)
      } finally {
        setSubmitting(false)
      }
    } else {
      if (!startDate) {
        setFormError("Start date is required.")
        return
      }
      if (selectedDays.length === 0) {
        setFormError("Select at least one day of the week.")
        return
      }
      setSubmitting(true)
      try {
        await createSessionTemplate({
          session_type_id: typeId,
          title: recurringTitle.trim() || "Recurring session",
          start_date: startDate,
          start_time: time,
          duration_minutes: mins,
          recurrence_days: selectedDays,
          interval_weeks: intervalWeeks,
          location: location.trim() || null,
          info: info.trim() || null,
          coach_notes: coachNotes.trim() || null,
        })
        onRefresh()
        setOpen(false)
        reset()
      } catch (err) {
        const message =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : "Failed to create session template"
        setFormError(message)
      } finally {
        setSubmitting(false)
      }
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) reset() }}>
      <DialogTrigger render={<Button size="sm" />}>
        Create Session
      </DialogTrigger>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create Session</DialogTitle>
        </DialogHeader>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4 mt-2">

          {/* Session type */}
          <div className="space-y-1.5">
            <Label htmlFor="session-type">Session type</Label>
            <Select value={typeId} onValueChange={(v) => { if (v !== null) setTypeId(v) }}>
              <SelectTrigger id="session-type" className="min-h-[44px]">
                <SelectValue placeholder="Select type…" />
              </SelectTrigger>
              <SelectContent>
                {localTypes.map((t) => (
                  <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {showNewTypeInput ? (
              <div className="flex gap-2 mt-1">
                <Input
                  value={newTypeName}
                  onChange={(e) => setNewTypeName(e.target.value)}
                  placeholder="New type name"
                  className="min-h-[44px] flex-1 text-sm"
                  aria-label="New session type name"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      void handleAddType()
                    }
                    if (e.key === "Escape") {
                      setShowNewTypeInput(false)
                      setNewTypeName("")
                    }
                  }}
                />
                <Button
                  type="button"
                  size="sm"
                  className="min-h-[44px] shrink-0"
                  onClick={() => void handleAddType()}
                  disabled={creatingType || newTypeName.trim() === ""}
                >
                  {creatingType ? "Adding…" : "Add"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="min-h-[44px] shrink-0"
                  onClick={() => { setShowNewTypeInput(false); setNewTypeName("") }}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <button
                type="button"
                className="text-xs text-muted-foreground hover:text-foreground transition-colors underline-offset-2 hover:underline mt-1"
                onClick={() => setShowNewTypeInput(true)}
              >
                Add new type…
              </button>
            )}
          </div>

          {/* Recurring toggle */}
          <label className="flex items-center gap-2 cursor-pointer min-h-[44px]">
            <Checkbox
              checked={isRecurring}
              onCheckedChange={(v) => setIsRecurring(v)}
            />
            <span className="text-sm font-medium">Recurring session</span>
          </label>

          {/* One-off: date */}
          {!isRecurring && (
            <div className="space-y-1.5">
              <Label htmlFor="session-date">Date</Label>
              <Input
                id="session-date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="min-h-[44px]"
              />
            </div>
          )}

          {/* Recurring: title, start date, days, interval */}
          {isRecurring && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="recurring-title">Template title (optional)</Label>
                <Input
                  id="recurring-title"
                  value={recurringTitle}
                  onChange={(e) => setRecurringTitle(e.target.value)}
                  placeholder="e.g. Monday evening practice"
                  className="min-h-[44px]"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="start-date">Start date</Label>
                <Input
                  id="start-date"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="min-h-[44px]"
                />
              </div>
            </>
          )}

          {/* Start time */}
          <div className="space-y-1.5">
            <Label htmlFor="session-time">Start time</Label>
            <Input
              id="session-time"
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className="min-h-[44px]"
            />
          </div>

          {/* Duration */}
          <div className="space-y-1.5">
            <Label htmlFor="session-duration">Duration (minutes)</Label>
            <Input
              id="session-duration"
              type="number"
              min={1}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
              className="min-h-[44px]"
            />
          </div>

          {/* Recurring: days + interval */}
          {isRecurring && (
            <>
              <div className="space-y-1.5">
                <Label>Days of week</Label>
                <DayPicker selected={selectedDays} onChange={setSelectedDays} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="interval-weeks">Recurrence</Label>
                <Select
                  value={String(intervalWeeks)}
                  onValueChange={(v) => setIntervalWeeks(v === "2" ? 2 : 1)}
                >
                  <SelectTrigger id="interval-weeks" className="min-h-[44px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">Weekly</SelectItem>
                    <SelectItem value="2">Bi-weekly</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {/* Location */}
          <div className="space-y-1.5">
            <Label htmlFor="session-location">Location (optional)</Label>
            <Input
              id="session-location"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Main dojo"
              className="min-h-[44px]"
            />
          </div>

          {/* Info (markdown) */}
          <MarkdownField
            id="session-info"
            label="Info (optional, markdown)"
            value={info}
            onChange={setInfo}
            preview={infoPreview}
            onTogglePreview={() => setInfoPreview((p) => !p)}
            placeholder="Session info visible to members…"
          />

          {/* Coach notes (markdown) */}
          <MarkdownField
            id="session-coach-notes"
            label="Coach notes (optional, markdown)"
            value={coachNotes}
            onChange={setCoachNotes}
            preview={coachNotesPreview}
            onTogglePreview={() => setCoachNotesPreview((p) => !p)}
            placeholder="Internal notes for coaches…"
          />

          {formError !== null && (
            <p className="text-sm text-destructive" role="alert">{formError}</p>
          )}

          <Button type="submit" className="w-full min-h-[44px]" disabled={submitting}>
            {submitting ? "Creating…" : "Create Session"}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ── Sessions page ─────────────────────────────────────────────────────────────

const SessionsPage = () => {
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<SessionInstance[] | null>(null)
  const [sessionTypes, setSessionTypes] = useState<SessionType[]>([])
  const [typeMap, setTypeMap] = useState<Map<string, string>>(new Map())
  const [role, setRole] = useState<"admin" | "member" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [icalCopied, setIcalCopied] = useState(false)

  useEffect(() => {
    Promise.all([getSessions(), getSessionTypes(), getMe()])
      .then(([fetchedSessions, fetchedTypes, me]) => {
        setSessions(fetchedSessions)
        setSessionTypes(fetchedTypes)
        setTypeMap(
          new Map(fetchedTypes.map((t: SessionType) => [t.id, t.name]))
        )
        setRole(me.role)
      })
      .catch(() => {
        setError("Failed to load sessions. Please try again.")
      })
  }, [])

  const handleCreated = (session: SessionInstance) => {
    setSessions((prev) =>
      prev === null
        ? [session]
        : [...prev, session].sort(
            (a, b) =>
              new Date(`${a.date}T${a.start_time}`).getTime() -
              new Date(`${b.date}T${b.start_time}`).getTime(),
          ),
    )
  }

  const refreshSessions = () => {
    getSessions().then(setSessions).catch(() => {
      setError("Failed to refresh sessions.")
    })
  }

  const icalUrl = `${window.location.origin}/api/sessions/ical`

  const handleCopyIcal = () => {
    navigator.clipboard.writeText(icalUrl).then(() => {
      setIcalCopied(true)
      setTimeout(() => setIcalCopied(false), 2000)
    })
  }

  if (error !== null) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (sessions === null) {
    return (
      <div className="px-4 py-6 space-y-4 max-w-2xl mx-auto">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-20 w-full rounded-xl" />
      </div>
    )
  }

  const isAdmin = role === "admin"
  const groups = groupByWeek(sessions)

  return (
    <div className="px-4 py-6 space-y-8 max-w-2xl mx-auto">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">Sessions</h1>
        {isAdmin && (
          <CreateSessionDialog
            sessionTypes={sessionTypes}
            onCreated={handleCreated}
            onRefresh={refreshSessions}
          />
        )}
      </div>

      {role !== null && (
        <Card>
          <CardContent className="py-4 space-y-2">
            <p className="text-xs text-muted-foreground">
              Subscribe in Google Calendar, Apple Calendar, or Outlook using this URL
            </p>
            <div className="flex gap-2">
              <Input
                readOnly
                value={icalUrl}
                className="text-xs font-mono"
                aria-label="iCal feed URL"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={handleCopyIcal}
                className="shrink-0"
              >
                {icalCopied ? "Copied!" : "Copy"}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {sessions.length === 0 && (
        <p className="text-sm text-muted-foreground">No upcoming sessions.</p>
      )}

      {groups.map((group) => (
        <section key={group.label}>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {group.label}
          </h2>
          <ul className="space-y-3">
            {group.sessions.map((session) => {
              const cancelled = session.cancelled
              return (
                <li key={session.id}>
                  <Card
                    className={`cursor-pointer${cancelled ? " opacity-60" : ""}`}
                    onClick={() => navigate(`/sessions/${session.id}`)}
                  >
                    <CardContent className="py-3">
                      <div
                        className={
                          cancelled ? "line-through text-muted-foreground" : undefined
                        }
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="font-medium truncate">
                              {typeMap.get(session.session_type_id) ?? "Unknown"}
                            </p>
                            <p className="text-sm text-muted-foreground mt-0.5">
                              {formatDate(session.date)}&nbsp;&middot;&nbsp;
                              {formatTime(session.start_time)}&nbsp;&middot;&nbsp;
                              {session.duration_minutes} min
                            </p>
                            {session.location !== null && (
                              <p className="text-sm text-muted-foreground mt-0.5">
                                {session.location}
                              </p>
                            )}
                          </div>
                          {cancelled && (
                            <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                              Cancelled
                            </span>
                          )}
                        </div>
                      </div>
                      {!cancelled && (
                        <div onClick={(e) => e.stopPropagation()}>
                          <SessionCardActions session={session} isAdmin={isAdmin} />
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}

export default SessionsPage
