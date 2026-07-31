import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  format,
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  addDays,
  addMonths,
  addWeeks,
  subMonths,
  subWeeks,
  isSameMonth,
  isSameDay,
  parseISO,
} from "date-fns"
import { Button } from "@/components/ui/button"
import { getSessionsForRange, getSessionTypes } from "@/api/sessions"
import type { SessionInstance, SessionType } from "@/api/sessions"
import { distinctSessionTypes } from "@/lib/sessionTypes"

// ── Types ─────────────────────────────────────────────────────────────────────

type ViewMode = "month" | "week"

export type CalendarViewProps = {
  isAdmin: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const toYMD = (d: Date): string => format(d, "yyyy-MM-dd")

const buildMonthGrid = (anchor: Date): Date[] => {
  const monthStart = startOfMonth(anchor)
  const gridStart = startOfWeek(monthStart, { weekStartsOn: 1 })
  const cells: Date[] = []
  for (let i = 0; i < 42; i++) {
    cells.push(addDays(gridStart, i))
  }
  return cells
}

const buildWeekDays = (anchor: Date): Date[] => {
  const weekStart = startOfWeek(anchor, { weekStartsOn: 1 })
  return Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))
}

const groupByDate = (sessions: SessionInstance[]): Map<string, SessionInstance[]> => {
  const map = new Map<string, SessionInstance[]>()
  for (const s of sessions) {
    const bucket = map.get(s.date)
    if (bucket !== undefined) {
      bucket.push(s)
    } else {
      map.set(s.date, [s])
    }
  }
  return map
}

const parseHour = (time: string): number => {
  const [h, m] = time.split(":").map(Number)
  return (h ?? 0) + (m ?? 0) / 60
}

// ── Session chip ──────────────────────────────────────────────────────────────

type SessionChipProps = {
  session: SessionInstance
  types: SessionType[]
  isAdmin: boolean
  compact?: boolean
}

const TypePipRow = ({ types }: { types: SessionType[] }) => {
  if (types.length === 0) return null
  return (
    <span className="inline-flex items-center gap-0.5 ml-1" aria-hidden="true">
      {types.map((t) => (
        <span
          key={t.id}
          className="inline-block h-1.5 w-1.5 rounded-full shrink-0"
          style={{ backgroundColor: t.colour ?? "currentColor" }}
        />
      ))}
    </span>
  )
}

