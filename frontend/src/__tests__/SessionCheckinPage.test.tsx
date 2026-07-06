/**
 * Unit tests for SessionCheckinPage (issue #191 — tokenless check-in link
 * in the iCal feed).
 *
 * This is the page the new /checkin/session/:id route renders. It drives
 * POST /sessions/{id}/checkin directly (no single-use token involved — that
 * flow is the existing /checkin/:token page and is left untouched).
 *
 * Acceptance criteria covered:
 *   - success: 2xx from POST /sessions/{id}/checkin shows a success state
 *   - already-checked-in: 409 with detail "Already checked in" shows that
 *     specific state (not the same message as cancelled)
 *   - cancelled: 409 with detail "Session is cancelled" shows a cancelled
 *     state
 *   - not-found: 404 shows a not-found state
 *   - unauthenticated: 401 redirects to /login (and back afterwards)
 *
 * SessionCheckinPage does not exist yet, so every test below fails at
 * import time — this is the expected RED state.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import SessionCheckinPage from "@/pages/SessionCheckinPage"

const SESSION_ID = "cccccccc-0000-0000-0000-000000000001"

function renderCheckinPage(sessionId: string = SESSION_ID) {
  return render(
    <MemoryRouter initialEntries={[`/checkin/session/${sessionId}`]}>
      <Routes>
        <Route path="/checkin/session/:id" element={<SessionCheckinPage />} />
        <Route path="/login" element={<div>Login Page</div>} />
        <Route path="/sessions" element={<div>Sessions Page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

function mockCheckinResponse(status: number, body: unknown) {
  return vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url
    if (url.includes(`/sessions/${SESSION_ID}/checkin`)) {
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe("success state", () => {
  it("shows a success message after a 2xx check-in response", async () => {
    mockCheckinResponse(201, {
      id: "att-new",
      session_id: SESSION_ID,
      member_id: "u1",
      visitor_name: null,
      checked_in_at: new Date().toISOString(),
      recorded_by: "u1",
    })

    renderCheckinPage()

    await waitFor(() => {
      expect(screen.getByText(/checked in/i)).toBeInTheDocument()
    })
  })
})

describe("already-checked-in state (409)", () => {
  it("shows an already-checked-in message distinct from the cancelled message", async () => {
    mockCheckinResponse(409, { detail: "Already checked in" })

    renderCheckinPage()

    await waitFor(() => {
      expect(screen.getByText(/already checked in/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/cancelled/i)).not.toBeInTheDocument()
  })
})

describe("cancelled state (409)", () => {
  it("shows a cancelled message distinct from the already-checked-in message", async () => {
    mockCheckinResponse(409, { detail: "Session is cancelled" })

    renderCheckinPage()

    await waitFor(() => {
      expect(screen.getByText(/cancelled/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/already checked in/i)).not.toBeInTheDocument()
  })
})

describe("not-found state (404)", () => {
  it("shows a not-found message when the session does not exist", async () => {
    mockCheckinResponse(404, { detail: "Session not found" })

    renderCheckinPage()

    await waitFor(() => {
      expect(screen.getByText(/not found/i)).toBeInTheDocument()
    })
  })
})

describe("unauthenticated (401)", () => {
  it("redirects to /login when the user is not authenticated", async () => {
    mockCheckinResponse(401, { detail: "Not authenticated" })

    renderCheckinPage()

    await waitFor(() => {
      expect(screen.getByText(/login page/i)).toBeInTheDocument()
    })
  })
})
