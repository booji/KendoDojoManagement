import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeSanitize from "rehype-sanitize"
import {
  getSession,
  updateSession,
  cancelSession,
  deleteTemplate,
  getSessionTypes,
  getSessionTemplate,
  extendSessionTemplate,
} from "@/api/sessions"
import type { SessionInstance, SessionInstanceUpdate, SessionType, SegmentInput, SessionTemplate } from "@/api/sessions"
import { getDojoSettings } from "@/api/settings"
import type { DojoSettings } from "@/api/settings"
import CopyButton from "@/components/CopyButton"
import SegmentEditor from "@/components/SegmentEditor"
import { getMe } from "@/api/auth"
import { checkIn, getSessionAttendance } from "@/api/attendance"
import type { AttendanceRecord } from "@/api/attendance"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent } from "@/components/ui/card"
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { ChevronDown, ChevronRight } from "lucide-react"
import { PageHeader } from "@/components/ui/page-header"

// ── Extend series control ───────────────────────────────────────────────────────

type ExtendSeriesControlProps = {
  templateId: string
  currentEndDate: string
  onExtended: (updated: SessionTemplate) => void
}

const ExtendSeriesControl = ({ templateId, currentEndDate, onExtended }: ExtendSeriesControlProps) => {
  const [open, setOpen] = useState(false)
  const [newEndDate, setNewEndDate] = useState(currentEndDate)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleExtend = async () => {
    setError(null)
    setSubmitting(true)
    try {
      const updated = await extendSessionTemplate(templateId, newEndDate)
      onExtended(updated)
      setOpen(false)
    } catch (err) {
      setError(
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to extend series",
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Popover open={open} onOpenChange={(v) => { setOpen(v); if (v) { setNewEndDate(currentEndDate); setError(null) } }}>
      <PopoverTrigger render={<Button variant="outline" className="min-h-[44px]" />}>
        Extend Series
      </PopoverTrigger>
      <PopoverContent className="w-72" align="end">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="extend-end-date">New end date</Label>
            <Input
              id="extend-end-date"
              type="date"
              value={newEndDate}
              onChange={(e) => setNewEndDate(e.target.value)}
              className="min-h-[44px]"
            />
          </div>
          {error !== null && (
            <p className="text-sm text-destructive" role="alert">{error}</p>
          )}
          <Button
            className="w-full min-h-[44px]"
            onClick={() => void handleExtend()}
            disabled={submitting}
          >
            {submitting ? "Extending…" : "Confirm Extend"}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

// ── MarkdownField ─────────────────────────────────────────────────────────────

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

const CHECKIN_WINDOW_MAX_MINUTES = 1440

// Blank means "no override — fall back to the live dojo default", so it
// must resolve to `null` rather than being rejected as invalid.
const parseCheckinWindowMinutes = (raw: string, label: string): number | null => {
  const trimmed = raw.trim()
  if (trimmed === "") return null
  if (!/^\d+$/.test(trimmed)) {
    throw new Error(`${label} must be a whole number of minutes.`)
  }
  const n = Number(trimmed)
  if (n > CHECKIN_WINDOW_MAX_MINUTES) {
    throw new Error(`${label} must be at most ${CHECKIN_WINDOW_MAX_MINUTES} minutes.`)
  }
  return n
}

// ── Edit form ─────────────────────────────────────────────────────────────────

type EditFormProps = {
  session: SessionInstance
  sessionTypes: SessionType[]
  onSave: (updated: SessionInstance) => void
  onCancel: () => void
}

const EditForm = ({ session, sessionTypes, onSave, onCancel }: EditFormProps) => {
  const [title, setTitle] = useState(session.title)
  const [date, setDate] = useState(session.date)
  // Deep copy of segments — SegmentEditor manages its own internal draft state,
  // but we keep a copy here so we can include it in the submit payload.
  const [segments, setSegments] = useState<SegmentInput[]>(
    session.segments.map((s) => ({
      start_time: s.start_time,
      duration_minutes: s.duration_minutes,
      title: s.title,
      type_ids: [...s.type_ids],
    })),
  )
  const [location, setLocation] = useState(session.location ?? "")
  const [notes, setNotes] = useState(session.notes ?? "")
  const [info, setInfo] = useState(session.info ?? "")
  const [infoPreview, setInfoPreview] = useState(false)
  const [coachNotes, setCoachNotes] = useState(session.coach_notes ?? "")
  const [coachNotesPreview, setCoachNotesPreview] = useState(false)
  const [checkinBefore, setCheckinBefore] = useState(
    session.checkin_window_before_minutes != null
      ? String(session.checkin_window_before_minutes)
      : "",
  )
  const [checkinAfter, setCheckinAfter] = useState(
    session.checkin_window_after_minutes != null
      ? String(session.checkin_window_after_minutes)
      : "",
  )
  const [dojoSettings, setDojoSettings] = useState<DojoSettings | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getDojoSettings()
      .then(setDojoSettings)
      .catch(() => {
        // Placeholders simply stay blank if defaults can't be fetched.
      })
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (!title.trim()) {
      setError("Title is required.")
      return
    }
    if (segments.length === 0) {
      setError("At least one segment is required.")
      return
    }
    for (const seg of segments) {
      if (!seg.start_time) {
        setError("Each segment must have a start time.")
        return
      }
      if (seg.duration_minutes < 1) {
        setError("Each segment must have a positive duration.")
        return
      }
      if (seg.type_ids.length === 0) {
        setError("Each segment must have at least one session type.")
        return
      }
    }

    let checkinWindowBeforeMinutes: number | null
    let checkinWindowAfterMinutes: number | null
    try {
      checkinWindowBeforeMinutes = parseCheckinWindowMinutes(
        checkinBefore,
        "Check-in opens before",
      )
      checkinWindowAfterMinutes = parseCheckinWindowMinutes(
        checkinAfter,
        "Check-in closes after",
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid check-in window value.")
      return
    }

    setSubmitting(true)
    try {
      const payload: Partial<SessionInstanceUpdate> = {
        title: title.trim(),
        date,
        location: location.trim() || null,
        notes: notes.trim() || null,
        info: info.trim() || null,
        coach_notes: coachNotes.trim() || null,
        segments,
        checkin_window_before_minutes: checkinWindowBeforeMinutes,
        checkin_window_after_minutes: checkinWindowAfterMinutes,
      }
      const updated = await updateSession(session.id, payload)
      onSave(updated)
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to save"
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4 mt-4">
      <div className="space-y-1.5">
        <Label htmlFor="edit-title">Title</Label>
        <Input
          id="edit-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="min-h-[44px]"
          required
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="edit-date">Date</Label>
        <Input
          id="edit-date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="min-h-[44px]"
          required
        />
      </div>
      <div className="space-y-1.5">
        <Label>Segments</Label>
        <SegmentEditor
          segments={segments}
          sessionTypes={sessionTypes}
          onChange={setSegments}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="edit-location">Location</Label>
        <Input
          id="edit-location"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className="min-h-[44px]"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="edit-notes">Notes</Label>
        <Input
          id="edit-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="min-h-[44px]"
        />
      </div>
      <MarkdownField
        id="edit-info"
        label="Info (optional, markdown)"
        value={info}
        onChange={setInfo}
        preview={infoPreview}
        onTogglePreview={() => setInfoPreview(p => !p)}
        placeholder="Session info visible to members…"
      />
      <MarkdownField
        id="edit-coach-notes"
        label="Coach notes (optional, markdown)"
        value={coachNotes}
        onChange={setCoachNotes}
        preview={coachNotesPreview}
        onTogglePreview={() => setCoachNotesPreview(p => !p)}
        placeholder="Internal notes for coaches…"
      />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label htmlFor="edit-checkin-before">Check-in opens before (minutes)</Label>
          <Input
            id="edit-checkin-before"
            type="number"
            min={0}
            max={CHECKIN_WINDOW_MAX_MINUTES}
            value={checkinBefore}
            onChange={(e) => setCheckinBefore(e.target.value)}
            placeholder={
              dojoSettings ? String(dojoSettings.checkin_window_before_minutes) : undefined
            }
            className="min-h-[44px]"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="edit-checkin-after">Check-in closes after (minutes)</Label>
          <Input
            id="edit-checkin-after"
            type="number"
            min={0}
            max={CHECKIN_WINDOW_MAX_MINUTES}
            value={checkinAfter}
            onChange={(e) => setCheckinAfter(e.target.value)}
            placeholder={
              dojoSettings ? String(dojoSettings.checkin_window_after_minutes) : undefined
            }
            className="min-h-[44px]"
          />
        </div>
      </div>
      {error !== null && (
        <p className="text-sm text-destructive" role="alert">{error}</p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={submitting} className="min-h-[44px]">
          {submitting ? "Saving…" : "Save"}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel} className="min-h-[44px]">
          Cancel
        </Button>
      </div>
    </form>
  )
}

// ── SessionDetailPage ─────────────────────────────────────────────────────────

type PageState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | {
      kind: "loaded"
      session: SessionInstance
      role: "admin" | "member"
      attendance: AttendanceRecord[]
      sessionTypes: SessionType[]
    }

const SessionDetailPage = () => {
  const { id } = useParams<{ id: string }>()
  const [state, setState] = useState<PageState>({ kind: "loading" })
  const [editing, setEditing] = useState(false)
  const [showSeriesCancel, setShowSeriesCancel] = useState(false)
  const [template, setTemplate] = useState<SessionTemplate | null>(null)
  const [checkinState, setCheckinState] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [checkinError, setCheckinError] = useState<string | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [attendanceOpen, setAttendanceOpen] = useState(false)

  useEffect(() => {
    if (!id) return
    Promise.all([
      getSession(id),
      getMe(),
      getSessionAttendance(id).catch(() => []),
      getSessionTypes().catch(() => []),
    ])
      .then(([session, me, attendance, sessionTypes]) => {
        const attendanceList = Array.isArray(attendance) ? attendance : []
        setState({ kind: "loaded", session, role: me.role, attendance: attendanceList, sessionTypes })
        if (session.template_id !== null) {
          setTimeout(() => setShowSeriesCancel(true), 0)
          // Template detail (incl. end_date) is admin-only on the backend —
          // only fetch it for admins, and swallow failures silently so a
          // 403/404 never blocks the rest of the page from rendering.
          if (me.role === "admin") {
            getSessionTemplate(session.template_id)
              .then(setTemplate)
              .catch(() => {
                // expiry display / extend action simply stay hidden
              })
          }
        }
      })
      .catch(() => {
        setState({ kind: "error", message: "Failed to load session." })
      })
  }, [id])

  const handleCheckIn = async () => {
    if (!id) return
    setCheckinState("loading")
    setCheckinError(null)
    try {
      await checkIn(id)
      setCheckinState("success")
    } catch (err) {
      const message =
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to check in"
      setCheckinState("error")
      setCheckinError(message)
    }
  }

  const handleCancelInstance = async () => {
    if (!id || state.kind !== "loaded") return
    setCancelError(null)
    try {
      const updated = await cancelSession(id)
      setState({ ...state, session: updated })
    } catch (err) {
      setCancelError(
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to cancel session",
      )
    }
  }

  const handleCancelSeries = async () => {
    if (state.kind !== "loaded" || state.session.template_id === null) return
    setCancelError(null)
    try {
      await deleteTemplate(state.session.template_id)
    } catch (err) {
      setCancelError(
        typeof err === "object" && err !== null && "message" in err
          ? String((err as { message: unknown }).message)
          : "Failed to cancel series",
      )
    }
  }

  if (state.kind === "loading") {
    return (
      <div className="px-4 py-6">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    )
  }

  if (state.kind === "error") {
    return (
      <div className="px-4 py-6">
        <p className="text-sm text-destructive">{state.message}</p>
      </div>
    )
  }

  const { session, role, attendance, sessionTypes } = state
  const isAdmin = role === "admin"
  const typeById = new Map<string, SessionType>(sessionTypes.map((t) => [t.id, t]))

  if (editing) {
    return (
      <div className="px-4 py-6">
        <div className="mb-4">
          <PageHeader title="Edit Session" />
        </div>
        <EditForm
          session={session}
          sessionTypes={sessionTypes}
          onSave={(updated) => {
            setState({ ...state, session: updated })
            setEditing(false)
          }}
          onCancel={() => setEditing(false)}
        />
      </div>
    )
  }

  return (
    <div className="px-4 py-6 space-y-6">
      <PageHeader title={session.title} />

      {/* Details card — full width, metadata in a grid on desktop */}
      <Card>
        <CardContent className="py-4 space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Date</p>
              <p className="font-medium">{session.date}</p>
            </div>
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Start time</p>
              <p className="font-medium">{session.start_time}</p>
            </div>
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Duration</p>
              <p className="font-medium">{session.duration_minutes} min</p>
            </div>
            {session.location !== null && (
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Location</p>
                <p className="font-medium">{session.location}</p>
              </div>
            )}
            {template !== null && (
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Series ends</p>
                <p className="font-medium">{template.end_date}</p>
              </div>
            )}
          </div>

          {/* Per-segment breakdown */}
          {session.segments.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-sm text-muted-foreground">Segments</p>
              <ul className="space-y-1.5">
                {session.segments.map((segment, idx) => {
                  const endMinutes =
                    Number(segment.start_time.slice(0, 2)) * 60 +
                    Number(segment.start_time.slice(3, 5)) +
                    segment.duration_minutes
                  const endTime = `${String(Math.floor(endMinutes / 60) % 24).padStart(2, "0")}:${String(endMinutes % 60).padStart(2, "0")}`
                  const types = segment.type_ids
                    .map((tid) => typeById.get(tid))
                    .filter((t): t is SessionType => t !== undefined)
                  return (
                    <li
                      key={segment.id ?? idx}
                      className="flex flex-col gap-1 text-sm rounded-md border px-3 py-2"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-medium tabular-nums">
                          {segment.start_time.slice(0, 5)}–{endTime}
                        </span>
                        <span className="flex items-center gap-1.5 flex-wrap">
                          {types.map((t) => (
                            <span key={t.id} className="inline-flex items-center gap-1">
                              <span
                                className="h-2 w-2 rounded-full shrink-0"
                                style={{ backgroundColor: t.colour ?? "var(--muted-foreground)" }}
                                aria-hidden="true"
                              />
                              {t.name}
                            </span>
                          ))}
                        </span>
                      </div>
                      {segment.title && (
                        <p className="font-medium">{segment.title}</p>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}

          {session.cancelled && (
            <span className="inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              Cancelled
            </span>
          )}

          {isAdmin && (
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Check-in link</p>
              <div className="flex items-start gap-2">
                <p className="text-sm break-all">{session.checkin_link}</p>
                <CopyButton
                  value={session.checkin_link}
                  label="Copy check-in link"
                  className="shrink-0"
                />
              </div>
            </div>
          )}

          {/* Check-in button */}
          {!session.cancelled && (
            <div className="space-y-2">
              {checkinState === "success" ? (
                <div
                  className="flex items-center justify-center w-full min-h-[48px] rounded-md bg-green-100 text-green-800 font-medium text-sm"
                  role="status"
                  aria-live="polite"
                >
                  Checked in!
                </div>
              ) : (
                <Button
                  size="lg"
                  className="w-full min-h-[48px]"
                  onClick={() => void handleCheckIn()}
                  disabled={checkinState === "loading"}
                  aria-label="Check in to this session"
                >
                  {checkinState === "loading" ? "Checking in…" : "Check In"}
                </Button>
              )}
              {checkinState === "error" && checkinError !== null && (
                <p className="text-xs text-destructive" role="alert">{checkinError}</p>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Info + Coach Notes — two columns on desktop only when both present */}
      {(session.info !== null || (isAdmin && session.coach_notes !== null)) && (
        <div className={
          session.info !== null && isAdmin && session.coach_notes !== null
            ? "grid grid-cols-1 md:grid-cols-2 gap-6"
            : "space-y-6"
        }>
          {session.info !== null && (
            <div className="space-y-1">
              <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Info</p>
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{session.info}</ReactMarkdown>
              </div>
            </div>
          )}
          {isAdmin && session.coach_notes !== null && (
            <div className="space-y-1">
              <p className="text-sm font-medium text-muted-foreground uppercase tracking-wider">Coach Notes</p>
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{session.coach_notes}</ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Admin actions + attendance */}
      {isAdmin && (
        <>
          <div className="flex flex-wrap justify-end gap-2">
            {showSeriesCancel && (
              <Button
                variant="destructive"
                onClick={() => void handleCancelSeries()}
                className="min-h-[44px]"
              >
                Cancel Series
              </Button>
            )}
            <Button
              variant="destructive"
              onClick={() => void handleCancelInstance()}
              className="min-h-[44px]"
            >
              Cancel Session
            </Button>
            {template !== null && (
              <ExtendSeriesControl
                templateId={template.id}
                currentEndDate={template.end_date}
                onExtended={(updated) => setTemplate(updated)}
              />
            )}
            <Button onClick={() => setEditing(true)} className="min-h-[44px]">
              Edit
            </Button>
          </div>
          {cancelError !== null && (
            <p className="text-sm text-destructive" role="alert">{cancelError}</p>
          )}

          <Collapsible open={attendanceOpen} onOpenChange={setAttendanceOpen}>
            <CollapsibleTrigger
              className="flex items-center gap-2 text-sm font-medium text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors"
              aria-expanded={attendanceOpen}
            >
              {attendanceOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
              Attendance ({attendance.length})
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-2">
                {attendance.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No attendees yet.</p>
                ) : (
                  <ul className="space-y-1" aria-label="Attendance list">
                    {attendance.map((record) => (
                      <li key={record.id} className="text-sm font-mono">
                        {record.visitor_name ?? record.display_name ?? "Unknown"}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </>
      )}
    </div>
  )
}

export default SessionDetailPage