const SessionChip = ({ session, types, isAdmin, compact = false }: SessionChipProps) => {
  const navigate = useNavigate()
  const cancelled = session.cancelled && isAdmin
  const colour = types[0]?.colour ?? null

  const colourStyle =
    !cancelled && colour !== null
      ? { backgroundColor: colour + "26", color: colour }
      : undefined

  return (
    <button
      type="button"
      onClick={() => void navigate(`/sessions/${session.id}`)}
      data-session-id={session.id}
      style={colourStyle}
      className={[
        "w-full text-left rounded px-1.5 py-0.5 text-xs leading-tight truncate transition-colors",
        cancelled
          ? "bg-muted text-muted-foreground line-through opacity-70"
          : colour === null
            ? "bg-primary/10 text-primary hover:bg-primary/20"
            : "",
        compact ? "text-[10px]" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-label={`${session.title}${cancelled ? " (cancelled)" : ""}`}
    >
      {session.start_time.slice(0, 5)} {session.title}
      <TypePipRow types={types} />
    </button>
  )
}

// ── Month grid view ───────────────────────────────────────────────────────────

type MonthGridProps = {
  anchor: Date
  byDate: Map<string, SessionInstance[]>
  typeMap: Map<string, SessionType>
  isAdmin: boolean
}

const DAY_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

const MonthGrid = ({ anchor, byDate, typeMap, isAdmin }: MonthGridProps) => {
  const today = new Date()
  const cells = buildMonthGrid(anchor)

  return (
    <div className="flex-1 min-h-0">
      <div className="grid grid-cols-7 border-b">
        {DAY_HEADERS.map((d) => (
          <div
            key={d}
            className="py-1 text-center text-xs font-medium text-muted-foreground"
          >
            {d}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 grid-rows-6 flex-1">
        {cells.map((cell) => {
          const key = toYMD(cell)
          const sessions = byDate.get(key) ?? []
          const inMonth = isSameMonth(cell, anchor)
          const isToday = isSameDay(cell, today)

          return (
            <div
              key={key}
              className={[
                "border-b border-r min-h-[80px] p-1 space-y-0.5",
                !inMonth ? "bg-muted/30" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <span
                className={[
                  "inline-flex h-5 w-5 items-center justify-center rounded-full text-xs",
                  isToday
                    ? "bg-primary text-primary-foreground font-semibold"
                    : inMonth
                      ? "text-foreground"
                      : "text-muted-foreground",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                {cell.getDate()}
              </span>
              {sessions.map((s) => (
                <SessionChip
                  key={s.id}
                  session={s}
                  types={distinctSessionTypes(s.segments, typeMap)}
                  isAdmin={isAdmin}
                  compact
                />
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Week grid view ────────────────────────────────────────────────────────────

const HOUR_LABELS = Array.from({ length: 24 }, (_, i) =>
  i === 0 ? "12 AM" : i < 12 ? `${i} AM` : i === 12 ? "12 PM" : `${i - 12} PM`
)

const GRID_START_HOUR = 6
const GRID_END_HOUR = 22
const HOUR_HEIGHT_PX = 60

type WeekGridProps = {
  anchor: Date
  byDate: Map<string, SessionInstance[]>
  typeMap: Map<string, SessionType>
  isAdmin: boolean
}

const WeekGrid = ({ anchor, byDate, typeMap, isAdmin }: WeekGridProps) => {
  const navigate = useNavigate()
  const today = new Date()
  const days = buildWeekDays(anchor)
  const visibleHours = GRID_END_HOUR - GRID_START_HOUR

  return (
    <div className="flex-1 min-h-0 overflow-auto">
      <div className="sticky top-0 z-10 bg-background grid grid-cols-[48px_repeat(7,1fr)] border-b">
        <div />
        {days.map((day) => {
          const isToday = isSameDay(day, today)
          return (
            <div
              key={toYMD(day)}
              className="py-1 text-center text-xs font-medium text-muted-foreground"
            >
              <span
                className={[
                  "inline-flex flex-col items-center",
                  isToday ? "text-primary font-semibold" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                <span>{format(day, "EEE")}</span>
                <span className={isToday ? "bg-primary text-primary-foreground rounded-full w-5 h-5 flex items-center justify-center text-xs" : ""}>
                  {day.getDate()}
                </span>
              </span>
            </div>
          )
        })}
      </div>

      <div
        className="relative grid grid-cols-[48px_repeat(7,1fr)]"
        style={{ height: visibleHours * HOUR_HEIGHT_PX }}
      >
        {Array.from({ length: visibleHours }, (_, i) => {
          const hour = GRID_START_HOUR + i
          return (
            <div key={hour} className="contents">
              <div
                className="absolute left-0 w-12 text-right pr-1 text-[10px] text-muted-foreground -translate-y-2"
                style={{ top: i * HOUR_HEIGHT_PX }}
              >
                {HOUR_LABELS[hour]}
              </div>
              <div
                className="absolute left-12 right-0 border-t border-border/40"
                style={{ top: i * HOUR_HEIGHT_PX }}
              />
            </div>
          )
        })}

        {days.map((day, colIdx) => {
          const key = toYMD(day)
          const sessions = byDate.get(key) ?? []

          return (
            <div
              key={key}
              className="absolute top-0 bottom-0 border-r border-border/40"
              style={{
                left: `calc(48px + ${colIdx} * ((100% - 48px) / 7))`,
                width: `calc((100% - 48px) / 7)`,
              }}
            >
              {sessions.map((s) => {
                const startHour = parseHour(s.start_time)
                const top = (startHour - GRID_START_HOUR) * HOUR_HEIGHT_PX
                const height = Math.max(
                  (s.duration_minutes / 60) * HOUR_HEIGHT_PX,
                  20
                )
                const cancelled = s.cancelled && isAdmin
                const types = distinctSessionTypes(s.segments, typeMap)
                const colour = types[0]?.colour ?? null

                const colourStyle =
                  !cancelled && colour !== null
                    ? { top, height, backgroundColor: colour + "26", color: colour }
                    : { top, height }

                if (startHour < GRID_START_HOUR || startHour >= GRID_END_HOUR) return null

                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => void navigate(`/sessions/${s.id}`)}
                    data-session-id={s.id}
                    style={colourStyle}
                    className={[
                      "absolute left-0.5 right-0.5 rounded px-1 text-[10px] leading-tight overflow-hidden text-left",
                      "transition-colors",
                      cancelled
                        ? "bg-muted text-muted-foreground line-through opacity-70"
                        : colour === null
                          ? "bg-primary/10 text-primary hover:bg-primary/20"
                          : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    aria-label={`${s.title}${cancelled ? " (cancelled)" : ""} at ${s.start_time}`}
                  >
                    <span className="font-medium">{s.start_time.slice(0, 5)}</span>
                    <br />
                    {s.title}
                    <TypePipRow types={types} />
                  </button>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Agenda list view ──────────────────────────────────────────────────────────

type AgendaViewProps = {
  sessions: SessionInstance[]
  typeMap: Map<string, SessionType>
  isAdmin: boolean
}

const AgendaView = ({ sessions, typeMap, isAdmin }: AgendaViewProps) => {
  const navigate = useNavigate()

  if (sessions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-8 text-center">
        No upcoming sessions.
      </p>
    )
  }

  const grouped: { date: string; label: string; items: SessionInstance[] }[] = []
  for (const s of sessions) {
    const last = grouped[grouped.length - 1]
    if (last !== undefined && last.date === s.date) {
      last.items.push(s)
    } else {
      grouped.push({
        date: s.date,
        label: format(parseISO(s.date), "EEEE, d MMMM yyyy"),
        items: [s],
      })
    }
  }

  return (
    <div className="space-y-6 py-2">
      {grouped.map((group) => (
        <section key={group.date}>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {group.label}
          </h2>
          <ul className="space-y-2">
            {group.items.map((s) => {
              const cancelled = s.cancelled && isAdmin
              const types = distinctSessionTypes(s.segments, typeMap)
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => void navigate(`/sessions/${s.id}`)}
                    className={[
                      "w-full text-left rounded-lg border px-4 py-3 transition-colors",
                      "hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      cancelled ? "opacity-60 bg-muted" : "bg-card",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    aria-label={`${s.title}${cancelled ? " (cancelled)" : ""}`}
                  >
                    <p
                      className={[
                        "font-medium text-sm flex items-center",
                        cancelled ? "line-through text-muted-foreground" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    >
                      {s.title}
                      <TypePipRow types={types} />
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {s.start_time.slice(0, 5)} &middot; {s.duration_minutes} min
                      {s.location !== null ? ` \u00b7 ${s.location}` : ""}
                    </p>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}

// ── Main CalendarView ─────────────────────────────────────────────────────────

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; sessions: SessionInstance[]; typeMap: Map<string, SessionType> }

// A settled result is tagged with the range it was fetched for, so a range
// change reads as "loading" during render instead of needing an effect to
// synchronously reset the state.
type SettledResult = Exclude<LoadState, { kind: "loading" }> & { range: string }

const CalendarView = ({ isAdmin }: CalendarViewProps) => {
  const [viewMode, setViewMode] = useState<ViewMode>("month")
  const [anchor, setAnchor] = useState<Date>(() => new Date())
  const [result, setResult] = useState<SettledResult | null>(null)

  const { from, to } = (() => {
    if (viewMode === "month") {
      const ms = startOfMonth(anchor)
      const me = endOfMonth(anchor)
      return {
        from: toYMD(startOfWeek(ms, { weekStartsOn: 1 })),
        to: toYMD(endOfWeek(me, { weekStartsOn: 1 })),
      }
    } else {
      const ws = startOfWeek(anchor, { weekStartsOn: 1 })
      const we = endOfWeek(anchor, { weekStartsOn: 1 })
      return { from: toYMD(ws), to: toYMD(we) }
    }
  })()

  const rangeKey = `${from}|${to}`
  const loadState: LoadState =
    result && result.range === rangeKey ? result : { kind: "loading" }

  useEffect(() => {
    let cancelled = false
    Promise.all([getSessionsForRange(from, to), getSessionTypes()])
      .then(([sessions, types]: [SessionInstance[], SessionType[]]) => {
        if (cancelled) return
        const typeMap = new Map<string, SessionType>(types.map((t) => [t.id, t]))
        setResult({ kind: "loaded", sessions, typeMap, range: rangeKey })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const message =
          typeof err === "object" && err !== null && "message" in err
            ? String((err as { message: unknown }).message)
            : "Failed to load sessions"
        setResult({ kind: "error", message, range: rangeKey })
      })
    return () => { cancelled = true }
  }, [from, to, rangeKey])

  const handlePrev = () => {
    if (viewMode === "month") setAnchor((d) => subMonths(d, 1))
    else setAnchor((d) => subWeeks(d, 1))
  }

  const handleNext = () => {
    if (viewMode === "month") setAnchor((d) => addMonths(d, 1))
    else setAnchor((d) => addWeeks(d, 1))
  }

  const periodLabel =
    viewMode === "month"
      ? format(anchor, "MMMM yyyy")
      : (() => {
          const ws = startOfWeek(anchor, { weekStartsOn: 1 })
          const we = endOfWeek(anchor, { weekStartsOn: 1 })
          return `${format(ws, "d MMM")} – ${format(we, "d MMM yyyy")}`
        })()

  const sessions = loadState.kind === "loaded" ? loadState.sessions : []
  const typeMap = loadState.kind === "loaded" ? loadState.typeMap : new Map<string, SessionType>()
  const byDate = groupByDate(sessions)

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-3 border-b shrink-0">
        <Button variant="outline" size="sm" onClick={handlePrev} aria-label="Previous period">
          &#8249;
        </Button>
        <span className="flex-1 text-center text-sm font-medium">{periodLabel}</span>
        <Button variant="outline" size="sm" onClick={handleNext} aria-label="Next period">
          &#8250;
        </Button>

        {/* Month/week toggle — desktop only */}
        <div className="hidden md:flex items-center gap-1 ml-2">
          <Button
            variant={viewMode === "month" ? "default" : "outline"}
            size="sm"
            onClick={() => setViewMode("month")}
            aria-pressed={viewMode === "month"}
          >
            Month
          </Button>
          <Button
            variant={viewMode === "week" ? "default" : "outline"}
            size="sm"
            onClick={() => setViewMode("week")}
            aria-pressed={viewMode === "week"}
          >
            Week
          </Button>
        </div>
      </div>

      {/* Error banner */}
      {loadState.kind === "error" && (
        <div
          className="px-4 py-2 text-sm text-destructive bg-destructive/10 border-b"
          role="alert"
        >
          {loadState.message}
        </div>
      )}

      {/* Content area */}
      <div className="flex-1 min-h-0 overflow-hidden px-4 pb-4">
        {/* Mobile: always agenda */}
        <div className="block md:hidden overflow-y-auto h-full">
          {loadState.kind === "loading" ? (
            <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
          ) : (
            <AgendaView sessions={sessions} typeMap={typeMap} isAdmin={isAdmin} />
          )}
        </div>

        {/* Desktop: month or week grid */}
        <div className="hidden md:flex flex-col h-full">
          {loadState.kind === "loading" ? (
            <p className="text-sm text-muted-foreground py-8 text-center">Loading…</p>
          ) : viewMode === "month" ? (
            <MonthGrid anchor={anchor} byDate={byDate} typeMap={typeMap} isAdmin={isAdmin} />
          ) : (
            <WeekGrid anchor={anchor} byDate={byDate} typeMap={typeMap} isAdmin={isAdmin} />
          )}
        </div>
      </div>
    </div>
  )
}

export default CalendarView
