/**
 * Unit tests for the federation catalogue empty state (issue #219).
 *
 * The catalogue no longer ships pre-populated, so a fresh instance starts with
 * nothing in it. Acceptance criteria covered:
 *   AC1 — an empty catalogue with no active filter links to the FIK affiliate list
 *   AC2 — a search matching nothing keeps the plain "no federations found" message
 *
 * Filtering is server-side, so the loaded list is already filtered; "catalogue is
 * empty" is therefore zero results *with no filter active*.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { AdminFederationCatalogue } from "@/pages/AdminSettingsPage"

const FIK_URL = "https://www.kendo-fik.org/organization/affiliate"

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

/** Serve the federation list from `rows`, keyed by whether a search is present. */
const installFetch = (
  federationsFor: (url: string) => unknown[],
): void => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
          ? input.toString()
          : input.url
      if (url.includes("/api/federations")) {
        return Promise.resolve(jsonResponse(federationsFor(url)))
      }
      return Promise.resolve(jsonResponse({}))
    }),
  )
}

describe("Federation catalogue empty state", () => {
  it("AC1: links to the FIK affiliate list when the catalogue is empty", async () => {
    installFetch(() => [])

    render(<AdminFederationCatalogue />)

    const link = await screen.findByRole("link", { name: /fik affiliate/i })
    expect(link).toHaveAttribute("href", FIK_URL)
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"))
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"))
    expect(link).toHaveAttribute("target", "_blank")
  })

  it("AC2: shows the plain message when a search matches nothing", async () => {
    // Populated catalogue, but any search returns no rows.
    installFetch((url) => (url.includes("search=") ? [] : [BKA]))

    render(<AdminFederationCatalogue />)

    expect(await screen.findByText("British Kendo Association")).toBeInTheDocument()

    await userEvent.type(
      screen.getByRole("textbox", { name: /search federations/i }),
      "zzzz",
    )

    await waitFor(() => {
      expect(screen.getByText(/no federations found/i)).toBeInTheDocument()
    })
    expect(
      screen.queryByRole("link", { name: /fik affiliate/i }),
    ).not.toBeInTheDocument()
  })
})

const BKA = {
  id: "fed-1",
  name: "British Kendo Association",
  abbreviation: "BKA",
  iso_code: "GB",
  website: "https://www.kendo.org.uk",
  continental_grouping: "Europe",
  type: "National",
  is_pinned: false,
  is_active: true,
}
