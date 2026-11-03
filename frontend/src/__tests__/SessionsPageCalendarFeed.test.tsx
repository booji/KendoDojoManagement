/**
 * The "Subscribe to iCal feed" popover shows the Calendar Feed URL, which ends
 * in the dojo name. It waits for Dojo Settings: a URL built from the "My Dojo"
 * placeholder would be one the server does not answer.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"

import SessionsPage from "@/pages/SessionsPage"
import { DojoSettingsProvider } from "@/contexts/DojoSettingsProvider"
import { getDojoSettings } from "@/api/settings"

vi.mock("@/api/sessions", () => ({
  getSessions: vi.fn().mockResolvedValue([]),
  getSessionTypes: vi.fn().mockResolvedValue([]),
  getSessionsForRange: vi.fn().mockResolvedValue([]),
}))

vi.mock("@/api/auth", () => ({
  getMe: vi.fn().mockResolvedValue({ role: "member", sub: "u1", email: "m@dojo.test", theme: "system" }),
}))

vi.mock("@/api/settings", () => ({ getDojoSettings: vi.fn() }))

const renderPage = () =>
  render(
    <DojoSettingsProvider>
      <MemoryRouter initialEntries={["/sessions"]}>
        <SessionsPage />
      </MemoryRouter>
    </DojoSettingsProvider>,
  )

describe("SessionsPage Calendar Feed URL", () => {
  beforeEach(() => {
    vi.mocked(getDojoSettings).mockReset()
  })

  it("ends in the dojo name once settings load", async () => {
    vi.mocked(getDojoSettings).mockResolvedValue({
      dojo_name: "Shoshinkai Reading",
      logo_url: null,
      primary_colour: "#4F46E5",
    } as Awaited<ReturnType<typeof getDojoSettings>>)
    renderPage()

    await userEvent.click(await screen.findByRole("button", { name: "Subscribe to iCal feed" }))

    expect(screen.getByLabelText("iCal feed URL")).toHaveValue(
      `${window.location.origin}/api/sessions/ical/Shoshinkai%20Reading`,
    )
  })

  it("is not offered before settings load", async () => {
    vi.mocked(getDojoSettings).mockReturnValue(new Promise(() => undefined))
    renderPage()

    await screen.findByRole("heading", { name: /sessions/i })
    expect(screen.queryByRole("button", { name: "Subscribe to iCal feed" })).not.toBeInTheDocument()
  })
})
