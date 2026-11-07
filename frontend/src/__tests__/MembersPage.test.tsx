/**
 * The Members list (#571): each Member's current Grade, and the members CSV
 * that used to sit on the Reports page's Members tab.
 */

import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"

import MembersPage from "@/pages/MembersPage"

const member = (id: string, first_name: string, current_grade_name: string | null) => ({
  id,
  email: `${id}@dojo.test`,
  first_name,
  surname: "Tanaka",
  display_name: null,
  dob: null,
  join_date: "2024-01-10",
  membership_status: "active",
  is_coach: false,
  is_first_aider: false,
  emergency_contact_name: null,
  emergency_contact_phone: null,
  anonymised_at: null,
  anonymised_by: null,
  current_grade_name,
})

const MEMBERS = [member("m-1", "Kenji", "Shodan (1-dan)"), member("m-2", "Ai", null)]

const stubFetch = () => {
  const fetchMock = vi.fn((url: string) => {
    const isCsv = String(url).includes("/reports/members/csv")
    return Promise.resolve(
      new Response(isCsv ? "member_id\n" : JSON.stringify(MEMBERS), { status: 200 }),
    )
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

const renderPage = () =>
  render(
    <MemoryRouter>
      <MembersPage />
    </MemoryRouter>,
  )

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("MembersPage current Grade", () => {
  it("shows each Member's current Grade, and — for a Member with none", async () => {
    stubFetch()
    renderPage()

    const table = await screen.findByRole("table", { name: "Members list" })
    expect(within(table).getByRole("columnheader", { name: "Current Grade" })).toBeInTheDocument()
    const kenji = within(table).getByRole("row", { name: "View Kenji Tanaka" })
    expect(kenji).toHaveTextContent("Shodan (1-dan)")
    const ai = within(table).getByRole("row", { name: "View Ai Tanaka" })
    expect(ai).toHaveTextContent("—")
  })

  it("shows the current Grade on the mobile cards too", async () => {
    stubFetch()
    renderPage()

    const cards = await screen.findByRole("list", { name: "Members list" })
    expect(within(cards).getByRole("button", { name: "View Kenji Tanaka" })).toHaveTextContent(
      "Shodan (1-dan)",
    )
    expect(within(cards).getByRole("button", { name: "View Ai Tanaka" })).toHaveTextContent("—")
  })
})

describe("MembersPage members CSV", () => {
  it("downloads the members CSV", async () => {
    const fetchMock = stubFetch()
    // jsdom has no object URLs; the download only needs them to exist.
    URL.createObjectURL = vi.fn(() => "blob:members")
    URL.revokeObjectURL = vi.fn()
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "Download members CSV" }))

    const urls = fetchMock.mock.calls.map((call) => String((call as unknown[])[0]))
    expect(urls.some((url) => url.endsWith("/api/reports/members/csv"))).toBe(true)
    expect(URL.createObjectURL).toHaveBeenCalled()
  })
})
