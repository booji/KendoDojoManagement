/**
 * Unit tests for SessionDetailPage (issue #54).
 *
 * Acceptance criteria covered:
 *   AC1 — route /sessions/:id renders correctly for a valid session ID
 *   AC2 — member view shows required fields; coach_notes is NOT rendered
 *   AC3 — info renders as Markdown (not raw text)
 *   AC4 — check-in button calls POST /sessions/{id}/checkin
 *   AC5 — checkin_url is shown when present
 *   AC6 — admin view shows coach_notes, attendance list, edit controls, cancel controls
 *   AC7 — edit form pre-populates with current values and calls PUT /sessions/{id}
 *   AC8 — cancel instance calls POST /sessions/{id}/cancel;
 *          cancel series calls DELETE /sessions/templates/{template_id}
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"

import SessionDetailPage from "@/pages/SessionDetailPage"

// ── Shared fixtures ────────────────────────────────────────────────────────────

const SESSION_ID = "aaaabbbb-0000-0000-0000-000000000001"
const TEMPLATE_ID = "tttttttt-0000-0000-0000-000000000002"

const TYPE_ID = "stst-0001-0000-0000-000000000000"

const BASE_SESSION = {
  id: SESSION_ID,
  title: "Evening Practice",
  date: "2026-04-20",
  start_time: "19:00",
  duration_minutes: 90,
  notes: null,
  template_id: TEMPLATE_ID,
  cancelled: false,
  location: "Main dojo",
  info: "Some **markdown** info",
  coach_notes: null,
  checkin_url: null,
  segments: [
    {
      id: "seg-0001",
      start_time: "19:00",
      duration_minutes: 90,
      coach_notes: null,
      type_ids: [TYPE_ID],
    },
  ],
}

const SESSION_TYPES = [
  { id: TYPE_ID, name: "General Training", colour: "#3366ff" },
]

const ADMIN_SESSION = {
  ...BASE_SESSION,
  coach_notes: "Admin-only **markdown** notes",
}

const SESSION_WITH_CHECKIN_URL = {
  ...BASE_SESSION,
  checkin_url: "https://dojo.example.com/checkin/abc123",
}

const ATTENDANCE = [
  {
    id: "att-0001",
    session_id: SESSION_ID,
    member_id: "mem-0001",
    visitor_name: null,
    checked_in_at: "2026-04-20T19:05:00Z",
    recorded_by: "mem-0001",
  },
]

// ── Helper: render with router ─────────────────────────────────────────────────

function renderDetailPage(sessionId: string = SESSION_ID) {
  return render(
    <MemoryRouter initialEntries={[`/sessions/${sessionId}`]}>
      <Routes>
        <Route path="/sessions/:id" element={<SessionDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

// ── Fetch mock helpers ─────────────────────────────────────────────────────────

function mockFetch(responses: Record<string, { status: number; body: unknown }>) {
  return vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : (input as Request).url
    for (const [pattern, { status, body }] of Object.entries(responses)) {
      if (url.includes(pattern)) {
        return new Response(JSON.stringify(body), {
          status,
          headers: { "Content-Type": "application/json" },
        })
      }
    }
    if (url.includes("/session-types")) {
      return new Response(JSON.stringify(SESSION_TYPES), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    }
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
})

// ── AC1 — page renders for a valid session ID ──────────────────────────────────

describe("AC1 — renders session detail page", () => {
  it("displays the session date and time after loading", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: BASE_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", is_active: true, theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByText(/2026-04-20|20.*Apr|Apr.*20/i)).toBeInTheDocument()
    })
  })
})

// ── AC2 — member sees required fields; coach_notes hidden ─────────────────────

describe("AC2 — member view", () => {
  beforeEach(() => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: BASE_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", is_active: true, theme: "system" } },
    })
  })

  it("renders the session duration", async () => {
    renderDetailPage()
    await waitFor(() => {
      expect(screen.getByText(/90/)).toBeInTheDocument()
    })
  })

  it("renders the session location", async () => {
    renderDetailPage()
    await waitFor(() => {
      expect(screen.getByText(/Main dojo/i)).toBeInTheDocument()
    })
  })

  it("renders the start time", async () => {
    renderDetailPage()
    await waitFor(() => {
      expect(screen.getAllByText(/19:00/).length).toBeGreaterThan(0)
    })
  })

  it("does NOT render a coach_notes section when coach_notes is null", async () => {
    renderDetailPage()
    await waitFor(() => {
      // Wait for the page to load fully (date visible)
      expect(screen.getAllByText(/19:00/).length).toBeGreaterThan(0)
    })
    expect(screen.queryByText(/coach.*notes/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/admin.only/i)).not.toBeInTheDocument()
  })
})

// ── AC3 — info renders as Markdown ────────────────────────────────────────────

describe("AC3 — Markdown rendering", () => {
  it("renders info field as Markdown — bold text is a <strong> element, not raw **", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: BASE_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", is_active: true, theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      // "markdown" should appear as formatted bold text, not raw **markdown**
      expect(screen.getByRole("strong") ?? screen.queryByText(/\*\*markdown\*\*/)).toBeTruthy()
    })

    // Raw markdown syntax must not appear
    expect(screen.queryByText(/\*\*markdown\*\*/)).not.toBeInTheDocument()
  })

  it("renders coach_notes as Markdown for admin", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: ADMIN_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: ATTENDANCE },
      [`/auth/me`]: { status: 200, body: { role: "admin", sub: "a1", email: "a@t.com", is_active: true, theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      // Coach notes content visible (but not raw **)
      expect(screen.getByText(/Admin-only/i)).toBeInTheDocument()
    })

    expect(screen.queryByText(/\*\*markdown\*\*/)).not.toBeInTheDocument()
  })
})

