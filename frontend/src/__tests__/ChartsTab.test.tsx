/**
 * The Charts tab on /reports (#560): the tab-wide Membership Status filter and
 * the grade distribution it scopes. The server owns the counting rules; these
 * tests cover what the Admin asks for and what they are shown.
 */

import { describe, it, expect, vi, afterEach } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import ChartsTab from "@/components/reports/ChartsTab"

const MUKYU_3_SHODAN_1 = [
  { grade: "MUKYUU", display_name: "Mukyū", count: 3 },
  { grade: "ROKKYUU", display_name: "Rokkyū (6-kyu)", count: 0 },
  { grade: "SHODAN", display_name: "Shodan (1-dan)", count: 1 },
]

const TWO_SESSIONS = [
  { session_id: "s1", date: "2026-03-05", members: 12, visitors: 2 },
  { session_id: "s2", date: "2026-03-12", members: 9, visitors: 0 },
]

const stubFetch = (
  body: unknown = MUKYU_3_SHODAN_1,
  headcount: unknown = TWO_SESSIONS,
) => {
  const fetchMock = vi.fn((url: string) => {
    const data = url.includes("/headcount") ? headcount : body
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

const requestedUrls = (
  fetchMock: ReturnType<typeof stubFetch>,
  path = "/api/reports/grades",
) =>
  fetchMock.mock.calls
    .map((call) => String((call as unknown[])[0]))
    .filter((url) => url.startsWith(path))

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
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

describe("Headcount per Session", () => {
  it("shows the Members and Visitors at each Session of the last 90 days", async () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date(2026, 5, 30, 12))
    const fetchMock = stubFetch()

    render(<ChartsTab />)

    const table = await screen.findByRole("table", { name: "Headcount per Session" })
    const rows = within(table).getAllByRole("row").slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      "Thu, 5 Mar 2026122",
      "Thu, 12 Mar 202690",
    ])
    expect(requestedUrls(fetchMock, "/api/reports/headcount")).toEqual([
      "/api/reports/headcount?date_from=2026-04-01&date_to=2026-06-30",
    ])
    expect(screen.getByLabelText("From")).toHaveValue("2026-04-01")
    expect(screen.getByLabelText("To")).toHaveValue("2026-06-30")
  })

  it("asks again over the range the Admin picks", async () => {
    const fetchMock = stubFetch()
    render(<ChartsTab />)
    await screen.findByRole("table", { name: "Headcount per Session" })

    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-01-01" },
    })

    await waitFor(() =>
      expect(requestedUrls(fetchMock, "/api/reports/headcount").at(-1)).toMatch(
        /^\/api\/reports\/headcount\?date_from=2026-01-01&date_to=/,
      ),
    )
  })

  it("ignores the Membership Status filter", async () => {
    const fetchMock = stubFetch()
    render(<ChartsTab />)
    await screen.findByRole("table", { name: "Headcount per Session" })

    await userEvent.click(screen.getByRole("checkbox", { name: "Active" }))
    await userEvent.click(screen.getByRole("checkbox", { name: "Archived" }))

    expect(
      screen.getByRole("table", { name: "Headcount per Session" }),
    ).toBeInTheDocument()
    expect(requestedUrls(fetchMock, "/api/reports/headcount")).toHaveLength(1)
  })

  it("shows the server's reason when it refuses the range", async () => {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(
        url.includes("/headcount")
          ? ({
              ok: false,
              status: 422,
              json: () =>
                Promise.resolve({ detail: "Date range must not exceed 366 days" }),
              text: () =>
                Promise.resolve(
                  JSON.stringify({ detail: "Date range must not exceed 366 days" }),
                ),
            } as unknown as Response)
          : ({
              ok: true,
              status: 200,
              json: () => Promise.resolve(MUKYU_3_SHODAN_1),
              text: () => Promise.resolve(JSON.stringify(MUKYU_3_SHODAN_1)),
            } as unknown as Response),
      ),
    )
    vi.stubGlobal("fetch", fetchMock)

    render(<ChartsTab />)

    expect(
      await screen.findByText("Date range must not exceed 366 days"),
    ).toBeInTheDocument()
  })
})
