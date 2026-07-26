/**
 * Brand primary-colour helpers.
 *
 * The admin-configurable `--primary` token drives two very different uses:
 *  - the solid primary button, where it is the *background* and
 *    `--primary-foreground` is the text; and
 *  - accents such as `text-primary` links, where the primary is itself the
 *    *foreground* painted on the page background.
 *
 * `applyPrimaryColour` fixes the first case: it pairs the chosen colour with a
 * foreground (near-white or near-black) derived from the colour's luminance, so
 * the button label stays legible in both light and dark themes. The second case
 * (accent legibility on the page background) is guarded separately by
 * `contrastRatio` / the admin warning, since no foreground token can rescue a
 * primary that has no contrast with the page it sits on.
 *
 * WCAG 2.1 relative-luminance + contrast maths, mirrored from the backend's
 * app/settings/wcag.py so the two stay in agreement.
 */

const NEAR_WHITE = "#ffffff"
const NEAR_BLACK = "#0a0a0a"

const hexToRgb = (hex: string): [number, number, number] | null => {
  const match = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim())
  if (!match) return null
  return [parseInt(match[1], 16), parseInt(match[2], 16), parseInt(match[3], 16)]
}

/** WCAG 2.1 relative luminance of an r/g/b triple in 0–255. */
const relativeLuminance = (r: number, g: number, b: number): number => {
  const toLinear = (c: number): number => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)
}

/** WCAG 2.1 contrast ratio between two hex colours (1–21). */
export const contrastRatio = (hexA: string, hexB: string): number => {
  const a = hexToRgb(hexA)
  const b = hexToRgb(hexB)
  if (!a || !b) return 1
  const la = relativeLuminance(...a)
  const lb = relativeLuminance(...b)
  const [lighter, darker] = la >= lb ? [la, lb] : [lb, la]
  return (lighter + 0.05) / (darker + 0.05)
}

/** Near-white or near-black, whichever contrasts more with the given colour. */
export const readableForeground = (hex: string): string =>
  contrastRatio(hex, NEAR_WHITE) >= contrastRatio(hex, NEAR_BLACK)
    ? NEAR_WHITE
    : NEAR_BLACK

/**
 * True when the colour is too light to read as an accent (e.g. a `text-primary`
 * link) on the light page background — the concern the admin warning surfaces.
 */
export const isTooLightForAccent = (hex: string): boolean =>
  hexToRgb(hex) !== null && contrastRatio(hex, NEAR_WHITE) < 4.5

/**
 * Set `--primary` and a matching, legible `--primary-foreground` on the root,
 * so the solid primary button stays readable regardless of the active theme.
 */
export const applyPrimaryColour = (hex: string): void => {
  const root = document.documentElement
  root.style.setProperty("--primary", hex)
  root.style.setProperty("--primary-foreground", readableForeground(hex))
}
