/**
 * The Attendance Rate chart on the Charts tab (#562): the 10 highest over the
 * tab's From/To range. The server owns the counting and the 4-Session floor;
 * these tests cover what the Admin asks for and what they are shown.
 */

import { afterEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import ChartsTab from "@/components/reports/ChartsTab"

const RATES = [
  {
    member_id: "m-1",
    display_name: "Kenji Tanaka",
    sessions_attended: 9,
    total_sessions: 10,
    attendance_rate: 0.9,
  },
  {
    member_id: "m-2",
    display_name: "Ai Sato",
    sessions_attended: 2,
    total_sessions: 3,
    attendance_rate: 0.6667,
  },
]

const PATH = "/api/reports/attendance-rates"

const stubFetch = (rates: unknown = RATES) => {
  const fetchMock = vi.fn((url: string) => {
    const body = url.startsWith(PATH) ? rates : []
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

const rateUrls = (fetchMock: ReturnType<typeof stubFetch>) =>
  fetchMock.mock.calls
    .map((call) => String((call as unknown[])[0]))
    .filter((url) => url.startsWith(PATH))

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe("Attendance Rate chart", () => {
  it("lists the highest rates over the last 90 days for active Members", async () => {
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date(2026, 5, 30, 12))
    const fetchMock = stubFetch()

    render(<ChartsTab />)

    const table = await screen.findByRole("table", { name: "Attendance Rate" })
    const rows = within(table).getAllByRole("row").slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      "Kenji Tanaka90%9 of 10",
      "Ai Sato67%2 of 3",
    ])
    expect(rateUrls(fetchMock)).toEqual([
      `${PATH}?date_from=2026-04-01&date_to=2026-06-30&status=active`,
    ])
  })

  it("follows the range and the Membership Status filter", async () => {
    const fetchMock = stubFetch()
    render(<ChartsTab />)
    await screen.findByRole("table", { name: "Attendance Rate" })

    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-01-01" },
    })
    await userEvent.click(screen.getByRole("checkbox", { name: "Archived" }))

    await waitFor(() =>
      expect(rateUrls(fetchMock).at(-1)).toMatch(
        /^\/api\/reports\/attendance-rates\?date_from=2026-01-01&date_to=[\d-]+&status=active&status=archived$/,
      ),
    )
  })

  it("says so when no Member has enough Sessions to rank", async () => {
    stubFetch([])

    render(<ChartsTab />)

    expect(
      await screen.findByText(
        "No Member had 4 or more held Sessions in this range.",
      ),
    ).toBeInTheDocument()
  })
})
