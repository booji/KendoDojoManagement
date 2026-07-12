/**
 * Tests for the new PageHeader component (issue #214 — design-system pass).
 *
 * PageHeader does NOT exist yet at @/components/ui/page-header — these tests
 * are the red phase.
 *
 * Component interface designed here:
 *
 *   interface PageHeaderProps {
 *     title: string
 *     description?: string | null
 *     action?: React.ReactNode | null   // arbitrary slot, e.g. a Button
 *   }
 *
 *   export function PageHeader(props: PageHeaderProps): JSX.Element
 *
 * Contract:
 *   - `title` renders as a heading (role="heading"), accessible name === title.
 *   - `description`, when provided, renders as visible text; when omitted,
 *     nothing extra renders (no empty node the implementer forgot to guard).
 *   - `action`, when provided, renders inside the header (queried via a
 *     stable test id: data-testid="page-header-action"); when omitted, that
 *     slot does not render at all.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import { PageHeader } from "@/components/ui/page-header"

describe("PageHeader — title", () => {
  it("renders the title as a heading", () => {
    render(<PageHeader title="Members" />)

    const heading = screen.getByRole("heading", { name: "Members" })
    expect(heading).toBeInTheDocument()
  })
})

describe("PageHeader — optional description", () => {
  it("renders the description when provided", () => {
    render(
      <PageHeader
        title="Members"
        description="Manage dojo members and their grading history"
      />,
    )

    expect(
      screen.getByText("Manage dojo members and their grading history"),
    ).toBeInTheDocument()
  })

  it("does not render a description when omitted", () => {
    render(<PageHeader title="Members" />)

    // No stray paragraph/description text beyond the title itself.
    expect(screen.queryByText(/manage/i)).not.toBeInTheDocument()
  })
})

describe("PageHeader — optional action slot", () => {
  it("renders the action when provided", () => {
    render(
      <PageHeader
        title="Members"
        action={<button>Add member</button>}
      />,
    )

    expect(screen.getByTestId("page-header-action")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Add member" }),
    ).toBeInTheDocument()
  })

  it("does not render the action slot when omitted", () => {
    render(<PageHeader title="Members" />)

    expect(screen.queryByTestId("page-header-action")).not.toBeInTheDocument()
  })
})
