/**
 * The Grade card on the Member detail page (#565).
 *
 * A Member's current Grade is their latest *confirmed* Promotion, and that
 * rule lives on the server: the card shows what GET
 * /members/{id}/grades/current answers (404 means Mukyū). It does not derive
 * the Grade from the history list.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import MemberDetailPage from "@/pages/MemberDetailPage"

const MEMBER_ID = "aaaaaaaa-0000-0000-0000-000000000001"

const member = {
  id: MEMBER_ID,
  email: "ai@dojo.test",
  first_name: "Ai",
  surname: "Sato",
  display_name: null,
  dob: "1990-01-01",
  join_date: "2024-01-01",
  membership_status: "active",
  is_coach: false,
  is_first_aider: false,
  emergency_contact_name: null,
  emergency_contact_phone: null,
  anonymised_at: null,
  anonymised_by: null,
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })

/** Answer the page's requests; anything not listed is an empty list. */
const serve = (routes: Record<string, () => Response>) =>
  vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url
    return routes[url]?.() ?? json([])
  })

const baseRoutes = {
  [`/api/members/${MEMBER_ID}`]: () => json(member),
  "/api/auth/me": () => json({ sub: "admin", email: "admin@dojo.test", role: "admin" }),
  "/api/accounts/me/member": () => json({ detail: "Not found" }, 404),
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/members/${MEMBER_ID}`]}>
      <Routes>
        <Route path="/members/:id" element={<MemberDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )

beforeEach(() => {
  vi.restoreAllMocks()
})

describe("current Grade", () => {
  it("shows the Grade the server reports as current", async () => {
    serve({
      ...baseRoutes,
      [`/api/members/${MEMBER_ID}/grades`]: () => json([]),
      [`/api/members/${MEMBER_ID}/grades/current`]: () =>
        json({ grade: "NIDAN", display_name: "Nidan (2-dan)", awarded_at: "2025-01-01" }),
    })

    renderPage()

    expect(await screen.findByText("Nidan (2-dan)")).toBeInTheDocument()
    expect(screen.queryByText("Mukyū")).not.toBeInTheDocument()
  })

  it("asks the server again after an Admin approves a pending Promotion", async () => {
    const pending = {
      id: "e1",
      member_id: MEMBER_ID,
      grade: "SHODAN",
      display_name: "Shodan (1-dan)",
      promoted_at: "2025-01-01T10:00:00+00:00",
      assigned_by: null,
      status: "pending",
    }
    let approved = false
    serve({
      ...baseRoutes,
      [`/api/members/${MEMBER_ID}/grades`]: () => json([pending]),
      [`/api/members/${MEMBER_ID}/grades/current`]: () =>
        approved
          ? json({ grade: "SHODAN", display_name: "Shodan (1-dan)", awarded_at: "2025-01-01" })
          : json({ detail: "No grade history found" }, 404),
      [`/api/members/${MEMBER_ID}/grades/e1/approve`]: () => {
        approved = true
        return json({ ...pending, status: "confirmed", assigned_by: "admin" })
      },
    })

    renderPage()
    expect(await screen.findByText("Mukyū")).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: /show grade history/i }))
    await userEvent.click(screen.getByRole("button", { name: "Approve Shodan (1-dan)" }))

    await waitFor(() => expect(screen.queryByText("Mukyū")).not.toBeInTheDocument())
  })
})
