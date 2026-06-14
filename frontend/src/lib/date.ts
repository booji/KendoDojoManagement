import { format, isValid, parseISO } from "date-fns"

// ── Helpers ────────────────────────────────────────────────────────────────────

const toDate = (value: Date | string): Date => {
  if (value instanceof Date) return value
  // parseISO treats date-only strings (YYYY-MM-DD) as local midnight,
  // avoiding the UTC-midnight timezone shift that `new Date(str)` causes.
  return parseISO(value)
}

const guard = (d: Date): void => {
  if (!isValid(d)) throw new RangeError(`Invalid date: ${d}`)
}

// ── Public API ─────────────────────────────────────────────────────────────────

/**
 * Session date label — includes weekday, day, abbreviated month, and year.
 * Example: "Sat, 7 Jun 2026"
 */
export const formatSessionDate = (date: Date | string): string => {
  const d = toDate(date)
  guard(d)
  return format(d, "EEE, d MMM yyyy")
}

/**
 * Member date label — day, abbreviated month, and year (no weekday).
 * Example: "7 Jun 2026"
 */
export const formatMemberDate = (date: Date | string): string => {
  const d = toDate(date)
  guard(d)
  return format(d, "d MMM yyyy")
}

/**
 * Short/compact date label — day and abbreviated month only (no year).
 * Example: "7 Jun"
 */
export const formatShortDate = (date: Date | string): string => {
  const d = toDate(date)
  guard(d)
  return format(d, "d MMM")
}
