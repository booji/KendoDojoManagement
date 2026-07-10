/**
 * Tests for SessionTypeMultiSelect component (issue #199).
 *
 * SessionTypeMultiSelect replaces the per-segment session-type checkbox row
 * in SegmentEditor with a single compact multi-select control built on the
 * existing Popover + Badge primitives (NO cmdk / Command dependency).
 * It does NOT exist yet — these tests are the red phase.
 *
 * Component interface designed here:
 *
 *   interface SessionTypeMultiSelectProps {
 *     options: SessionType[]
 *     selectedIds: string[]
 *     onChange: (ids: string[]) => void
 *     requireOne?: boolean   // when true, the last remaining selected id
 *                            // cannot be removed
 *   }
 *
 * Contract assumed by these tests (implementation detail the component must
 * satisfy so it is reliably queryable):
 *   - The trigger is a <button> with a STABLE accessible name matching
 *     /session types/i (e.g. aria-label="Session types"), regardless of
 *     selection state — this lets tests find it whether the visible content
 *     is the placeholder or a row of badges.
 *   - Trigger shows the placeholder text "Select session types…" when
 *     selectedIds is empty.
 *   - Each selected type renders as a Badge (text = type name) inside the
 *     trigger, with a small colour-dot swatch (data-testid="colour-dot")
 *     preceding it. A null colour falls back to a neutral dot.
 *   - Popover rows are role="checkbox" with accessible name = type name,
 *     aria-checked reflecting selection.
 *   - A filter <input role="textbox"> appears at the top of the panel only
 *     when options.length > 10.
 *
 * Acceptance criteria covered: AC 9 (compact multi-select for session types)
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import SessionTypeMultiSelect from "@/components/SessionTypeMultiSelect"
import type { SessionType } from "@/api/sessions"

// ── Fixtures ──────────────────────────────────────────────────────────────────

const FEW_TYPES: SessionType[] = [
  { id: "type-1", name: "Keiko", colour: "#3366ff" },
  { id: "type-2", name: "Iaido", colour: "#ff6633" },
  { id: "type-3", name: "Shinsa Prep", colour: null }, // exercises neutral fallback
]

const MANY_TYPES: SessionType[] = [
  { id: "t-1", name: "Keiko", colour: "#3366ff" },
  { id: "t-2", name: "Iaido", colour: "#ff6633" },
  { id: "t-3", name: "Shinsa Prep", colour: "#33cc66" },
  { id: "t-4", name: "Kata Practice", colour: null },
  { id: "t-5", name: "Jodo", colour: "#9933ff" },
  { id: "t-6", name: "Zazen", colour: "#111111" },
  { id: "t-7", name: "Bokken Drills", colour: "#00aacc" },
  { id: "t-8", name: "Suburi", colour: "#cc0044" },
  { id: "t-9", name: "Grading Prep", colour: null },
  { id: "t-10", name: "Kids Class", colour: "#ffaa00" },
  { id: "t-11", name: "Officer Training", colour: "#556677" },
  { id: "t-12", name: "Seminar", colour: "#889900" },
]

// ── Helper ────────────────────────────────────────────────────────────────────

function renderControl({
  options = FEW_TYPES,
  selectedIds = [] as string[],
  onChange = vi.fn(),
  requireOne = undefined as boolean | undefined,
} = {}) {
  return {
    onChange,
    ...render(
      <SessionTypeMultiSelect
        options={options}
        selectedIds={selectedIds}
        onChange={onChange}
        requireOne={requireOne}
      />,
    ),
  }
}

function getTrigger() {
  return screen.getByRole("button", { name: /session types/i })
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ── Placeholder / empty state ────────────────────────────────────────────────

describe("AC 9 — placeholder when nothing selected", () => {
  it("shows placeholder text when selectedIds is empty", () => {
    renderControl({ selectedIds: [] })

    expect(screen.getByText(/select session types…/i)).toBeInTheDocument()
  })
})

// ── Selected badges ───────────────────────────────────────────────────────────

describe("AC 9 — selected types render as colour-dot badges", () => {
  it("renders a badge with the type name for each selected id", () => {
    renderControl({ selectedIds: ["type-1", "type-2"] })

    const trigger = getTrigger()
    expect(within(trigger).getByText("Keiko")).toBeInTheDocument()
    expect(within(trigger).getByText("Iaido")).toBeInTheDocument()
  })

  it("renders a colour dot per badge, falling back to neutral when colour is null", () => {
    renderControl({ selectedIds: ["type-3"] })

    const trigger = getTrigger()
    expect(within(trigger).getByText("Shinsa Prep")).toBeInTheDocument()
    // type-3 has colour: null — a dot must still render (neutral fallback),
    // not crash, and not be styled with an explicit hex background.
    const dot = within(trigger).getByTestId("colour-dot")
    expect(dot).toBeInTheDocument()
    expect(dot.style.backgroundColor).not.toBe("rgb(51, 204, 102)") // not falsely coloured
  })
})

// ── Opening the popover reveals all options ──────────────────────────────────

describe("AC 9 — opening the popover reveals all option rows", () => {
  it("clicking the trigger opens the popover and reveals every option as a row", async () => {
    const user = userEvent.setup()
    renderControl({ options: FEW_TYPES, selectedIds: [] })

    await user.click(getTrigger())

    const rows = await screen.findAllByRole("checkbox")
    expect(rows).toHaveLength(FEW_TYPES.length)
    expect(screen.getByRole("checkbox", { name: /keiko/i })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: /iaido/i })).toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: /shinsa prep/i })).toBeInTheDocument()
  })
})

// ── Selecting / deselecting ───────────────────────────────────────────────────

describe("AC 9 — clicking an unselected row adds it", () => {
  it("calls onChange with the id added when an unselected row is clicked", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderControl({ selectedIds: ["type-1"], onChange })

    await user.click(getTrigger())
    const iaidoRow = await screen.findByRole("checkbox", { name: /iaido/i })
    await user.click(iaidoRow)

    expect(onChange).toHaveBeenCalled()
    const ids: string[] = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(ids).toContain("type-1")
    expect(ids).toContain("type-2")
  })
})

describe("AC 9 — clicking a selected row (with >1 selected) removes it", () => {
  it("calls onChange with the id removed", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderControl({ selectedIds: ["type-1", "type-2"], onChange })

    await user.click(getTrigger())
    const iaidoRow = await screen.findByRole("checkbox", { name: /iaido/i })
    expect(iaidoRow).toHaveAttribute("aria-checked", "true")
    await user.click(iaidoRow)

    expect(onChange).toHaveBeenCalled()
    const ids: string[] = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(ids).toContain("type-1")
    expect(ids).not.toContain("type-2")
  })
})

// ── Multi-select builds up length ────────────────────────────────────────────

describe("AC 9 — multi-select: selecting a second option yields length 2", () => {
  it("selecting a second option yields type_ids length 2", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderControl({ selectedIds: ["type-1"], onChange })

    await user.click(getTrigger())
    const shinsaRow = await screen.findByRole("checkbox", { name: /shinsa prep/i })
    await user.click(shinsaRow)

    expect(onChange).toHaveBeenCalled()
    const ids: string[] = onChange.mock.calls[onChange.mock.calls.length - 1][0]
    expect(ids).toHaveLength(2)
  })
})

// ── requireOne soft-lock ──────────────────────────────────────────────────────

describe("AC 9 — requireOne soft-lock on the last remaining selection", () => {
  it("does not allow the last remaining selected row to be deselected", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderControl({ selectedIds: ["type-1"], onChange, requireOne: true })

    await user.click(getTrigger())
    const keikoRow = await screen.findByRole("checkbox", { name: /keiko/i })
    expect(keikoRow).toHaveAttribute("aria-checked", "true")

    // Attempt to deselect the last remaining type — the soft-lock must hold
    // whether it is enforced by disabling the row or by making the click a no-op.
    await user.click(keikoRow)

    // The lock is violated if ANY emitted selection is empty.
    for (const call of onChange.mock.calls) {
      const ids: string[] = call[0]
      expect(ids.length).toBeGreaterThanOrEqual(1)
    }
    // The row must remain selected after the attempted deselect.
    expect(
      screen.getByRole("checkbox", { name: /keiko/i }),
    ).toHaveAttribute("aria-checked", "true")
  })
})

// ── Filter input visibility threshold ────────────────────────────────────────

describe("AC 9 — filter input only appears above the 10-option threshold", () => {
  it("does NOT render a filter input when options.length <= 10", async () => {
    const user = userEvent.setup()
    renderControl({ options: FEW_TYPES, selectedIds: [] })

    await user.click(getTrigger())
    await screen.findByRole("checkbox", { name: /keiko/i })

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
  })

  it("renders a filter input when options.length > 10, and typing narrows the visible rows", async () => {
    const user = userEvent.setup()
    renderControl({ options: MANY_TYPES, selectedIds: [] })

    await user.click(getTrigger())
    const filterInput = await screen.findByRole("textbox")
    expect(filterInput).toBeInTheDocument()

    // Sanity: before filtering, all 12 rows are visible.
    expect(screen.getAllByRole("checkbox")).toHaveLength(MANY_TYPES.length)

    await user.type(filterInput, "jodo")

    const visibleRows = screen.getAllByRole("checkbox")
    expect(visibleRows).toHaveLength(1)
    expect(visibleRows[0]).toHaveAccessibleName(/jodo/i)
  })
})
