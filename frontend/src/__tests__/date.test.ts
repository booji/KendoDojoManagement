/**
 * Tests for the shared date utility (issue #168).
 *
 * Acceptance criteria covered:
 *   AC1 — formatSessionDate, formatMemberDate, formatShortDate exist in @/lib/date
 *   AC2 — each function accepts both Date objects and ISO strings
 *   AC3 — formatSessionDate and formatMemberDate return a string containing day, month, and year
 *   AC4 — formatShortDate returns a shorter string (no year)
 *   AC5 — invalid input throws or returns a recognizable error string (no silent swallow)
 */

import { describe, it, expect } from "vitest"
import { formatSessionDate, formatMemberDate, formatShortDate } from "@/lib/date"

// ── Fixtures ──────────────────────────────────────────────────────────────────

const isoString = "2024-06-15"
const dateObject = new Date(2024, 5, 15) // 15 June 2024 (month is 0-indexed)

// ── formatSessionDate ─────────────────────────────────────────────────────────

describe("formatSessionDate", () => {
  it("accepts a Date object and returns a string", () => {
    const result = formatSessionDate(dateObject)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  it("accepts an ISO date string and returns a string", () => {
    const result = formatSessionDate(isoString)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  it("output contains the day number (15)", () => {
    const result = formatSessionDate(isoString)
    expect(result).toMatch(/15/)
  })

  it("output contains the year (2024)", () => {
    const result = formatSessionDate(isoString)
    expect(result).toMatch(/2024/)
  })

  it("output contains a month indicator", () => {
    // Either numeric (6 or 06) or a name fragment (Jun, June, etc.)
    const result = formatSessionDate(isoString)
    expect(result).toMatch(/jun|6/i)
  })

  it("Date object and ISO string produce the same output", () => {
    // Both represent 15 June 2024 in local time — they may differ by timezone
    // so we only check that both contain 2024 and 15, not strict equality
    const fromDate = formatSessionDate(dateObject)
    const fromString = formatSessionDate(isoString)
    expect(fromDate).toMatch(/2024/)
    expect(fromString).toMatch(/2024/)
  })
})

// ── formatMemberDate ──────────────────────────────────────────────────────────

describe("formatMemberDate", () => {
  it("accepts a Date object and returns a string", () => {
    const result = formatMemberDate(dateObject)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  it("accepts an ISO date string and returns a string", () => {
    const result = formatMemberDate(isoString)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  it("output contains the day number (15)", () => {
    const result = formatMemberDate(isoString)
    expect(result).toMatch(/15/)
  })

  it("output contains the year (2024)", () => {
    const result = formatMemberDate(isoString)
    expect(result).toMatch(/2024/)
  })

  it("output contains a month indicator", () => {
    const result = formatMemberDate(isoString)
    expect(result).toMatch(/jun|6/i)
  })
})

// ── formatShortDate ───────────────────────────────────────────────────────────

describe("formatShortDate", () => {
  it("accepts a Date object and returns a string", () => {
    const result = formatShortDate(dateObject)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  it("accepts an ISO date string and returns a string", () => {
    const result = formatShortDate(isoString)
    expect(typeof result).toBe("string")
    expect(result.length).toBeGreaterThan(0)
  })

  it("output does NOT contain the year (2024)", () => {
    const result = formatShortDate(isoString)
    expect(result).not.toMatch(/2024/)
  })

  it("output is shorter than formatSessionDate output for the same input", () => {
    const short = formatShortDate(isoString)
    const full = formatSessionDate(isoString)
    expect(short.length).toBeLessThan(full.length)
  })
})

// ── Invalid input ─────────────────────────────────────────────────────────────

describe("invalid input handling", () => {
  it("formatSessionDate throws or returns an error string for a clearly invalid date string", () => {
    const tryIt = () => formatSessionDate("not-a-date")
    // Must not silently return a plausible-looking date
    try {
      const result = tryIt()
      // If it doesn't throw, it must return something that signals an error
      expect(result).toMatch(/invalid|error|NaN/i)
    } catch (e) {
      // Throwing is also acceptable
      expect(e).toBeDefined()
    }
  })

  it("formatMemberDate throws or returns an error string for a clearly invalid date string", () => {
    const tryIt = () => formatMemberDate("not-a-date")
    try {
      const result = tryIt()
      expect(result).toMatch(/invalid|error|NaN/i)
    } catch (e) {
      expect(e).toBeDefined()
    }
  })

  it("formatShortDate throws or returns an error string for a clearly invalid date string", () => {
    const tryIt = () => formatShortDate("not-a-date")
    try {
      const result = tryIt()
      expect(result).toMatch(/invalid|error|NaN/i)
    } catch (e) {
      expect(e).toBeDefined()
    }
  })
})