// ── AC4 — check-in button calls POST /sessions/{id}/checkin ───────────────────

describe("AC4 — check-in button", () => {
  it("shows a Check In button and calls POST /sessions/{id}/checkin on click", async () => {
    const user = userEvent.setup()

    let checkinCalled = false
    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url
      const method = typeof input === "string" ? "GET" : (input as Request).method

      if (url.includes(`/sessions/${SESSION_ID}/checkin`) && method === "POST") {
        checkinCalled = true
        return new Response(
          JSON.stringify({ id: "att-new", session_id: SESSION_ID, member_id: "u1", visitor_name: null, checked_in_at: new Date().toISOString(), recorded_by: "u1" }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        )
      }
      if (url.includes(`/sessions/${SESSION_ID}/attendance`)) {
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes(`/sessions/${SESSION_ID}`)) {
        return new Response(JSON.stringify(BASE_SESSION), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes("/auth/me")) {
        return new Response(
          JSON.stringify({ role: "member", sub: "u1", email: "m@t.com", is_active: true, theme: "system" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        )
      }
      if (url.includes("/session-types")) {
        return new Response(JSON.stringify(SESSION_TYPES), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /check.?in/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /check.?in/i }))

    await waitFor(() => {
      expect(checkinCalled).toBe(true)
    })
  })
})

// ── AC5 — checkin_url shown when present ──────────────────────────────────────

describe("AC5 — checkin_url display", () => {
  it("shows the checkin URL when the session has a checkin_url", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: SESSION_WITH_CHECKIN_URL },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", is_active: true, theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByText(/https:\/\/dojo\.example\.com\/checkin\/abc123/i)).toBeInTheDocument()
    })
  })
})

// ── AC6 — admin view shows coach_notes, attendance, edit + cancel controls ─────

describe("AC6 — admin view", () => {
  beforeEach(() => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: ADMIN_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: ATTENDANCE },
      [`/auth/me`]: { status: 200, body: { role: "admin", sub: "a1", email: "a@t.com", is_active: true, theme: "system" } },
    })
  })

  it("shows coach_notes section for admin", async () => {
    renderDetailPage()
    await waitFor(() => {
      expect(screen.getByText(/Admin-only/i)).toBeInTheDocument()
    })
  })

  it("shows attendance list for admin", async () => {
    renderDetailPage()
    await waitFor(() => {
      // Either the attendance list heading or the member id
      expect(
        screen.getByText(/attendance/i) ?? screen.getByText(/mem-0001/)
      ).toBeInTheDocument()
    })
  })

  it("shows an edit button for admin", async () => {
    renderDetailPage()
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument()
    })
  })

  it("shows a cancel button for admin", async () => {
    renderDetailPage()
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /cancel/i })
      ).toBeInTheDocument()
    })
  })
})

