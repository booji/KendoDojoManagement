/**
 * The attendance report renders what GET /api/reports/attendance sends
 * (#559): each Session's date, and each Member's name beside their rate.
 */

import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import ReportsPage from "@/pages/ReportsPage"

const REPORT = {
  sessions: [{ session_id: "s-1", date: "2026-03-05", headcount: 4 }],
  member_rates: [
    {
      member_id: "m-1",
      display_name: "Kenji Tanaka",
      sessions_attended: 1,
      total_sessions: 2,
      attendance_rate: 0.5,
    },
  ],
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("ReportsPage attendance report", () => {
  it("shows each Session's date and each Member's name", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify(REPORT), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    render(<ReportsPage />)

    await userEvent.click(screen.getByRole("tab", { name: "Attendance" }))
    await userEvent.click(
      screen.getByRole("button", { name: "Generate attendance report" }),
    )

    const sessions = await screen.findByRole("table", {
      name: "Sessions summary",
    })
    expect(sessions).toHaveTextContent("Thu, 5 Mar 2026")
    const rates = screen.getByRole("table", { name: "Member attendance rates" })
    expect(rates).toHaveTextContent("Kenji Tanaka")
    expect(rates).toHaveTextContent("50%")
  })
})

describe("ReportsPage tabs", () => {
  it("has no Members tab: the Members list carries its Grade and CSV (#571)", () => {
    render(<ReportsPage />)

    expect(screen.getByRole("tab", { name: "Attendance" })).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "Members" })).not.toBeInTheDocument()
  })
})
