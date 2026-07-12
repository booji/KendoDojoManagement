/**
 * Tests for the new EmptyState component (issue #214 — design-system pass).
 *
 * EmptyState does NOT exist yet at @/components/ui/empty-state — these tests
 * are the red phase.
 *
 * Component interface designed here:
 *
 *   interface EmptyStateProps {
 *     message: string
 *     icon?: React.ReactNode | null       // e.g. a lucide-react icon element
 *     actionLabel?: string | null         // text for the optional action button
 *     onAction?: (() => void) | null      // handler invoked when the action is activated
 *   }
 *
 *   export function EmptyState(props: EmptyStateProps): JSX.Element
 *
 * Contract:
 *   - `message` always renders as visible text.
 *   - `icon`, when provided, renders somewhere in the component (queried via
 *     a stable test id: data-testid="empty-state-icon" wrapping whatever node
 *     is passed).
 *   - `actionLabel` + `onAction`, when both provided, render a
 *     role="button" with accessible name === actionLabel; clicking it invokes
 *     onAction exactly once.
 *   - When actionLabel/onAction/icon are omitted, the component renders only
 *     the message and does not throw.
 */

import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { EmptyState } from "@/components/ui/empty-state"

describe("EmptyState — message", () => {
  it("renders the message text", () => {
    render(<EmptyState message="No sessions found" />)

    expect(screen.getByText("No sessions found")).toBeInTheDocument()
  })
})

describe("EmptyState — optional icon", () => {
  it("renders the icon when provided", () => {
    render(
      <EmptyState
        message="No members yet"
        icon={<svg data-testid="my-icon" />}
      />,
    )

    expect(
      screen.getByTestId("empty-state-icon"),
    ).toBeInTheDocument()
    expect(screen.getByTestId("my-icon")).toBeInTheDocument()
  })

  it("does not render an icon wrapper when icon is omitted", () => {
    render(<EmptyState message="No members yet" />)

    expect(screen.queryByTestId("empty-state-icon")).not.toBeInTheDocument()
  })
})

describe("EmptyState — optional action", () => {
  it("renders the action button and invokes the handler when activated", async () => {
    const user = userEvent.setup()
    const onAction = vi.fn()

    render(
      <EmptyState
        message="No sessions found"
        actionLabel="Create session"
        onAction={onAction}
      />,
    )

    const button = screen.getByRole("button", { name: "Create session" })
    await user.click(button)

    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it("renders no action button when actionLabel/onAction are omitted", () => {
    render(<EmptyState message="No sessions found" />)

    expect(screen.queryByRole("button")).not.toBeInTheDocument()
  })
})

describe("EmptyState — minimal usage does not crash", () => {
  it("renders just the message with no icon or action", () => {
    expect(() =>
      render(<EmptyState message="Nothing here" />),
    ).not.toThrow()

    expect(screen.getByText("Nothing here")).toBeInTheDocument()
  })
})
