/**
 * Unit tests for SessionDetailPage (issue #54).
 *
 * Acceptance criteria covered:
 *   AC1 — route /sessions/:id renders correctly for a valid session ID
 *   AC2 — member view shows required fields; coach_notes is NOT rendered
 *   AC3 — info renders as Markdown (not raw text)
 *   AC4 — check-in button calls POST /sessions/{id}/checkin
 *   AC5 — the session's check-in link is shown to admins only
 *   AC6 — admin view shows coach_notes, attendance list, edit controls, cancel controls
 *   AC7 — edit form pre-populates with current values and calls PUT /sessions/{id}
 *   AC8 — cancel instance calls POST /sessions/{id}/cancel;
 *          cancel series calls DELETE /sessions/templates/{template_id};
 *          both only after a confirm dialog (#579)
 *   #579 — a cancelled Session can be reinstated
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
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
  template_id: TEMPLATE_ID,
  cancelled: false,
  location: "Main dojo",
  info: "Some **markdown** info",
  coach_notes: null,
  checkin_link: "https://dojo.example.com/checkin/session/aaaabbbb-0000-0000-0000-000000000001",
  segments: [
    {
      id: "seg-0001",
      start_time: "19:00",
      duration_minutes: 90,
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
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", theme: "system" } },
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
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", theme: "system" } },
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

// ── Issue #182 — per-segment public title in the breakdown (note gone, #406) ──

describe("issue #182 — segment title", () => {
  const SESSION_WITH_TITLE = {
    ...BASE_SESSION,
    segments: [
      {
        id: "seg-0001",
        start_time: "20:00",
        duration_minutes: 30,
        coach_notes: null,
        title: "Footwork drills",
        type_ids: [TYPE_ID],
      },
    ],
  }

  it("renders the segment title in the breakdown", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: SESSION_WITH_TITLE },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByText("Footwork drills")).toBeInTheDocument()
    })
  })

  it("never renders a lingering note from a pre-#406 row", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: {
        status: 200,
        body: {
          ...SESSION_WITH_TITLE,
          segments: [{ ...SESSION_WITH_TITLE.segments[0], note: "stale text" }],
        },
      },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByText("Footwork drills")).toBeInTheDocument()
    })
    expect(screen.queryByText("stale text")).not.toBeInTheDocument()
  })

  it("renders a segment cleanly when the title is absent", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: BASE_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getAllByText(/19:00/).length).toBeGreaterThan(0)
    })
    // No empty paragraphs / dangling separators when the title is absent.
    expect(screen.queryByText("Footwork drills")).not.toBeInTheDocument()
  })
})

// ── AC3 — info renders as Markdown ────────────────────────────────────────────

describe("AC3 — Markdown rendering", () => {
  it("renders info field as Markdown — bold text is a <strong> element, not raw **", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: BASE_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", theme: "system" } },
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
      [`/auth/me`]: { status: 200, body: { role: "admin", sub: "a1", email: "a@t.com", theme: "system" } },
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
    vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : (input as Request).url
      // The api layer calls fetch(path, init), so the method lives in init.
      // (It used to build a Request object; both shapes are read here.)
      const method =
        init?.method ?? (typeof input === "string" ? "GET" : (input as Request).method)

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
          JSON.stringify({ role: "member", sub: "u1", email: "m@t.com", theme: "system" }),
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

// ── AC5 — check-in link is admin-only ─────────────────────────────────────────

describe("AC5 — check-in link display", () => {
  it("shows the session's check-in link to an admin", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: ADMIN_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "admin", sub: "a1", email: "a@t.com", theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByText(BASE_SESSION.checkin_link)).toBeInTheDocument()
    })
  })

  it("does not show it to a member — sharing the link is an admin action", async () => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: BASE_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: [] },
      [`/auth/me`]: { status: 200, body: { role: "member", sub: "u1", email: "m@t.com", theme: "system" } },
    })

    renderDetailPage()

    await waitFor(() => {
      expect(screen.getByText("Evening Practice")).toBeInTheDocument()
    })
    expect(screen.queryByText(BASE_SESSION.checkin_link)).not.toBeInTheDocument()
  })
})

// ── AC6 — admin view shows coach_notes, attendance, edit + cancel controls ─────

describe("AC6 — admin view", () => {
  beforeEach(() => {
    mockFetch({
      [`/sessions/${SESSION_ID}`]: { status: 200, body: ADMIN_SESSION },
      [`/sessions/${SESSION_ID}/attendance`]: { status: 200, body: ATTENDANCE },
      [`/auth/me`]: { status: 200, body: { role: "admin", sub: "a1", email: "a@t.com", theme: "system" } },
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
      [`/auth/me`]: { status: 200, body: { role: "admin", sub: "a1", email: "a@t.com", theme: "system" } },
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
    // #430: info and coach notes cover both audiences; no third free-text field.
    expect(screen.queryByLabelText(/^notes$/i)).not.toBeInTheDocument()
  })

  it("submits PUT /sessions/{id} when the edit form is saved", async () => {
    const user = userEvent.setup()
    let putCalled = false

    vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : (input as Request).url
      // The api layer calls fetch(path, init), so the method lives in init.
      // (It used to build a Request object; both shapes are read here.)
      const method =
        init?.method ?? (typeof input === "string" ? "GET" : (input as Request).method)

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
          JSON.stringify({ role: "admin", sub: "a1", email: "a@t.com", theme: "system" }),
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

// ── AC8 — cancel instance / cancel series, behind confirm dialogs (#579) ─────

/** A fake admin backend that remembers the session's Cancellation. */
function mockAdminServer(initial = ADMIN_SESSION) {
  const calls: string[] = []
  let session = { ...initial }
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
  vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : (input as Request).url
    const method = init?.method ?? "GET"
    if (method !== "GET") calls.push(`${method} ${url}`)
    if (url.includes(`/sessions/${SESSION_ID}/cancel`)) {
      session = { ...session, cancelled: true }
      return json(session)
    }
    if (url.includes(`/sessions/${SESSION_ID}/reinstate`)) {
      session = { ...session, cancelled: false }
      return json(session)
    }
    if (url.includes(`/sessions/templates/${TEMPLATE_ID}`) && method === "DELETE") {
      session = { ...session, cancelled: true }
      return json({ id: TEMPLATE_ID })
    }
    if (url.includes(`/sessions/${SESSION_ID}/attendance`)) return json([])
    if (url.includes(`/sessions/${SESSION_ID}`)) return json(session)
    if (url.includes("/auth/me")) return json({ role: "admin", sub: "a1", email: "a@t.com", theme: "system" })
    if (url.includes("/session-types")) return json(SESSION_TYPES)
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
  })
  return calls
}

