/**
 * Absent Members on the Charts tab (#564): a list, so someone can reach out.
 * The server owns who is absent and the order; these tests cover what the
 * Admin asks for and what they are shown.
 */

import { describe, it, expect, vi, afterEach } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"

import ChartsTab from "@/components/reports/ChartsTab"

const ABSENT = [
  {
    member_id: "m-never",
    display_name: "Ai Sato",
    email: "ai@dojo.test",
    last_attended: null,
    days_absent: 40,
  },
  {
    member_id: "m-seen",
    display_name: "Kenji",
    email: null,
    last_attended: "2026-10-12",
    days_absent: 24,
  },
]

const stubFetch = (absent: unknown = ABSENT) => {
  const fetchMock = vi.fn((url: string) => {
    const body = String(url).includes("/absent-members") ? absent : []
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(body),
      text: () => Promise.resolve(JSON.stringify(body)),
    } as unknown as Response)
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

const absentUrls = (fetchMock: ReturnType<typeof stubFetch>) =>
  fetchMock.mock.calls
    .map((call) => String((call as unknown[])[0]))
    .filter((url) => url.includes("/absent-members"))

const renderTab = () =>
  render(
    <MemoryRouter>
      <ChartsTab />
    </MemoryRouter>,
  )

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("Absent Members", () => {
  it("lists each Absent Member with how to reach them and how long they have been away", async () => {
    const fetchMock = stubFetch()

    renderTab()

    const table = await screen.findByRole("table", { name: "Absent Members" })
    const rows = within(table).getAllByRole("row")
    expect(
      within(rows[0])
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Name", "Email", "Last attended", "Days absent"])
    expect(
      rows.slice(1).map((r) =>
        within(r)
          .getAllByRole("cell")
          .map((c) => c.textContent),
      ),
    ).toEqual([
      ["Ai Sato", "ai@dojo.test", "Never", "40"],
      ["Kenji", "", "12 Oct 2026", "24"],
    ])
    expect(within(table).getByRole("link", { name: "Ai Sato" })).toHaveAttribute(
      "href",
      "/members/m-never",
    )
    expect(absentUrls(fetchMock)).toEqual([
      "/api/reports/absent-members?status=active",
    ])
  })

  it("follows the Membership Status filter", async () => {
    const fetchMock = stubFetch()
    renderTab()
    await screen.findByRole("table", { name: "Absent Members" })

    await userEvent.click(screen.getByRole("checkbox", { name: "Inactive" }))

    expect(absentUrls(fetchMock).at(-1)).toBe(
      "/api/reports/absent-members?status=active&status=inactive",
    )
  })

  it("says so when nobody is absent", async () => {
    stubFetch([])

    renderTab()

    expect(await screen.findByText("No Absent Members.")).toBeInTheDocument()
  })
})
