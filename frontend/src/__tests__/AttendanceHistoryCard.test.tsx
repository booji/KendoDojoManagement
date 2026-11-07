/**
 * The Attendance history card (#572): collapsed by default, as on the Member
 * page; My Attendance opens it with defaultOpen.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"

import AttendanceHistoryCard from "@/components/AttendanceHistoryCard"

const MEMBER_ID = "aaaaaaaa-0000-0000-0000-000000000001"

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(global, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify([
        {
          id: "r1",
          session_id: "bbbbbbbb-0000-0000-0000-000000000001",
          member_id: MEMBER_ID,
          visitor_name: null,
          checked_in_at: "2025-03-06T19:00:00Z",
          recorded_by: "x",
          display_name: null,
          session_title: "Thursday keiko",
          session_date: "2025-03-06",
        },
      ]),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ),
  )
})

describe("AttendanceHistoryCard", () => {
  it("starts collapsed", async () => {
    render(<AttendanceHistoryCard memberId={MEMBER_ID} />)

    expect(
      await screen.findByRole("button", { name: /show attendance/i }),
    ).toHaveAttribute("aria-expanded", "false")
    expect(screen.queryByText("Thursday keiko")).not.toBeInTheDocument()
  })

  it("starts open with defaultOpen", async () => {
    render(<AttendanceHistoryCard memberId={MEMBER_ID} defaultOpen />)

    expect(await screen.findByText("Thursday keiko")).toBeInTheDocument()
  })
})
