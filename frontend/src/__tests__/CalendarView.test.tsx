/**
 * Month view fetch range must cover the whole rendered grid (issue #427).
 *
 * September 2026's grid runs Mon 31 Aug → Sun 11 Oct (42 cells). The week of
 * 5–11 Oct sits after the week containing month-end, so a range that stops at
 * endOfWeek(endOfMonth) leaves that row drawn but never fetched.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"

import CalendarView from "@/components/CalendarView"
import { getSessionsForRange, type SessionInstance } from "@/api/sessions"

vi.mock("@/api/sessions", () => ({
  getSessionTypes: vi.fn().mockResolvedValue([]),
  getSessionsForRange: vi.fn(),
}))

const session = (date: string): SessionInstance => ({
  id: `s-${date}`,
  title: `Keiko ${date}`,
  date,
  start_time: "19:00:00",
  duration_minutes: 90,
  location: null,
  template_id: null,
  cancelled: false,
  info: null,
  coach_notes: null,
  checkin_link: "",
  checkin_window_before_minutes: null,
  checkin_window_after_minutes: null,
  attendance_count: 0,
  is_checked_in: false,
  segments: [],
})

describe("CalendarView month range", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date(2026, 8, 15))
    // Like the backend: only sessions inside [from, to] come back.
    vi.mocked(getSessionsForRange).mockImplementation(async (from, to) =>
      [session("2026-10-06")].filter((s) => s.date >= from && s.date <= to)
    )
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("fetches through the grid's last cell and shows its sessions", async () => {
    render(
      <MemoryRouter>
        <CalendarView isAdmin={false} />
      </MemoryRouter>
    )

    // The month-grid chip; the calendar's agenda list renders the same session too.
    const matches = await screen.findAllByRole("button", { name: "Keiko 2026-10-06" })
    expect(matches.some((b) => b.dataset.sessionId === "s-2026-10-06")).toBe(true)
    expect(getSessionsForRange).toHaveBeenCalledWith("2026-08-31", "2026-10-11")
  })
})
