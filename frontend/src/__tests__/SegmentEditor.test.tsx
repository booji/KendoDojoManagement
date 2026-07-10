/**
 * Tests for SegmentEditor component (issue #175).
 *
 * SegmentEditor is a controlled segment-list editor used inside the create
 * dialog (SessionsPage) and the edit form (SessionDetailPage). It does NOT
 * exist yet — these tests are the red phase.
 *
 * Component interface designed here:
 *
 *   interface SegmentEditorProps {
 *     segments: SegmentInput[]          // controlled value
 *     sessionTypes: SessionType[]        // available types to pick from
 *     onChange: (segments: SegmentInput[]) => void
 *   }
 *
 *   SegmentInput = {
 *     start_time: string        // "HH:MM"
 *     duration_minutes: number
 *     type_ids: string[]
 *   }
 *
 *   SessionType = { id: string; name: string; colour: string | null }
 *
 * Each segment row must expose:
 *   - a text/time input for start_time (labelled "Start time" or similar)
 *   - a number input for duration_minutes (labelled "Duration" or similar)
 *   - a multi-select mechanism for type_ids — as of issue #199, this is the
 *     SessionTypeMultiSelect popover control (one trigger per segment row,
 *     each with a stable accessible name matching /session types/i). Opening
 *     the Nth segment's trigger reveals its options as role="checkbox" rows.
 *   - a remove button (disabled / absent when only one segment remains)
 * The editor overall must expose:
 *   - an "Add segment" button that appends a blank segment row
 *
 * Acceptance criteria covered:
 *   AC-unit-1 — renders one row by default
 *   AC-unit-2 — "Add segment" appends a row; onChange called with longer array
 *   AC-unit-3 — remove control drops a row; onChange called with shorter array
 *   AC-unit-4 — cannot remove the last remaining row
 *   AC-unit-5 — a segment row supports selecting multiple types (type_ids > 1)
 *     via the SessionTypeMultiSelect popover (issue #199)
 *   AC-unit-6 — editing start_time flows through onChange
 *   AC-unit-7 — editing duration_minutes flows through onChange
 *
 * Issue #190 removed the per-segment coach_notes field entirely; the editor
 * must no longer render it.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import SegmentEditor from "@/components/SegmentEditor"
import type { SegmentInput, SessionType } from "@/api/sessions"

// ── Fixtures ──────────────────────────────────────────────────────────────────

const SESSION_TYPES: SessionType[] = [
  { id: "type-1", name: "Keiko", colour: "#3366ff" },
  { id: "type-2", name: "Iaido", colour: "#ff6633" },
  { id: "type-3", name: "Shinsa Prep", colour: "#33cc66" },
]

const BLANK_SEGMENT: SegmentInput = {
  start_time: "19:00",
  duration_minutes: 90,
  type_ids: ["type-1"],
}

const TWO_SEGMENTS: SegmentInput[] = [
  { start_time: "09:00", duration_minutes: 60, type_ids: ["type-1"] },
  { start_time: "10:00", duration_minutes: 45, type_ids: ["type-2"] },
]

// ── Helper ────────────────────────────────────────────────────────────────────

function renderEditor(
  segments: SegmentInput[],
  onChange = vi.fn(),
  types = SESSION_TYPES,
) {
  return {
    onChange,
    ...render(
      <SegmentEditor
        segments={segments}
        sessionTypes={types}
        onChange={onChange}
      />,
    ),
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ── AC-unit-1 — Renders one row by default ────────────────────────────────────

describe("AC-unit-1 — renders one row by default", () => {
  it("renders exactly one segment row when given a one-element segments array", () => {
    renderEditor([BLANK_SEGMENT])

    // Expect exactly one start-time input (one per segment row)
    const startInputs = screen.getAllByLabelText(/start time/i)
    expect(startInputs).toHaveLength(1)
  })

  it("renders the Add segment button", () => {
    renderEditor([BLANK_SEGMENT])

    expect(screen.getByRole("button", { name: /add segment/i })).toBeInTheDocument()
  })
})

// ── AC-unit-2 — "Add segment" appends a row ───────────────────────────────────

describe("AC-unit-2 — Add segment appends a row", () => {
  it("calls onChange with an array one element longer when Add segment is clicked", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor([BLANK_SEGMENT], onChange)

    await user.click(screen.getByRole("button", { name: /add segment/i }))

    expect(onChange).toHaveBeenCalledOnce()
    const nextSegments: SegmentInput[] = onChange.mock.calls[0][0]
    expect(nextSegments).toHaveLength(2)
  })

  it("new segment appended by Add segment has valid defaults (positive duration, at least no type_ids constraint violation)", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor([BLANK_SEGMENT], onChange)

    await user.click(screen.getByRole("button", { name: /add segment/i }))

    const nextSegments: SegmentInput[] = onChange.mock.calls[0][0]
    const newSeg = nextSegments[1]
    expect(newSeg.duration_minutes).toBeGreaterThan(0)
    expect(typeof newSeg.start_time).toBe("string")
  })
})

// ── AC-unit-3 — Remove control drops a row ────────────────────────────────────

describe("AC-unit-3 — remove control drops a row", () => {
  it("calls onChange with one fewer segment when Remove is clicked on a two-segment list", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor(TWO_SEGMENTS, onChange)

    // There should be two remove buttons (one per row) when >1 segment exists
    const removeButtons = screen.getAllByRole("button", { name: /remove segment/i })
    expect(removeButtons).toHaveLength(2)

    await user.click(removeButtons[0])

    expect(onChange).toHaveBeenCalledOnce()
    const nextSegments: SegmentInput[] = onChange.mock.calls[0][0]
    expect(nextSegments).toHaveLength(1)
  })

  it("the remaining segment after removal corresponds to the non-removed row", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor(TWO_SEGMENTS, onChange)

    const removeButtons = screen.getAllByRole("button", { name: /remove segment/i })
    // Remove the first row → second row (10:00, type-2) should remain
    await user.click(removeButtons[0])

    const nextSegments: SegmentInput[] = onChange.mock.calls[0][0]
    expect(nextSegments[0].start_time).toBe("10:00")
    expect(nextSegments[0].type_ids).toEqual(["type-2"])
  })
})

// ── AC-unit-4 — Cannot remove the last remaining row ─────────────────────────

describe("AC-unit-4 — cannot remove the last remaining row", () => {
  it("does NOT render a remove button when only one segment is present", () => {
    renderEditor([BLANK_SEGMENT])

    expect(screen.queryByRole("button", { name: /remove segment/i })).not.toBeInTheDocument()
  })

  it("alternatively, the remove button is disabled when only one segment is present", () => {
    // Some implementations render a disabled button rather than hiding it.
    // This test handles that variant; if the button is absent, the test passes
    // trivially (queryByRole returns null, which is falsy — disabled check skipped).
    renderEditor([BLANK_SEGMENT])

    const btn = screen.queryByRole("button", { name: /remove segment/i })
    if (btn !== null) {
      // If a remove button exists, it must be disabled
      expect(btn).toBeDisabled()
    } else {
      // Button absent — correctly cannot remove
      expect(btn).toBeNull()
    }
  })
})

// ── AC-unit-5 — Segment row supports selecting multiple types ─────────────────
// (issue #199 — driven through the SessionTypeMultiSelect popover trigger,
// not a bare checkbox row)

describe("AC-unit-5 — multiple type selection within a segment row", () => {
  it("selecting a second type causes onChange to be called with type_ids of length 2", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    // Start with a segment that has only type-1 selected
    renderEditor(
      [{ start_time: "19:00", duration_minutes: 90, type_ids: ["type-1"] }],
      onChange,
    )

    // Open the segment's session-type multi-select popover
    const trigger = screen.getByRole("button", { name: /session types/i })
    await user.click(trigger)

    // Select type-2 in addition — the popover row for "Iaido"
    const iaidoOption = await screen.findByRole("checkbox", { name: /iaido/i })
    await user.click(iaidoOption)

    expect(onChange).toHaveBeenCalled()
    const nextSegments: SegmentInput[] = onChange.mock.calls[0][0]
    expect(nextSegments[0].type_ids).toContain("type-1")
    expect(nextSegments[0].type_ids).toContain("type-2")
    expect(nextSegments[0].type_ids).toHaveLength(2)
  })

  it("deselecting the only remaining type is prevented or leaves type_ids non-empty", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor(
      [{ start_time: "19:00", duration_minutes: 90, type_ids: ["type-1"] }],
      onChange,
    )

    const trigger = screen.getByRole("button", { name: /session types/i })
    await user.click(trigger)

    const keikoOption = await screen.findByRole("checkbox", { name: /keiko/i })
    expect(keikoOption).toHaveAttribute("aria-checked", "true")

    // The only remaining selected type — attempting to deselect it must never
    // produce an empty type_ids array, whether the row is disabled or the click
    // is silently a no-op.
    await user.click(keikoOption)

    for (const call of onChange.mock.calls) {
      const nextSegments: SegmentInput[] = call[0]
      expect(nextSegments[0].type_ids.length).toBeGreaterThanOrEqual(1)
    }
    // The type remains selected after the attempted deselect.
    expect(
      screen.getByRole("checkbox", { name: /keiko/i }),
    ).toHaveAttribute("aria-checked", "true")
  })
})

// ── AC-unit-6 — Editing start_time flows through onChange ────────────────────

describe("AC-unit-6 — editing start_time", () => {
  it("changing start_time calls onChange with the updated value", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor([BLANK_SEGMENT], onChange)

    const startInput = screen.getByLabelText(/start time/i)
    await user.clear(startInput)
    await user.type(startInput, "20:00")

    // onChange should have been called; the last call should have start_time "20:00"
    expect(onChange).toHaveBeenCalled()
    const lastCall: SegmentInput[] = onChange.mock.lastCall![0]
    expect(lastCall[0].start_time).toBe("20:00")
  })
})

// ── AC-unit-7 — Editing duration_minutes flows through onChange ───────────────

describe("AC-unit-7 — editing duration_minutes", () => {
  it("changing duration_minutes calls onChange with the updated numeric value", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor([BLANK_SEGMENT], onChange)

    const durationInput = screen.getByLabelText(/duration/i)
    await user.clear(durationInput)
    await user.type(durationInput, "60")

    expect(onChange).toHaveBeenCalled()
    const lastCall: SegmentInput[] = onChange.mock.lastCall![0]
    expect(lastCall[0].duration_minutes).toBe(60)
  })
})

// ── Issue #190 — per-segment coach_notes removed entirely ────────────────────

describe("issue #190 — no per-segment coach notes", () => {
  it("never renders a coach notes field for a segment", () => {
    renderEditor([BLANK_SEGMENT])

    expect(screen.queryByLabelText(/coach notes/i)).not.toBeInTheDocument()
  })
})

// ── Issue #182 — public title & note fields ──────────────────────────────────

describe("public title & note (issue #182)", () => {
  it("renders always-visible Title and Note inputs", () => {
    renderEditor([BLANK_SEGMENT])

    expect(screen.getByLabelText(/^title$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^note$/i)).toBeInTheDocument()
  })

  it("typing in Title flows through onChange", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor([BLANK_SEGMENT], onChange)

    await user.type(screen.getByLabelText(/^title$/i), "Footwork drills")

    const lastCall: SegmentInput[] = onChange.mock.lastCall![0]
    expect(lastCall[0].title).toBe("Footwork drills")
  })

  it("typing in Note flows through onChange", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor([BLANK_SEGMENT], onChange)

    await user.type(screen.getByLabelText(/^note$/i), "today focus nuki-do")

    const lastCall: SegmentInput[] = onChange.mock.lastCall![0]
    expect(lastCall[0].note).toBe("today focus nuki-do")
  })
})

// ── Multi-segment rendering ────────────────────────────────────────────────────

describe("multi-segment rendering", () => {
  it("renders two rows when given a two-element segments array", () => {
    renderEditor(TWO_SEGMENTS)

    const startInputs = screen.getAllByLabelText(/start time/i)
    expect(startInputs).toHaveLength(2)
  })

  it("each row shows its own start_time value", () => {
    renderEditor(TWO_SEGMENTS)

    const [firstInput, secondInput] = screen.getAllByLabelText(
      /start time/i,
    ) as HTMLInputElement[]
    expect(firstInput.value).toBe("09:00")
    expect(secondInput.value).toBe("10:00")
  })

  it("editing the second segment's start_time updates only that segment", async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderEditor(TWO_SEGMENTS, onChange)

    const startInputs = screen.getAllByLabelText(/start time/i)
    await user.clear(startInputs[1])
    await user.type(startInputs[1], "11:00")

    expect(onChange).toHaveBeenCalled()
    const lastCall: SegmentInput[] = onChange.mock.lastCall![0]
    // First segment unchanged
    expect(lastCall[0].start_time).toBe("09:00")
    // Second segment updated
    expect(lastCall[1].start_time).toBe("11:00")
  })
})

// ── Mobile / responsive rendering ────────────────────────────────────────────

describe("mobile layout — stacked cards", () => {
  it("renders segment rows as cards stacked vertically (no table structure)", () => {
    renderEditor(TWO_SEGMENTS)

    // The component must NOT use a <table> element for the segment list;
    // a stacked-card layout (divs/articles) is required for mobile usability.
    expect(document.querySelector("table")).toBeNull()
  })
})
