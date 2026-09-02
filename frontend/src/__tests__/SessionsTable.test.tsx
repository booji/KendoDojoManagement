/**
 * Tests for SessionsTable component (issue #91).
 *
 * Acceptance criteria covered:
 *   AC1 — rows render with correct Date, Type, Time, Duration values
 *   AC2 — upcoming-only filter hides past rows by default
 *   AC3 — toggling "Show past sessions" reveals previously hidden past rows
 *   AC4 — cancelled session renders "Cancelled" badge + opacity-60 row
 *   AC5 — clicking a row navigates to /sessions/:id
 *   AC6 — Attendees count column hidden when isAdmin=false, shown when isAdmin=true
 *   AC7 — inline "Check In" button present for upcoming sessions and calls checkIn API
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import SessionsTable from "@/components/SessionsTable"

// ── Mock @/api/attendance ─────────────────────────────────────────────────────

const mockCheckIn = vi.fn()

vi.mock("@/api/attendance", () => ({
  checkIn: (...args: unknown[]) => mockCheckIn(...args),
}))

// ── Fixtures ──────────────────────────────────────────────────────────────────

const SEGMENTS_T1 = [
  { id: "seg-1", start_time: "19:00", duration_minutes: 90, type_ids: ["t1"] },
]

const pastSession = {
  id: "s-past",
  title: "General Training",
  date: "2020-01-01",
  start_time: "19:00",
  duration_minutes: 90,
  location: "Main dojo",
  template_id: null,
  cancelled: false,
  notes: null,
  info: null,
  coach_notes: null,
  checkin_link: "https://dojo.example.com/checkin/session/s1",
  attendance_count: 5,
  is_checked_in: false,
  segments: SEGMENTS_T1,
}

const upcomingSession = {
  id: "s-upcoming",
  title: "General Training",
  date: "2099-01-01",
  start_time: "19:00",
  duration_minutes: 90,
  location: "Main dojo",
  template_id: null,
  cancelled: false,
  notes: null,
  info: null,
  coach_notes: null,
  checkin_link: "https://dojo.example.com/checkin/session/s1",
  attendance_count: 3,
  is_checked_in: false,
  segments: SEGMENTS_T1,
}

const cancelledSession = {
  ...upcomingSession,
  id: "s-cancelled",
  cancelled: true,
}

const typeMap = new Map([["t1", { id: "t1", name: "General Training", colour: "#3366ff" }]])

// ── Helper ────────────────────────────────────────────────────────────────────

type RenderOptions = {
  sessions?: typeof pastSession[]
  isAdmin?: boolean
}

function renderTable({ sessions = [upcomingSession], isAdmin = false }: RenderOptions = {}) {
  return render(
    <MemoryRouter initialEntries={["/sessions"]}>
      <SessionsTable
        sessions={sessions}
        typeMap={typeMap}
        isAdmin={isAdmin}
        data-testid="sessions-table"
      />
    </MemoryRouter>,
  )
}

// Renders the table alongside a real detail route so we can assert that
// clicking navigates to the correct destination (not just that a link exists).
function renderTableWithRouting({ sessions = [upcomingSession], isAdmin = false }: RenderOptions = {}) {
  return render(
    <MemoryRouter initialEntries={["/sessions"]}>
      <Routes>
        <Route
          path="/sessions"
          element={<SessionsTable sessions={sessions} typeMap={typeMap} isAdmin={isAdmin} />}
        />
        <Route path="/sessions/:id" element={<div data-testid="session-detail-page">Detail Page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ── AC1 — Rows render correct column values ───────────────────────────────────

describe("AC1 — row data", () => {
  it("renders the session date in a row", () => {
    renderTable({ sessions: [upcomingSession] })

    // Date "2099-01-01" should appear somewhere in the table (formatted or raw)
    expect(screen.getByTestId("sessions-table")).toBeInTheDocument()
    expect(screen.getByText(/2099/)).toBeInTheDocument()
  })

  it("renders the session type name from the typeMap", () => {
    renderTable({ sessions: [upcomingSession] })

    expect(screen.getAllByText("General Training").length).toBeGreaterThan(0)
  })

  it("renders the start time", () => {
    renderTable({ sessions: [upcomingSession] })

    expect(screen.getByText(/19:00/)).toBeInTheDocument()
  })

  it("renders the duration", () => {
    renderTable({ sessions: [upcomingSession] })

    // Duration 90 should appear (as minutes or "90 min" label)
    expect(screen.getByText(/90/)).toBeInTheDocument()
  })
})

// ── AC2 — Upcoming-only filter hides past rows by default ─────────────────────

describe("AC2 — past rows hidden by default", () => {
  it("does not render a row for the past session when upcoming-only is default", () => {
    renderTable({ sessions: [pastSession, upcomingSession] })

    // past session date 2020 should not be visible
    expect(screen.queryByText(/2020/)).not.toBeInTheDocument()
  })

  it("renders the upcoming session row when past-only filter is active", () => {
    renderTable({ sessions: [pastSession, upcomingSession] })

    expect(screen.getByText(/2099/)).toBeInTheDocument()
  })
})

// ── AC3 — Toggle reveals past rows ────────────────────────────────────────────

describe("AC3 — show past sessions toggle", () => {
  it("renders a toggle / checkbox to show past sessions", () => {
    renderTable({ sessions: [pastSession, upcomingSession] })

    // Some control labelled "Show past sessions" or similar
    const toggle = screen.getByRole("checkbox", { name: /show past/i })
      ?? screen.getByRole("button", { name: /show past/i })
    expect(toggle).toBeInTheDocument()
  })

  it("reveals past session row after toggling 'Show past sessions'", async () => {
    const user = userEvent.setup()
    renderTable({ sessions: [pastSession, upcomingSession] })

    expect(screen.queryByText(/2020/)).not.toBeInTheDocument()

    const toggle = screen.getByRole("checkbox", { name: /show past/i })
    await user.click(toggle)

    await waitFor(() => {
      expect(screen.getByText(/2020/)).toBeInTheDocument()
    })
  })
})

// ── AC4 — Cancelled badge + reduced opacity ───────────────────────────────────

describe("AC4 — cancelled session styling", () => {
  it("renders a 'Cancelled' badge for a cancelled session", () => {
    renderTable({ sessions: [cancelledSession] })

    expect(screen.getByText(/cancelled/i)).toBeInTheDocument()
  })

  it("applies opacity-60 (or similar) class to the cancelled session row", () => {
    renderTable({ sessions: [cancelledSession] })

    // The row or its container should have a reduced-opacity class
    const badge = screen.getByText(/cancelled/i)
    // Walk up to find the row element that carries the opacity class
    let el: HTMLElement | null = badge
    let found = false
    while (el !== null) {
      if (el.className && /opacity-60/.test(el.className)) {
        found = true
        break
      }
      el = el.parentElement
    }
    expect(found).toBe(true)
  })
})

// ── AC5 — Clicking a row navigates to /sessions/:id ──────────────────────────

describe("AC5 — row click navigates", () => {
  it("navigates to /sessions/:id when a row is clicked", async () => {
    // Use a navigate spy via MemoryRouter — check that a link wraps each row
    // or that the row has a role="link" / onclick that leads to the correct href.
    // The simplest assertion: there is an <a> element pointing to /sessions/s-upcoming.
    renderTable({ sessions: [upcomingSession] })

    const link = screen.getByRole("link", { name: /s-upcoming|General Training|2099/i })
      ?? document.querySelector(`a[href*="s-upcoming"]`)
    expect(link).not.toBeNull()
    expect((link as HTMLAnchorElement).href).toMatch(/\/sessions\/s-upcoming/)
  })
})

// ── AC6 — Attendees column visibility by role ─────────────────────────────────

describe("AC6 — attendees column", () => {
  it("does NOT render an Attendees column header when isAdmin is false", () => {
    renderTable({ sessions: [upcomingSession], isAdmin: false })

    expect(screen.queryByRole("columnheader", { name: /attendees/i })).not.toBeInTheDocument()
  })

  it("renders an Attendees column header when isAdmin is true", () => {
    renderTable({ sessions: [upcomingSession], isAdmin: true })

    expect(screen.getByRole("columnheader", { name: /attendees/i })).toBeInTheDocument()
  })

  it("renders the attendance count in the row when isAdmin is true", () => {
    renderTable({ sessions: [upcomingSession], isAdmin: true })

    // upcomingSession.attendance_count === 3
    expect(screen.getByText("3")).toBeInTheDocument()
  })
})

// ── AC7 — Inline "Check In" button in upcoming rows ──────────────────────────

describe("AC7 — check-in button", () => {
  it("renders a Check In button for an upcoming session", () => {
    renderTable({ sessions: [upcomingSession] })

    expect(screen.getByRole("button", { name: /check in/i })).toBeInTheDocument()
  })

  it("does NOT render a Check In button for a past session (even when shown)", async () => {
    const user = userEvent.setup()
    renderTable({ sessions: [pastSession] })

    // Reveal past sessions
    const toggle = screen.getByRole("checkbox", { name: /show past/i })
    await user.click(toggle)

    await waitFor(() => {
      expect(screen.getByText(/2020/)).toBeInTheDocument()
    })

    expect(screen.queryByRole("button", { name: /check in/i })).not.toBeInTheDocument()
  })

  it("calls checkIn with the session id when Check In is clicked", async () => {
    const user = userEvent.setup()
    mockCheckIn.mockResolvedValue({})
    renderTable({ sessions: [upcomingSession] })

    const btn = screen.getByRole("button", { name: /check in/i })
    await user.click(btn)

    await waitFor(() => {
      expect(mockCheckIn).toHaveBeenCalledWith("s-upcoming")
    })
  })
})

// ── Issue #211 — whole-row click opens session detail ────────────────────────

describe("issue #211 — whole-row click", () => {
  it("navigates to the session detail page when a non-Date cell (Title) is clicked", async () => {
    const user = userEvent.setup()
    renderTableWithRouting({ sessions: [upcomingSession] })

    await user.click(screen.getAllByText(upcomingSession.title)[0])

    await waitFor(() => {
      expect(screen.getByTestId("session-detail-page")).toBeInTheDocument()
    })
  })

  it("navigates to the session detail page when the Location cell is clicked", async () => {
    const user = userEvent.setup()
    renderTableWithRouting({ sessions: [upcomingSession] })

    await user.click(screen.getByText(upcomingSession.location))

    await waitFor(() => {
      expect(screen.getByTestId("session-detail-page")).toBeInTheDocument()
    })
  })

  it("does NOT navigate away when the Check In button is clicked, and still calls checkIn", async () => {
    const user = userEvent.setup()
    mockCheckIn.mockResolvedValue({})
    renderTableWithRouting({ sessions: [upcomingSession] })

    await user.click(screen.getByRole("button", { name: /check in/i }))

    await waitFor(() => {
      expect(mockCheckIn).toHaveBeenCalledWith("s-upcoming")
    })
    expect(screen.queryByTestId("session-detail-page")).not.toBeInTheDocument()
  })

  it("exposes a focusable row link with an accessible name containing the date and title", () => {
    renderTable({ sessions: [upcomingSession] })

    const link = screen.getByRole("link", { name: /2099.*General Training/i })
    expect(link).toBeInTheDocument()
    expect(link).not.toHaveAttribute("tabindex", "-1")
  })
})
