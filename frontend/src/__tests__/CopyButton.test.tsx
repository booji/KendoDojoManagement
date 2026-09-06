/**
 * Tests for CopyButton.
 *
 * One copy-to-clipboard control, extracted because the same shape (copied
 * state, a 2s reset, "Copied!") had been written four times: SessionsPage's
 * iCal widget, AdminInvitesPage, MemberDetailPage's recovery token, and now
 * the session check-in link.
 *
 * Acceptance criteria covered:
 *   AC1 — clicking copies the value to the clipboard
 *   AC2 — the label confirms the copy, then reverts
 *   AC3 — a clipboard rejection is soft: no throw, label stays "Copy"
 *   AC4 — the accessible name distinguishes one instance from another
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import CopyButton from "@/components/CopyButton"

const writeText = vi.fn()

beforeEach(() => {
  writeText.mockReset().mockResolvedValue(undefined)
  // navigator.clipboard is getter-only in jsdom, so it has to be redefined
  // rather than assigned.
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  })
})

describe("AC1 — copies the value", () => {
  it("writes the given value to the clipboard", async () => {
    render(<CopyButton value="https://dojo.test/checkin/session/abc" label="Copy check-in link" />)

    await userEvent.click(screen.getByRole("button", { name: "Copy check-in link" }))

    expect(writeText).toHaveBeenCalledWith("https://dojo.test/checkin/session/abc")
  })
})

describe("AC2 — confirms, then reverts", () => {
  it("shows Copied! after a copy and returns to Copy", async () => {
    render(<CopyButton value="x" label="Copy check-in link" />)

    await userEvent.click(screen.getByRole("button", { name: "Copy check-in link" }))
    expect(await screen.findByText("Copied!")).toBeInTheDocument()

    // Real timers: the confirmation is 2s, and faking them here fights
    // userEvent's own scheduling for no gain in one short test.
    await waitFor(() => expect(screen.getByText("Copy")).toBeInTheDocument(), {
      timeout: 4000,
    })
  }, 10000)
})

describe("AC3 — a clipboard failure is soft", () => {
  it("does not throw and leaves the label alone when the write rejects", async () => {
    // Insecure context or denied permission — the value is still on screen to
    // select by hand, so this must not surface as an error.
    writeText.mockRejectedValue(new Error("denied"))
    render(<CopyButton value="x" label="Copy check-in link" />)

    await userEvent.click(screen.getByRole("button", { name: "Copy check-in link" }))

    await waitFor(() => expect(writeText).toHaveBeenCalled())
    expect(screen.getByText("Copy")).toBeInTheDocument()
  })
})

describe("AC4 — accessible name", () => {
  it("uses the given label as the accessible name", () => {
    render(<CopyButton value="x" label="Copy invite link" />)

    expect(screen.getByRole("button", { name: "Copy invite link" })).toBeInTheDocument()
  })
})
