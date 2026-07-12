/**
 * Tests for extended Badge variants (issue #214 — design-system pass).
 *
 * Badge already exists at @/components/ui/badge, built on @base-ui/react's
 * useRender with `state: { slot: "badge", variant }`. Empirically confirmed
 * (see base-ui's getStateAttributesProps): useRender's default state-attribute
 * mapping turns any truthy, non-boolean state value into a
 * `data-{key}="{value}"` DOM attribute with NO custom mapping required. So
 * `state: { variant: "secondary" }` already renders as `data-variant="secondary"`
 * on the root element today — this is the stable, queryable contract these
 * tests rely on for the NEW variants too.
 *
 * This test file does NOT touch the existing default/secondary/destructive/
 * outline/ghost/link variants' behaviour, except to assert `default` is
 * unchanged. It specifies the contract for three NEW semantic variants and a
 * category variant that the implementer must add to `badgeVariants` (the cva
 * config) in badge.tsx.
 *
 * Contract designed here:
 *
 *   type BadgeVariant =
 *     | "default" | "secondary" | "destructive" | "outline" | "ghost" | "link" // existing
 *     | "success" | "warning" | "info"                                        // NEW semantic
 *     | "category"                                                            // NEW category palette
 *
 *   interface BadgeProps {
 *     variant?: BadgeVariant
 *     category?: number | string  // only meaningful when variant="category";
 *                                 // selects one of a fixed palette of N slots
 *                                 // (implementer picks N, e.g. 8), surfaced as
 *                                 // data-category="{index}" on the root element
 *                                 // so a fixed number of distinguishable colours
 *                                 // can be asserted without reading CSS.
 *     // ...existing className/render/children props unchanged
 *   }
 *
 * Each variant/category combination must render with a DISTINCT, STABLE
 * `data-variant` (and `data-category` where relevant) attribute — that is the
 * only observable contract these tests assert; no class-string or colour-value
 * assertions.
 *
 * These tests are RED: `success`, `warning`, `info`, and `category` are not
 * yet valid variants in badgeVariants, so class-variance-authority falls back
 * to `undefined`/no variant class and — critically — the component does not
 * emit a data-variant value distinguishing them from each other today.
 */

import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import { Badge } from "@/components/ui/badge"

describe("Badge — existing default variant is unchanged", () => {
  it("renders with data-variant='default' when no variant prop is given", () => {
    render(<Badge>Plain</Badge>)

    const badge = screen.getByText("Plain")
    expect(badge).toHaveAttribute("data-variant", "default")
  })

  it("renders with data-variant='default' when variant='default' is explicit", () => {
    render(<Badge variant="default">Explicit Default</Badge>)

    const badge = screen.getByText("Explicit Default")
    expect(badge).toHaveAttribute("data-variant", "default")
  })
})

describe("Badge — new semantic variants", () => {
  it("renders variant='success' with data-variant='success'", () => {
    render(<Badge variant="success">Approved</Badge>)

    expect(screen.getByText("Approved")).toHaveAttribute(
      "data-variant",
      "success",
    )
  })

  it("renders variant='warning' with data-variant='warning'", () => {
    render(<Badge variant="warning">Pending</Badge>)

    expect(screen.getByText("Pending")).toHaveAttribute(
      "data-variant",
      "warning",
    )
  })

  it("renders variant='info' with data-variant='info'", () => {
    render(<Badge variant="info">Note</Badge>)

    expect(screen.getByText("Note")).toHaveAttribute("data-variant", "info")
  })

  it("success, warning, and info are distinguishable from each other and from default", () => {
    render(
      <>
        <Badge variant="default">D</Badge>
        <Badge variant="success">S</Badge>
        <Badge variant="warning">W</Badge>
        <Badge variant="info">I</Badge>
      </>,
    )

    const variants = ["D", "S", "W", "I"].map((text) =>
      screen.getByText(text).getAttribute("data-variant"),
    )
    expect(new Set(variants).size).toBe(4)
  })
})

describe("Badge — new category variant", () => {
  it("renders variant='category' with data-variant='category'", () => {
    render(
      <Badge variant="category" category={0}>
        Grading
      </Badge>,
    )

    expect(screen.getByText("Grading")).toHaveAttribute(
      "data-variant",
      "category",
    )
  })

  it("exposes the category index as data-category so distinct categories are queryable", () => {
    render(
      <>
        <Badge variant="category" category={0}>
          Cat A
        </Badge>
        <Badge variant="category" category={1}>
          Cat B
        </Badge>
      </>,
    )

    expect(screen.getByText("Cat A")).toHaveAttribute("data-category", "0")
    expect(screen.getByText("Cat B")).toHaveAttribute("data-category", "1")
  })

  it("different category indices are distinguishable from each other", () => {
    render(
      <>
        <Badge variant="category" category={2}>
          Cat C
        </Badge>
        <Badge variant="category" category={5}>
          Cat F
        </Badge>
      </>,
    )

    const a = screen.getByText("Cat C").getAttribute("data-category")
    const b = screen.getByText("Cat F").getAttribute("data-category")
    expect(a).not.toBe(b)
  })
})
