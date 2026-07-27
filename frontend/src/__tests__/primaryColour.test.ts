/**
 * Tests for the brand primary-colour helpers (@/lib/primaryColour).
 *
 * Issue #223: the stored brand hex is a *hue*, not a literal accent. Because
 * WCAG contrast is luminance-based, one fixed colour cannot be an accessible
 * accent against both a near-white and a near-black page. deriveThemePrimaries
 * turns the brand hue into a darker light-theme shade and a lighter dark-theme
 * shade, each guaranteeing AA contrast against its own background *and* against
 * its paired --primary-foreground.
 *
 * Regression (#222): a dark custom primary (e.g. #1a1a2e) must still pair with
 * a legible foreground on the solid button.
 */

import { describe, it, expect, beforeEach } from "vitest"
import {
  applyPrimaryColour,
  deriveThemePrimaries,
  contrastRatio,
  readableForeground,
  hexToOklch,
  oklchToHex,
  LIGHT_BG,
  DARK_BG,
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
})

describe("hexToOklch / oklchToHex round-trip", () => {
  it("round-trips in-gamut colours within tolerance", () => {
    for (const hex of ["#4f46e5", "#1a1a2e", "#ffd700", "#2e7d32", "#c2185b"]) {
      const { L, C, H } = hexToOklch(hex)
      const back = hexToOklch(oklchToHex(L, C, H))
      expect(back.L).toBeCloseTo(L, 2)
      expect(back.C).toBeCloseTo(C, 2)
      // hue is meaningless at near-zero chroma; only check when chromatic
      if (C > 0.02) expect(Math.cos((back.H - H) * (Math.PI / 180))).toBeCloseTo(1, 2)
    }
  })
})

describe("deriveThemePrimaries", () => {
  // The four acceptance-criteria AA conditions, for any brand hue:
  //  light.primary vs LIGHT_BG, light.primary vs light.primaryForeground,
  //  dark.primary  vs DARK_BG,  dark.primary  vs dark.primaryForeground.
  const brands = ["#4f46e5", "#1a1a2e", "#ffd700", "#f0f0f0", "#2e7d32"]

  for (const brand of brands) {
    it(`yields AA-legible shades in both themes for ${brand}`, () => {
      const { light, dark } = deriveThemePrimaries(brand)

      expect(contrastRatio(light.primary, LIGHT_BG)).toBeGreaterThanOrEqual(4.5)
      expect(
        contrastRatio(light.primary, light.primaryForeground)
      ).toBeGreaterThanOrEqual(4.5)

      expect(contrastRatio(dark.primary, DARK_BG)).toBeGreaterThanOrEqual(4.5)
      expect(
        contrastRatio(dark.primary, dark.primaryForeground)
      ).toBeGreaterThanOrEqual(4.5)
    })
  }

  it("derives distinct shades: dark-theme primary is lighter than light-theme primary", () => {
    // A dark brand hue must still surface a visible accent in dark mode, which
    // requires lightening it relative to the light-theme shade.
    const { light, dark } = deriveThemePrimaries("#1a1a2e")
    expect(hexToOklch(dark.primary).L).toBeGreaterThan(hexToOklch(light.primary).L)
  })

  it("preserves the brand hue in both derived shades", () => {
    const brand = "#c2185b"
    const { H } = hexToOklch(brand)
    const { light, dark } = deriveThemePrimaries(brand)
    for (const shade of [light.primary, dark.primary]) {
      const dh = hexToOklch(shade).H - H
      expect(Math.cos(dh * (Math.PI / 180))).toBeCloseTo(1, 1)
    }
  })
})

describe("applyPrimaryColour", () => {
  beforeEach(() => {
    document.getElementById("brand-primary")?.remove()
  })

  it("injects a #brand-primary stylesheet with both :root and .dark rules", () => {
    applyPrimaryColour("#1a1a2e")
    const el = document.getElementById("brand-primary")
    expect(el).not.toBeNull()
    const css = el?.textContent ?? ""
    expect(css).toContain(":root")
    expect(css).toContain(".dark")
    expect(css).toContain("--primary")
    expect(css).toContain("--primary-foreground")
  })

  it("reuses the same style element on repeated calls", () => {
    applyPrimaryColour("#1a1a2e")
    applyPrimaryColour("#ffd700")
    expect(document.querySelectorAll("#brand-primary")).toHaveLength(1)
  })
})
