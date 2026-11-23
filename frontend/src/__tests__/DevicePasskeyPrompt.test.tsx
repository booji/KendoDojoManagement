/**
 * After a sign-in from a phone (or a security key), offer a passkey for this
 * device (#612). The offer survives the full page load that follows login; a
 * dismissal is remembered per device.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import DevicePasskeyPrompt from "@/components/DevicePasskeyPrompt"
import { noteSignInAttachment } from "@/lib/devicePasskeyOffer"

const performPasskeyAddMock = vi.fn()

vi.mock("@/api/auth", () => ({
  performPasskeyAdd: () => performPasskeyAddMock(),
}))

const prompt = () => screen.queryByRole("dialog", { name: /add a passkey on this device/i })

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  localStorage.clear()
})

describe("DevicePasskeyPrompt", () => {
  it("appears after a cross-platform sign-in", async () => {
    noteSignInAttachment("cross-platform")
    render(<DevicePasskeyPrompt onClose={() => {}} />)
    await waitFor(() => expect(prompt()).toBeInTheDocument())
  })

  it.each([["platform" as const], [null]])("does not appear after a %s sign-in", (attachment) => {
    noteSignInAttachment(attachment)
    render(<DevicePasskeyPrompt onClose={() => {}} />)
    expect(prompt()).not.toBeInTheDocument()
  })

  it("stays away on this device once dismissed", async () => {
    noteSignInAttachment("cross-platform")
    const { unmount } = render(<DevicePasskeyPrompt onClose={() => {}} />)
    await userEvent.click(await screen.findByRole("button", { name: "Not now" }))
    await waitFor(() => expect(prompt()).not.toBeInTheDocument())
    unmount()

    noteSignInAttachment("cross-platform")
    render(<DevicePasskeyPrompt onClose={() => {}} />)
    expect(prompt()).not.toBeInTheDocument()
  })

  it("adds a passkey through the Add passkey flow", async () => {
    performPasskeyAddMock.mockResolvedValue({ sub: "acc-1", show_nudge: false })
    noteSignInAttachment("cross-platform")
    render(<DevicePasskeyPrompt onClose={() => {}} />)

    await userEvent.click(await screen.findByRole("button", { name: "Add passkey" }))

    expect(performPasskeyAddMock).toHaveBeenCalledOnce()
    await waitFor(() => expect(prompt()).not.toBeInTheDocument())
  })

  it("keeps the prompt open with the error when adding fails", async () => {
    performPasskeyAddMock.mockRejectedValue({ status: 0, message: "Passkey registration failed" })
    noteSignInAttachment("cross-platform")
    render(<DevicePasskeyPrompt onClose={() => {}} />)

    await userEvent.click(await screen.findByRole("button", { name: "Add passkey" }))

    expect(await screen.findByRole("alert")).toHaveTextContent("Passkey registration failed")
    expect(prompt()).toBeInTheDocument()
  })
})