describe("AC8 — cancel controls", () => {
  it("asks for confirmation before cancelling the session, focusing Cancel", async () => {
    const user = userEvent.setup()
    const calls = mockAdminServer()
    renderDetailPage()

    await user.click(await screen.findByRole("button", { name: "Cancel Session" }))

    const dialog = await screen.findByRole("dialog")
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus())
    expect(calls).toEqual([])

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(calls).toEqual([])
  })

  it("cancels the session on confirm and hides the cancel actions", async () => {
    const user = userEvent.setup()
    const calls = mockAdminServer()
    renderDetailPage()

    await user.click(await screen.findByRole("button", { name: "Cancel Session" }))
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel session" }))

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    expect(calls).toEqual([`POST /api/sessions/${SESSION_ID}/cancel`])
    expect(screen.getByText("Cancelled")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Cancel Session" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Cancel Series" })).not.toBeInTheDocument()
  })

  it("cancels the series only on confirm, then shows the refetched Session", async () => {
    const user = userEvent.setup()
    const calls = mockAdminServer()
    renderDetailPage()

    await user.click(await screen.findByRole("button", { name: "Cancel Series" }))
    const dialog = await screen.findByRole("dialog")
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus())
    expect(calls).toEqual([])

    await user.click(within(dialog).getByRole("button", { name: "Cancel series" }))

    await waitFor(() => expect(screen.getByText("Cancelled")).toBeInTheDocument())
    expect(calls).toEqual([`DELETE /api/sessions/templates/${TEMPLATE_ID}`])
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Cancel Series" })).not.toBeInTheDocument()
  })
})

describe("Reinstate (#579)", () => {
  it("reinstates a cancelled Session and brings the cancel actions back", async () => {
    const user = userEvent.setup()
    const calls = mockAdminServer({ ...ADMIN_SESSION, cancelled: true })
    renderDetailPage()

    await user.click(await screen.findByRole("button", { name: "Reinstate Session" }))

    expect(await screen.findByRole("button", { name: "Cancel Session" })).toBeInTheDocument()
    expect(calls).toEqual([`POST /api/sessions/${SESSION_ID}/reinstate`])
    expect(screen.queryByText("Cancelled")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Reinstate Session" })).not.toBeInTheDocument()
  })
})
