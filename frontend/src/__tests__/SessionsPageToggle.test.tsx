/**
 * Unit tests for the List/Calendar toggle on SessionsPage (issue #93).
 *
 * Acceptance criteria covered:
 *   AC1 — List and Calendar toggle buttons are present in the toolbar at desktop
 *   AC2 — Clicking "Calendar" replaces content area with CalendarView
 *   AC3 — Clicking "List" restores SessionCardList
 *   AC8 — Toggle container has the responsive hidden class (not rendered on mobile)
 *   AC9 — List is the default view (SessionCardList visible on initial render)
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"

import SessionsPage from "@/pages/SessionsPage"

// ── Mock @/api/sessions ───────────────────────────────────────────────────────

vi.mock("@/api/sessions", () => ({
  getSessions: vi.fn().mockResolvedValue([]),
  getSessionTypes: vi.fn().mockResolvedValue([]),
  getSessionsForRange: vi.fn().mockResolvedValue([]),
  createSession: vi.fn(),
  createSessionTemplate: vi.fn(),
  createSessionType: vi.fn(),
}))

// ── Mock @/api/auth ───────────────────────────────────────────────────────────

vi.mock("@/api/auth", () => ({
  getMe: vi.fn().mockResolvedValue({
    role: "member",
    sub: "u1",
    email: "member@dojo.test",
    is_active: true,
    theme: "system",
  }),
}))

// ── Mock CalendarView so tests don't need date-fns / full calendar setup ──────

vi.mock("@/components/CalendarView", () => ({
  default: ({ isAdmin }: { isAdmin: boolean }) => (
    <div data-testid="calendar-view" aria-label="Calendar view">
      Calendar ({isAdmin ? "admin" : "member"})
    </div>
  ),
}))

// ── Mock SessionCardList ──────────────────────────────────────────────────────

vi.mock("@/components/SessionCardList", () => ({
  default: () => (
    <div data-testid="session-card-list" aria-label="Session card list">
      Session list
    </div>
  ),
}))

// ── Mock SessionsTable (for AC8 desktop integration test) ─────────────────────

vi.mock("@/components/SessionsTable", () => ({
  default: () => (
    <div data-testid="sessions-table" aria-label="Sessions table">
      Sessions table
    </div>
  ),
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderSessionsPage() {
  return render(
    <MemoryRouter initialEntries={["/sessions"]}>
      <SessionsPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ── AC9 — Default view is List (SessionCardList visible on initial render) ────

describe("AC9 — default view is List", () => {
  it("renders SessionCardList by default without clicking anything", async () => {
    renderSessionsPage()

    await waitFor(() => {
      expect(screen.getByTestId("session-card-list")).toBeInTheDocument()
    })

    expect(screen.queryByTestId("calendar-view")).not.toBeInTheDocument()
  })
})

// ── AC1 — Toggle buttons present in the toolbar ───────────────────────────────

describe("AC1 — toggle buttons present", () => {
  it("renders a List toggle button", async () => {
    renderSessionsPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^list$/i })).toBeInTheDocument()
    })
  })

  it("renders a Calendar toggle button", async () => {
    renderSessionsPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^calendar$/i })).toBeInTheDocument()
    })
  })

  it("List button has aria-pressed=true by default", async () => {
    renderSessionsPage()

    await waitFor(() => {
      const listBtn = screen.getByRole("button", { name: /^list$/i })
      expect(listBtn).toHaveAttribute("aria-pressed", "true")
    })
  })

  it("Calendar button has aria-pressed=false by default", async () => {
    renderSessionsPage()

    await waitFor(() => {
      const calBtn = screen.getByRole("button", { name: /^calendar$/i })
      expect(calBtn).toHaveAttribute("aria-pressed", "false")
    })
  })
})

// ── AC2 — Clicking Calendar renders CalendarView ──────────────────────────────

describe("AC2 — clicking Calendar shows CalendarView", () => {
  it("renders CalendarView after clicking Calendar toggle", async () => {
    const user = userEvent.setup()
    renderSessionsPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^calendar$/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /^calendar$/i }))

    await waitFor(() => {
      expect(screen.getByTestId("calendar-view")).toBeInTheDocument()
    })

    expect(screen.queryByTestId("session-card-list")).not.toBeInTheDocument()
  })

  it("Calendar button becomes aria-pressed=true after clicking it", async () => {
    const user = userEvent.setup()
    renderSessionsPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^calendar$/i })).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /^calendar$/i }))

    await waitFor(() => {
      const calBtn = screen.getByRole("button", { name: /^calendar$/i })
      expect(calBtn).toHaveAttribute("aria-pressed", "true")
    })
  })
})

// ── AC3 — Clicking List restores SessionCardList ──────────────────────────────

describe("AC3 — clicking List restores SessionCardList", () => {
  it("switches back to SessionCardList after toggling Calendar then List", async () => {
    const user = userEvent.setup()
    renderSessionsPage()

    // Switch to calendar
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^calendar$/i })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("button", { name: /^calendar$/i }))

    await waitFor(() => {
      expect(screen.getByTestId("calendar-view")).toBeInTheDocument()
    })

    // Switch back to list
    await user.click(screen.getByRole("button", { name: /^list$/i }))

    await waitFor(() => {
      expect(screen.getByTestId("session-card-list")).toBeInTheDocument()
    })

    expect(screen.queryByTestId("calendar-view")).not.toBeInTheDocument()
  })

  it("List button becomes aria-pressed=true after returning to list view", async () => {
    const user = userEvent.setup()
    renderSessionsPage()

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /^calendar$/i })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("button", { name: /^calendar$/i }))

    await waitFor(() => {
      expect(screen.getByTestId("calendar-view")).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /^list$/i }))

    await waitFor(() => {
      const listBtn = screen.getByRole("button", { name: /^list$/i })
      expect(listBtn).toHaveAttribute("aria-pressed", "true")
    })
  })
})

// ── AC8 — Toggle container has responsive hidden class (not rendered on mobile) ─

describe("AC8 — toggle is hidden on mobile via responsive CSS class", () => {
  it("toggle container has a class that hides it below md breakpoint", async () => {
    renderSessionsPage()

    await waitFor(() => {
      // The container wrapping List/Calendar toggle buttons should have 'hidden md:flex'
      // (or similar Tailwind responsive hiding) to stay invisible on mobile.
      const listBtn = screen.getByRole("button", { name: /^list$/i })
      const toggleContainer = listBtn.closest("[class*='hidden']")
      expect(toggleContainer).not.toBeNull()
    })
  })

  it("toggle container class includes 'hidden' to suppress mobile rendering", async () => {
    renderSessionsPage()

    await waitFor(() => {
      const listBtn = screen.getByRole("button", { name: /^list$/i })
      const toggleContainer = listBtn.parentElement
      expect(toggleContainer?.className).toMatch(/hidden/)
    })
  })
})

// ── AC8 — SessionsTable present in DOM in desktop list view ──────────────────
//
// SessionsTable is rendered for the desktop table layout alongside (or instead of)
// SessionCardList. It may be visually hidden on mobile via CSS but must be present
// in the DOM so assistive tech and tests can reach it.

describe("AC8 — SessionsTable present in DOM for desktop list view", () => {
  it("renders an element with data-testid='sessions-table' in list view", async () => {
    renderSessionsPage()

    await waitFor(() => {
      expect(screen.getByTestId("sessions-table")).toBeInTheDocument()
    })
  })

  it("sessions-table is present in DOM even alongside session-card-list", async () => {
    renderSessionsPage()

    await waitFor(() => {
      // Both may exist simultaneously (one hidden on mobile via CSS, one on desktop)
      // The key requirement is that sessions-table is in the DOM.
      const table = screen.getByTestId("sessions-table")
      expect(table).toBeInTheDocument()
    })
  })
})
