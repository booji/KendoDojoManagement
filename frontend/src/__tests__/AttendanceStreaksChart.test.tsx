/**
 * The Attendance Streaks chart on the Charts tab (#563): the 10 longest this
 * year, an unbroken one marked. The server owns the week walk; these tests cover
 * what the Admin asks for and what they are shown.
 */

import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import ChartsTab from "@/components/reports/ChartsTab"

const STREAKS = [
  { member_id: "m-1", display_name: "Kenji Tanaka", weeks: 6, running: true },
  { member_id: "m-2", display_name: "Ai Sato", weeks: 4, running: false },
]

const stubFetch = (streaks: unknown = STREAKS) => {
  const fetchMock = vi.fn((url: string) => {
    const body = url.startsWith("/api/reports/streaks") ? streaks : []
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

const streakUrls = (fetchMock: ReturnType<typeof stubFetch>) =>
  fetchMock.mock.calls
    .map((call) => String((call as unknown[])[0]))
    .filter((url) => url.startsWith("/api/reports/streaks"))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("Attendance Streaks chart", () => {
  it("lists the longest Attendance Streaks this year, marking one still unbroken", async () => {
    const fetchMock = stubFetch()

    render(<ChartsTab />)

    const table = await screen.findByRole("table", { name: "Attendance Streaks" })
    const rows = within(table).getAllByRole("row").slice(1)
    expect(rows.map((r) => r.textContent)).toEqual([
      "Kenji Tanaka6Yes",
      "Ai Sato4No",
    ])
    expect(streakUrls(fetchMock)).toEqual(["/api/reports/streaks?status=active"])
  })

  it("follows the Membership Status filter", async () => {
    const fetchMock = stubFetch()
    render(<ChartsTab />)
    await screen.findByRole("table", { name: "Attendance Streaks" })

    await userEvent.click(screen.getByRole("checkbox", { name: "Archived" }))

    expect(streakUrls(fetchMock).at(-1)).toBe(
      "/api/reports/streaks?status=active&status=archived",
    )
  })

  it("says so when nobody has an Attendance Streak this year", async () => {
    stubFetch([])

    render(<ChartsTab />)

    expect(
      await screen.findByText("No Attendance Streaks this year."),
    ).toBeInTheDocument()
  })
})
