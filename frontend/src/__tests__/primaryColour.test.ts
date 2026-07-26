/**
 * Tests for the brand primary-colour helpers (@/lib/primaryColour).
 *
 * Regression: a dark custom primary (e.g. #1a1a2e) previously left
 * --primary-foreground at the theme default, giving dark-on-dark button text
 * in dark mode. applyPrimaryColour must always pair the colour with a legible
 * foreground.
 */

import { describe, it, expect, beforeEach } from "vitest"
import {
  applyPrimaryColour,
  contrastRatio,
  readableForeground,
  isTooLightForAccent,
} from "@/lib/primaryColour"

describe("contrastRatio", () => {
  it("returns ~21 for black vs white", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 0)
  })

  it("is symmetric in its arguments", () => {
    expect(contrastRatio("#1a1a2e", "#ffffff")).toBeCloseTo(
      contrastRatio("#ffffff", "#1a1a2e"),
      5
    )
  })
})

describe("readableForeground", () => {
  it("picks near-white for a dark brand colour", () => {
    expect(readableForeground("#1a1a2e")).toBe("#ffffff")
  })

  it("picks near-black for a light brand colour", () => {
    expect(readableForeground("#ffd700")).toBe("#0a0a0a")
  })

  it("always yields an AA-legible pairing (>= 4.5:1)", () => {
    for (const hex of ["#1a1a2e", "#4f46e5", "#ffd700", "#7f7f7f", "#f0f0f0"]) {
      expect(contrastRatio(hex, readableForeground(hex))).toBeGreaterThanOrEqual(4.5)
    }
  })
})

describe("isTooLightForAccent", () => {
  it("flags a near-white colour that would vanish as a text accent", () => {
    expect(isTooLightForAccent("#f0f0f0")).toBe(true)
  })

  it("does not flag a dark brand colour", () => {
    expect(isTooLightForAccent("#1a1a2e")).toBe(false)
  })
})

describe("applyPrimaryColour", () => {
  beforeEach(() => {
    document.documentElement.style.removeProperty("--primary")
    document.documentElement.style.removeProperty("--primary-foreground")
  })

  it("sets both --primary and a contrasting --primary-foreground", () => {
    applyPrimaryColour("#1a1a2e")
    const style = document.documentElement.style
    expect(style.getPropertyValue("--primary")).toBe("#1a1a2e")
    expect(style.getPropertyValue("--primary-foreground")).toBe("#ffffff")
  })
})