// ── AC7 — edit form pre-populates and calls PUT /sessions/{id} ─────────────────

describe("AC7 — edit form", () => {
  it("pre-populates the edit form with current session values", async () => {
    const user = userEvent.setup()

    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: ADMIN_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "admin", sub: "a1", email: "a@t.com", is_active: true, theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /edit/i }))

    await waitFor(() => {
      // Form should be visible with pre-populated date value
      expect(screen.getByDisplayValue("2026-04-20")).toBeInTheDocument()
    })
  })

  it("submits PUT /sessions/{id} when the edit form is saved", async () => {
    const user = userEvent.setup()
    let putCalled = false

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url
      const method = typeof input === "string" ? "GET" : (input as Request).method

      if (url.includes(`/sessions/${SESSION_ID}`) && method === "PUT") {
        putCalled = true
        return new Response(JSON.stringify(ADMIN_SESSION), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes(`/sessions/${SESSION_ID}/attendance`)) {
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes(`/sessions/${SESSION_ID}`)) {
        return new Response(JSON.stringify(ADMIN_SESSION), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes("/auth/me")) {
        return new Response(
          JSON.stringify({ role: "admin", sub: "a1", email: "a@t.com", is_active: true, theme: "system" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        )
      }
      if (url.includes("/session-types")) {
        return new Response(JSON.stringify(SESSION_TYPES), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /edit/i }))

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /save/i }))

    await waitFor(() => {
      expect(putCalled).toBe(true)
    })
  })
})

// ── AC8 — cancel instance / cancel series ─────────────────────────────────────

describe("AC8 — cancel controls", () => {
  it("calls POST /sessions/{id}/cancel when cancelling the instance", async () => {
    const user = userEvent.setup()
    let cancelInstanceCalled = false

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url
      const method = typeof input === "string" ? "GET" : (input as Request).method

      if (url.includes(`/sessions/${SESSION_ID}/cancel`) && method === "POST") {
        cancelInstanceCalled = true
        return new Response(JSON.stringify({ ...ADMIN_SESSION, cancelled: true }), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes(`/sessions/${SESSION_ID}/attendance`)) {
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes(`/sessions/${SESSION_ID}`)) {
        return new Response(JSON.stringify(ADMIN_SESSION), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes("/auth/me")) {
        return new Response(
          JSON.stringify({ role: "admin", sub: "a1", email: "a@t.com", is_active: true, theme: "system" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        )
      }
      if (url.includes("/session-types")) {
        return new Response(JSON.stringify(SESSION_TYPES), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /cancel.*session|cancel.*instance/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /cancel.*session|cancel.*instance/i }))

    // May show a confirmation dialog — confirm if present
    const confirmBtn = screen.queryByRole("button", { name: /confirm/i })
    if (confirmBtn) {
      await user.click(confirmBtn)
    }

    await waitFor(() => {
      expect(cancelInstanceCalled).toBe(true)
    })
  })

  it("calls DELETE /sessions/templates/{template_id} when cancelling the series", async () => {
    const user = userEvent.setup()
    let cancelSeriesCalled = false

    vi.spyOn(global, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : (input as Request).url
      const method = typeof input === "string" ? "GET" : (input as Request).method

      if (url.includes(`/sessions/templates/${TEMPLATE_ID}`) && method === "DELETE") {
        cancelSeriesCalled = true
        return new Response(null, { status: 204 })
      }
      if (url.includes(`/sessions/${SESSION_ID}/attendance`)) {
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes(`/sessions/${SESSION_ID}`)) {
        return new Response(JSON.stringify(ADMIN_SESSION), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      if (url.includes("/auth/me")) {
        return new Response(
          JSON.stringify({ role: "admin", sub: "a1", email: "a@t.com", is_active: true, theme: "system" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        )
      }
      if (url.includes("/session-types")) {
        return new Response(JSON.stringify(SESSION_TYPES), { status: 200, headers: { "Content-Type": "application/json" } })
      }
      return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /cancel.*series|cancel.*template/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /cancel.*series|cancel.*template/i }))

    // May show a confirmation dialog — confirm if present
    const confirmBtn = screen.queryByRole("button", { name: /confirm/i })
    if (confirmBtn) {
      await user.click(confirmBtn)
    }

    await waitFor(() => {
      expect(cancelSeriesCalled).toBe(true)
    })
  })
})
