import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeSanitize from "rehype-sanitize"
import { getSession, updateSession, cancelSession, deleteTemplate } from "@/api/sessions"
import type { SessionInstance, SessionInstanceUpdate } from "@/api/sessions"
import { getMe } from "@/api/auth"
import { checkIn, getSessionAttendance } from "@/api/attendance"
import type { AttendanceRecord } from "@/api/attendance"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Card, CardContent } from "@/components/ui/card"
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible"
import { ChevronDown, ChevronRight } from "lucide-react"

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

// ── Edit form ─────────────────────────────────────────────────────────────────

type EditFormProps = {
  session: SessionInstance
  onSave: (updated: SessionInstance) => void
  onCancel: () => void
}

const EditForm = ({ session, onSave, onCancel }: EditFormProps) => {
  const [date, setDate] = useState(session.date)
  const [startTime, setStartTime] = useState(session.start_time)
  const [durationMinutes, setDurationMinutes] = useState(String(session.duration_minutes))
  const [location, setLocation] = useState(session.location ?? "")
  const [notes, setNotes] = useState(session.notes ?? "")
  const [info, setInfo] = useState(session.info ?? "")
  const [infoPreview, setInfoPreview] = useState(false)
  const [coachNotes, setCoachNotes] = useState(session.coach_notes ?? "")
  const [coachNotesPreview, setCoachNotesPreview] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const payload: Partial<SessionInstanceUpdate> = {
        date,
        start_time: startTime,
        duration_minutes: parseInt(durationMinutes, 10),
        location: location.trim() || null,
        notes: notes.trim() || null,
        info: info.trim() || null,
        coach_notes: coachNotes.trim() || null,
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
        <Label htmlFor="edit-start-time">Start time</Label>
        <Input
          id="edit-start-time"
          type="time"
          value={startTime}
          onChange={(e) => setStartTime(e.target.value)}
          className="min-h-[44px]"
          required
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="edit-duration">Duration (minutes)</Label>
        <Input
          id="edit-duration"
          type="number"
          min={1}
          value={durationMinutes}
          onChange={(e) => setDurationMinutes(e.target.value)}
          className="min-h-[44px]"
          required
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
  | { kind: "loaded"; session: SessionInstance; role: "admin" | "member"; attendance: AttendanceRecord[] }

const SessionDetailPage = () => {
  const { id } = useParams<{ id: string }>()
  const [state, setState] = useState<PageState>({ kind: "loading" })
  const [editing, setEditing] = useState(false)
  const [showSeriesCancel, setShowSeriesCancel] = useState(false)
  const [checkinState, setCheckinState] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [checkinError, setCheckinError] = useState<string | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [attendanceOpen, setAttendanceOpen] = useState(false)

  useEffect(() => {
    if (!id) return
    Promise.all([getSession(id), getMe(), getSessionAttendance(id).catch(() => [])])
      .then(([session, me, attendance]) => {
        const attendanceList = Array.isArray(attendance) ? attendance : []
        setState({ kind: "loaded", session, role: me.role, attendance: attendanceList })
        if (session.template_id !== null) {
          setTimeout(() => setShowSeriesCancel(true), 0)
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
      <div className="px-4 py-6 max-w-6xl mx-auto">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    )
  }

  if (state.kind === "error") {
    return (
      <div className="px-4 py-6 max-w-6xl mx-auto">
        <p className="text-sm text-destructive">{state.message}</p>
      </div>
    )
  }

  const { session, role, attendance } = state
  const isAdmin = role === "admin"

  if (editing) {
    return (
      <div className="px-4 py-6 max-w-6xl mx-auto">
        <h1 className="text-xl font-semibold mb-4">Edit Session</h1>
        <EditForm
          session={session}
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
    <div className="px-4 py-6 space-y-6 max-w-6xl mx-auto">
      <h1 className="text-xl font-semibold">Session Detail</h1>

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
          </div>

          {session.cancelled && (
            <span className="inline-block rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
              Cancelled
            </span>
          )}

          {session.checkin_url !== null && (
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Check-in URL</p>
              <p className="text-sm break-all">{session.checkin_url}</p>
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
