/**
 * My Attendance (#572): the signed-in Member's own Attendance history.
 *
 * The page reads the Member behind the Account (GET /accounts/me/member) and
 * then that Member's history (GET /members/{id}/attendance).
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"

import AttendancePage from "@/pages/AttendancePage"

const MEMBER_ID = "aaaaaaaa-0000-0000-0000-000000000001"

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })

const serve = (routes: Record<string, () => Response>) =>
  vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url
    return routes[url]?.() ?? json({ detail: "Not found" }, 404)
  })

const ownMember = () => json({ id: MEMBER_ID, first_name: "Ai", surname: "Sato" })

const renderPage = () =>
  render(
    <MemoryRouter>
      <AttendancePage />
    </MemoryRouter>,
  )

beforeEach(() => {
  vi.restoreAllMocks()
})

describe("My Attendance", () => {
  it("lists each Session the signed-in Member attended, by title and date", async () => {
    serve({
      "/api/accounts/me/member": ownMember,
      [`/api/members/${MEMBER_ID}/attendance`]: () =>
        json([
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
    })

    renderPage()

    await userEvent.click(
      await screen.findByRole("button", { name: /show attendance \(1 sessions\)/i }),
    )
    expect(screen.getByText("Thursday keiko")).toBeInTheDocument()
    expect(screen.getByText("Thu, 6 Mar 2025")).toBeInTheDocument()
    expect(screen.queryByText(/bbbbbbbb/)).not.toBeInTheDocument()
  })

  it("shows an empty state, not an error, when the Account has no Member", async () => {
    serve({})

    renderPage()

    expect(await screen.findByText(/no member record/i)).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("shows an empty state, not an error, when the Member has no Attendance", async () => {
    serve({
      "/api/accounts/me/member": ownMember,
      [`/api/members/${MEMBER_ID}/attendance`]: () => json([]),
    })

    renderPage()

    expect(await screen.findByText(/no attendance records yet/i)).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })

  it("points to the Sessions page for check-in", async () => {
    serve({})

    renderPage()

    expect(screen.getByRole("link", { name: /sessions page/i })).toHaveAttribute(
      "href",
      "/sessions",
    )
  })
})
