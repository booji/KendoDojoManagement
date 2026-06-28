import { useState } from "react"
import { Link } from "react-router-dom"
import type { SessionInstance, SessionType } from "@/api/sessions"
import { checkIn } from "@/api/attendance"
import { Button } from "@/components/ui/button"
import { formatSessionDate } from "@/lib/date"
import { distinctSessionTypes } from "@/lib/sessionTypes"

export type SessionsTableProps = {
  sessions: SessionInstance[]
  typeMap: Map<string, SessionType>
  isAdmin: boolean
}

const formatDate = (dateStr: string): string => formatSessionDate(dateStr)

const isUpcoming = (s: SessionInstance): boolean =>
  new Date(`${s.date}T${s.start_time}`) >= new Date()

const CheckInCell = ({ session }: { session: SessionInstance }) => {
  const [checkedIn, setCheckedIn] = useState(false)

  if (session.cancelled || !isUpcoming(session)) return null

  if (checkedIn) {
    return <span className="text-sm text-muted-foreground">Checked in!</span>
  }

  return (
    <Button
      size="sm"
      onClick={(e) => {
        e.stopPropagation()
        e.preventDefault()
        void checkIn(session.id).then(() => setCheckedIn(true))
      }}
    >
      Check In
    </Button>
  )
}

const SessionsTable = ({ sessions, typeMap, isAdmin }: SessionsTableProps) => {
  const [showPast, setShowPast] = useState(false)

  const filtered = showPast ? sessions : sessions.filter(isUpcoming)

  return (
    <div data-testid="sessions-table">
      <div className="flex items-center justify-end mb-3">
        <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showPast}
            onChange={(e) => setShowPast(e.target.checked)}
            className="cursor-pointer"
            aria-label="Show past sessions"
          />
          Show past sessions
        </label>
      </div>

      <table className="w-full text-sm border-collapse">
        <thead>
          <tr>
            <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
              Date
            </th>
            <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
              Title
            </th>
            <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
              Type
            </th>
            <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
              Time
            </th>
            <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
              Duration
            </th>
            <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
              Location
            </th>
            {isAdmin && (
              <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
                Attendees
              </th>
            )}
            <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
              Status
            </th>
            <th className="text-left font-medium text-muted-foreground text-xs uppercase tracking-wider py-2 px-3">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((session) => (
            <tr
              key={session.id}
              className={`cursor-pointer hover:bg-muted/50 border-t border-border${session.cancelled ? " opacity-60" : ""}`}
            >
              <td className="py-2 px-3">
                <Link
                  to={`/sessions/${session.id}`}
                  className="block after:absolute after:inset-0 after:content-[''] relative"
                  tabIndex={-1}
                  aria-label={`${formatDate(session.date)} ${session.title}`}
                >
                  {formatDate(session.date)}
                </Link>
              </td>
              <td className="py-2 px-3">{session.title}</td>
              <td className="py-2 px-3">
                <div className="flex items-center gap-2">
                  {distinctSessionTypes(session.segments, typeMap).map((t) => (
                    <span key={t.id} className="inline-flex items-center gap-1 text-xs">
                      <span
                        className="h-2 w-2 rounded-full shrink-0"
                        style={{ backgroundColor: t.colour ?? "var(--muted-foreground)" }}
                        aria-hidden="true"
                      />
                      {t.name}
                    </span>
                  ))}
                </div>
              </td>
              <td className="py-2 px-3">{session.start_time}</td>
              <td className="py-2 px-3">{session.duration_minutes} min</td>
              <td className="py-2 px-3">{session.location ?? "—"}</td>
              {isAdmin && (
                <td className="py-2 px-3">{session.attendance_count}</td>
              )}
              <td className="py-2 px-3">
                {session.cancelled && <span>Cancelled</span>}
              </td>
              <td className="py-2 px-3">
                <CheckInCell session={session} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default SessionsTable
