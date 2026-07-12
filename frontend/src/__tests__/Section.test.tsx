/**
 * Tests for the new Section component (issue #214 — design-system pass).
 *
 * Section does NOT exist yet at @/components/ui/section — these tests are
 * the red phase.
 *
 * Component interface designed here:
 *
 *   interface SectionProps {
 *     heading: string
 *     children: React.ReactNode
 *   }
 *
 *   export function Section(props: SectionProps): JSX.Element
 *
 * Contract:
 *   - `heading` renders as a heading (role="heading"), accessible name ===
 *     heading.
 *   - `children` render inside the section, in the DOM, alongside the
 *     heading.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import { Section } from "@/components/ui/section"

describe("Section — heading", () => {
  it("renders the heading text as a heading", () => {
    render(
      <Section heading="Upcoming Sessions">
        <p>content</p>
      </Section>,
    )

    expect(
      screen.getByRole("heading", { name: "Upcoming Sessions" }),
    ).toBeInTheDocument()
  })
})

describe("Section — children", () => {
  it("renders its children", () => {
    render(
      <Section heading="Upcoming Sessions">
        <p>No sessions scheduled this week</p>
      </Section>,
    )

    expect(
      screen.getByText("No sessions scheduled this week"),
    ).toBeInTheDocument()
  })

  it("renders multiple children", () => {
    render(
      <Section heading="Roster">
        <span>Member A</span>
        <span>Member B</span>
      </Section>,
    )

    expect(screen.getByText("Member A")).toBeInTheDocument()
    expect(screen.getByText("Member B")).toBeInTheDocument()
  })
})
