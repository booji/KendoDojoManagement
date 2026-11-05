/**
 * The Charts tab on /reports (#560): the tab-wide Membership Status filter and
 * the grade distribution it scopes. The server owns the counting rules; these
 * tests cover what the Admin asks for and what they are shown.
 */

import { describe, it, expect, vi, afterEach } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import ChartsTab from "@/components/reports/ChartsTab"

const MUKYU_3_SHODAN_1 = [
  { grade: "MUKYUU", display_name: "Mukyū", count: 3 },
  { grade: "ROKKYUU", display_name: "Rokkyū (6-kyu)", count: 0 },
  { grade: "SHODAN", display_name: "Shodan (1-dan)", count: 1 },
]

const stubFetch = (body: unknown = MUKYU_3_SHODAN_1) => {
  // Grades only: the tab's other views (AbsentMembers.test.tsx) get nothing.
  const fetchMock = vi.fn((url: string) => {
    const data = String(url).includes("/reports/grades") ? body : []
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve(data),
      text: () => Promise.resolve(JSON.stringify(data)),
    } as unknown as Response)
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

const requestedUrls = (fetchMock: ReturnType<typeof stubFetch>) =>
  fetchMock.mock.calls
    .map((call) => String((call as unknown[])[0]))
    .filter((url) => url.includes("/reports/grades"))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("Charts tab", () => {
  it("shows how many active Members hold each Grade by default", async () => {
    const fetchMock = stubFetch()

    render(<ChartsTab />)

    const table = await screen.findByRole("table", { name: "Grade distribution" })
    const rows = within(table).getAllByRole("row").slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      "Mukyū3",
      "Rokkyū (6-kyu)0",
      "Shodan (1-dan)1",
    ])
    expect(requestedUrls(fetchMock)).toEqual([
      "/api/reports/grades?status=active",
    ])
    expect(screen.getByRole("checkbox", { name: "Active" })).toBeChecked()
    expect(screen.getByRole("checkbox", { name: "Inactive" })).not.toBeChecked()
  })

  it("counts the Membership Statuses the Admin ticks", async () => {
    const fetchMock = stubFetch()
    render(<ChartsTab />)
    await screen.findByRole("table", { name: "Grade distribution" })

    await userEvent.click(screen.getByRole("checkbox", { name: "Suspended" }))

    expect(requestedUrls(fetchMock).at(-1)).toBe(
      "/api/reports/grades?status=active&status=suspended",
    )
  })

  it("asks for a status instead of fetching when none is ticked", async () => {
    const fetchMock = stubFetch()
    render(<ChartsTab />)
    await screen.findByRole("table", { name: "Grade distribution" })

    await userEvent.click(screen.getByRole("checkbox", { name: "Active" }))

    expect(
      screen.getByText("Choose at least one Membership Status."),
    ).toBeInTheDocument()
    expect(screen.queryByRole("table", { name: "Grade distribution" })).toBeNull()
    expect(requestedUrls(fetchMock)).toHaveLength(1)
  })

  it("says so when no Member is counted", async () => {
    stubFetch([])

    render(<ChartsTab />)

    expect(
      await screen.findByText("No Members with these Membership Statuses."),
    ).toBeInTheDocument()
  })
})
