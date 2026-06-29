import { useEffect, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeSanitize from "rehype-sanitize"
import {
  getSessions,
  getSessionTypes,
  createSession,
  createSessionTemplate,
} from "@/api/sessions"
import type { SessionInstance, SessionType, SegmentInput } from "@/api/sessions"
import SegmentEditor from "@/components/SegmentEditor"
import { getMe } from "@/api/auth"
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
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { CalendarIcon } from "lucide-react"
import SessionCardList from "@/components/SessionCardList"
import CalendarView from "@/components/CalendarView"
import SessionsTable from "@/components/SessionsTable"

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

const DEFAULT_SEGMENT: SegmentInput = {
  start_time: "",
  duration_minutes: 90,
  coach_notes: null,
  type_ids: [],
}

const CreateSessionDialog = ({ sessionTypes, onCreated, onRefresh }: CreateDialogProps) => {
  const [open, setOpen] = useState(false)
  const [isRecurring, setIsRecurring] = useState(false)

  // Title
  const [title, setTitle] = useState("")

  // Segments (multi-segment editor)
  const [segments, setSegments] = useState<SegmentInput[]>([{ ...DEFAULT_SEGMENT }])

  // Common fields
  const [location, setLocation] = useState("")
  const [info, setInfo] = useState("")
  const [coachNotes, setCoachNotes] = useState("")
  const [infoPreview, setInfoPreview] = useState(false)
  const [coachNotesPreview, setCoachNotesPreview] = useState(false)

  // One-off
  const [date, setDate] = useState("")

  // Recurring
  const [startDate, setStartDate] = useState("")
  const [selectedDays, setSelectedDays] = useState<number[]>([])
  const [intervalWeeks, setIntervalWeeks] = useState<1 | 2>(1)

  // Form state
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const reset = () => {
    setIsRecurring(false)
    setTitle("")
    setSegments([{ ...DEFAULT_SEGMENT }])
    setLocation("")
    setInfo("")
    setCoachNotes("")
    setInfoPreview(false)
    setCoachNotesPreview(false)
    setDate("")
    setStartDate("")
    setSelectedDays([])
    setIntervalWeeks(1)
    setSubmitting(false)
    setFormError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)

    const trimmedTitle = title.trim()
    if (!trimmedTitle) {
      setFormError("Title is required.")
      return
    }
    if (segments.length === 0) {
      setFormError("At least one segment is required.")
      return
    }
    for (const seg of segments) {
      if (!seg.start_time) {
        setFormError("Each segment must have a start time.")
        return
      }
      if (seg.duration_minutes < 1) {
        setFormError("Each segment must have a positive duration.")
        return
      }
      if (seg.type_ids.length === 0) {
        setFormError("Each segment must have at least one session type.")
        return
      }
    }

    if (!isRecurring) {
      if (!date) {
        setFormError("Date is required.")
        return
      }
      setSubmitting(true)
      try {
        const created = await createSession({
          title: trimmedTitle,
          date,
          location: location.trim() || null,
          info: info.trim() || null,
          coach_notes: coachNotes.trim() || null,
          segments,
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
          title: trimmedTitle,
          start_date: startDate,
          recurrence_days: selectedDays,
          interval_weeks: intervalWeeks,
          location: location.trim() || null,
          info: info.trim() || null,
          coach_notes: coachNotes.trim() || null,
          segments,
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

          {/* Title */}
          <div className="space-y-1.5">
            <Label htmlFor="session-title">Title</Label>
            <Input
              id="session-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Monday evening practice"
              className="min-h-[44px]"
              required
            />
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

          {/* Recurring: start date */}
          {isRecurring && (
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
          )}

          {/* Segments */}
          <div className="space-y-1.5">
            <Label>Segments</Label>
            <SegmentEditor
              segments={segments}
              sessionTypes={sessionTypes}
              onChange={setSegments}
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

// ── iCal popover button ────────────────────────────────────────────────────────

type ICalButtonProps = {
  icalUrl: string
}

const ICalButton = ({ icalUrl }: ICalButtonProps) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(icalUrl).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <Popover>
      <PopoverTrigger render={<Button variant="outline" size="sm" aria-label="Subscribe to iCal feed" className="shrink-0" />}>
        <CalendarIcon className="h-4 w-4" />
      </PopoverTrigger>
      <PopoverContent className="w-80" align="end">
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            Subscribe in Google Calendar, Apple Calendar, or Outlook using this URL
          </p>
          <div className="flex gap-2">
            <Input
              readOnly
              value={icalUrl}
              className="text-xs font-mono"
              aria-label="iCal feed URL"
              onFocus={(e) => e.target.select()}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopy}
              className="shrink-0"
            >
              {copied ? "Copied!" : "Copy"}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}

// ── Sessions page ─────────────────────────────────────────────────────────────

type PageView = "list" | "calendar"

const SessionsPage = () => {
  const [sessions, setSessions] = useState<SessionInstance[] | null>(null)
  const [sessionTypes, setSessionTypes] = useState<SessionType[]>([])
  const [typeMap, setTypeMap] = useState<Map<string, SessionType>>(new Map())
  const [role, setRole] = useState<"admin" | "member" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pageView, setPageView] = useState<PageView>("list")

  useEffect(() => {
    Promise.all([getSessions(), getSessionTypes(), getMe()])
      .then(([fetchedSessions, fetchedTypes, me]) => {
        setSessions(fetchedSessions)
        setSessionTypes(fetchedTypes)
        setTypeMap(
          new Map(fetchedTypes.map((t: SessionType) => [t.id, t]))
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

  if (error !== null) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (sessions === null) {
    return (
      <div className="px-4 py-6 space-y-4">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-20 w-full rounded-xl" />
      </div>
    )
  }

  const isAdmin = role === "admin"

  return (
    <div className={pageView === "calendar" ? "flex flex-col h-screen px-0 py-0" : "px-4 py-6 space-y-6"}>
      {/* Page toolbar */}
      <div className={pageView === "calendar" ? "flex items-center justify-between gap-4 px-4 py-3 border-b shrink-0" : "flex items-center justify-between gap-4"}>
        <h1 className="text-xl font-semibold">Sessions</h1>
        <div className="flex items-center gap-2">
          {/* List / Calendar toggle — desktop only */}
          <div className="hidden md:flex items-center gap-1">
            <Button
              variant={pageView === "list" ? "default" : "outline"}
              size="sm"
              onClick={() => setPageView("list")}
              aria-pressed={pageView === "list"}
            >
              List
            </Button>
            <Button
              variant={pageView === "calendar" ? "default" : "outline"}
              size="sm"
              onClick={() => setPageView("calendar")}
              aria-pressed={pageView === "calendar"}
            >
              Calendar
            </Button>
          </div>
          {role !== null && <ICalButton icalUrl={icalUrl} />}
          {isAdmin && (
            <CreateSessionDialog
              sessionTypes={sessionTypes}
              onCreated={handleCreated}
              onRefresh={refreshSessions}
            />
          )}
        </div>
      </div>

      {pageView === "calendar" ? (
        <CalendarView isAdmin={isAdmin} />
      ) : (
        <>
          {/* Mobile: card list */}
          <div className="md:hidden">
            <SessionCardList sessions={sessions} typeMap={typeMap} role={role} />
          </div>
          {/* Desktop: data table */}
          <div className="hidden md:block">
            <SessionsTable sessions={sessions} typeMap={typeMap} isAdmin={isAdmin} />
          </div>
        </>
      )}
    </div>
  )
}

export default SessionsPage
