/**
 * The notification bell (#611): what is waiting for the user's action,
 * derived live from GET /grades/pending. Nothing is stored.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Link, MemoryRouter } from "react-router-dom"

import NotificationBell from "@/components/NotificationBell"
import { useNotifications } from "@/hooks/useNotifications"

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })

const pending = (id: string, member_name: string, display_name: string) => ({
  id,
  member_id: `m-${id}`,
  member_name,
  grade: "shodan",
  display_name,
  promoted_at: "2026-11-01",
  status: "pending",
})

const Harness = ({ role }: { role: "admin" | "member" }) => {
  const items = useNotifications(role)
  return (
    <>
      <Link to="/elsewhere">Elsewhere</Link>
      {role === "admin" && <NotificationBell items={items} />}
    </>
  )
}

const setVisibility = (state: DocumentVisibilityState) => {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  })
  document.dispatchEvent(new Event("visibilitychange"))
}

const renderBell = (role: "admin" | "member" = "admin") =>
  render(
    <MemoryRouter>
      <Harness role={role} />
    </MemoryRouter>
  )

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.useRealTimers()
    setVisibility("visible")
  })

  it("names the bell with the pending count", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      json([pending("1", "Ai Sato", "Shodan"), pending("2", "Ken Ito", "Nidan")])
    )
    renderBell()
    expect(
      await screen.findByRole("button", { name: "Notifications, 2 pending" })
    ).toHaveTextContent("2")
  })

  it("lists each pending submission, linking to Grade settings", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      json([pending("1", "Ai Sato", "Shodan"), pending("2", "Ken Ito", "Nidan")])
    )
    renderBell()
    await userEvent.click(
      await screen.findByRole("button", { name: "Notifications, 2 pending" })
    )
    const ai = await screen.findByRole("link", { name: /Ai Sato.*Shodan/ })
    const ken = screen.getByRole("link", { name: /Ken Ito.*Nidan/ })
    expect(ai).toHaveAttribute("href", "/admin/settings/grades")
    expect(ken).toHaveAttribute("href", "/admin/settings/grades")
  })

  it("shows no count when nothing is pending", async () => {
    const fetch = vi.spyOn(global, "fetch").mockResolvedValue(json([]))
    renderBell()
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    const bell = screen.getByRole("button", { name: "Notifications" })
    expect(bell).toHaveTextContent("")
  })

  it("refreshes on route change, dropping a decided submission", async () => {
    vi.spyOn(global, "fetch")
      .mockResolvedValueOnce(json([pending("1", "Ai Sato", "Shodan")]))
      .mockResolvedValue(json([]))
    renderBell()
    await screen.findByRole("button", { name: "Notifications, 1 pending" })
    await userEvent.click(screen.getByRole("link", { name: "Elsewhere" }))
    expect(
      await screen.findByRole("button", { name: "Notifications" })
    ).toBeInTheDocument()
  })

  it("polls every 60 s while the tab is visible, and stops while hidden", async () => {
    vi.useFakeTimers()
    const fetch = vi.spyOn(global, "fetch").mockResolvedValue(json([]))
    renderBell()
    expect(fetch).toHaveBeenCalledTimes(1)

    await act(() => vi.advanceTimersByTimeAsync(60_000))
    expect(fetch).toHaveBeenCalledTimes(2)

    act(() => setVisibility("hidden"))
    await act(() => vi.advanceTimersByTimeAsync(180_000))
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it("does not fetch for a Member", async () => {
    const fetch = vi.spyOn(global, "fetch").mockResolvedValue(json([]))
    renderBell("member")
    expect(screen.queryByRole("button", { name: /Notifications/ })).toBeNull()
    expect(fetch).not.toHaveBeenCalled()
  })
})
