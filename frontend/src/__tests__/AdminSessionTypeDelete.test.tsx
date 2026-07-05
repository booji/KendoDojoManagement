/**
 * Unit tests for deleting a session type from Admin Settings (issue #183).
 *
 * Acceptance criteria covered:
 *   AC1 — admin can delete an unreferenced session type; it disappears from the list
 *   AC2 — deleting a referenced type shows the backend 409 error and the type remains
 *
 * (AC3 — non-admins cannot see/use the control — is enforced by the RequireAdmin
 *  route guard around /admin/settings, and is asserted by the e2e suite.)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { SessionTypesSection } from "@/pages/AdminSettingsPage"

// We render the Session Types section in isolation — the full page also mounts
// branding + federation sections that depend on the DojoSettings context.

const TYPES = [
  { id: "type-1", name: "General Training", colour: "#3366ff" },
  { id: "type-2", name: "Grading", colour: "#ff6633" },
]

const REFERENCED_DETAIL =
  "Session type 'Grading' cannot be deleted because it is referenced by one or more session segments."

const jsonResponse = (body: unknown, ok = true, status = 200): Response =>
  ({
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }) as unknown as Response

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

// Route every non-session-type request to a benign empty response so the other
// admin sections don't blow up during these tests.
const installFetch = (
  handler: (url: string, init?: RequestInit) => Response,
): void => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
          ? input.toString()
          : input.url
      const method = init?.method ?? (input instanceof Request ? input.method : "GET")
      return Promise.resolve(handler(url, { ...init, method }))
    }),
  )
}

describe("Session type deletion", () => {
  it("AC1: deletes an unreferenced type and removes it from the list", async () => {
    installFetch((url, init) => {
      if (url.includes("/api/session-types") && init?.method === "DELETE") {
        return jsonResponse({ id: "type-2", name: "Grading", colour: "#ff6633" })
      }
      if (url.endsWith("/api/session-types")) {
        return jsonResponse(TYPES)
      }
      return jsonResponse({})
    })

    render(<SessionTypesSection />)

    // wait for the types to load
    expect(await screen.findByText("Grading")).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole("button", { name: /delete grading/i }),
    )

    // confirm in the dialog
    const dialog = await screen.findByRole("dialog")
    await userEvent.click(
      within(dialog).getByRole("button", { name: /^delete$/i }),
    )

    await waitFor(() => {
      expect(screen.queryByText("Grading")).not.toBeInTheDocument()
    })
    expect(screen.getByText("General Training")).toBeInTheDocument()
  })

  it("AC2: shows the backend error and keeps the type when it is referenced", async () => {
    installFetch((url, init) => {
      if (url.includes("/api/session-types") && init?.method === "DELETE") {
        return jsonResponse({ detail: REFERENCED_DETAIL }, false, 409)
      }
      if (url.endsWith("/api/session-types")) {
        return jsonResponse(TYPES)
      }
      return jsonResponse({})
    })

    render(<SessionTypesSection />)

    expect(await screen.findByText("Grading")).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole("button", { name: /delete grading/i }),
    )
    const dialog = await screen.findByRole("dialog")
    await userEvent.click(
      within(dialog).getByRole("button", { name: /^delete$/i }),
    )

    // error surfaced, type still present in the list (its row label remains)
    expect(await screen.findByText(REFERENCED_DETAIL)).toBeInTheDocument()
    expect(screen.getByText("Grading", { selector: "label" })).toBeInTheDocument()
  })
})
