/**
 * Brand primary-colour helpers.
 *
 * The admin picks a single brand hex, but `--primary` drives two uses that pull
 * in opposite directions on a page:
 *  - the solid primary button, where `--primary` is the *background* and
 *    `--primary-foreground` is the text; and
 *  - accents such as `text-primary` links, where `--primary` is itself the
 *    *foreground* painted on the page background.
 *
 * WCAG contrast is luminance-based, so a single fixed colour cannot be an
 * accessible accent against both a near-white (light theme) and a near-black
 * (dark theme) page — those requirements are mutually exclusive. We therefore
 * treat the stored hex as a brand *hue* and derive two theme-specific shades
 * (`deriveThemePrimaries`): a darker one for the light theme and a lighter one
 * for the dark theme, each at a lightness that guarantees AA contrast against
 * its own background *and* against its paired `--primary-foreground`. This
 * mirrors how #214 derives the status/`--category-*` tokens per theme.
 *
 * WCAG 2.1 relative-luminance + contrast maths mirror the backend's
 * app/settings/wcag.py so the two stay in agreement; the OKLCH conversion is
 * Björn Ottosson's reference sRGB↔OKLab transform.
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

// --- OKLCH conversion (Björn Ottosson) ----------------------------------

const srgbToLinear = (c: number): number => {
  const s = c / 255
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
}

const linearToSrgb = (c: number): number => {
  const v = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055
  return Math.round(Math.min(1, Math.max(0, v)) * 255)
}

const toHex = (n: number): string => n.toString(16).padStart(2, "0")

export type Oklch = { L: number; C: number; H: number }

/** Convert a hex colour to OKLCH (L 0–1, C ≥ 0, H degrees 0–360). */
export const hexToOklch = (hex: string): Oklch => {
  const rgb = hexToRgb(hex) ?? [0, 0, 0]
  const [r, g, b] = rgb.map(srgbToLinear)

  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)

  const okL = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
  const okA = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
  const okB = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s

  const C = Math.sqrt(okA * okA + okB * okB)
  let H = (Math.atan2(okB, okA) * 180) / Math.PI
  if (H < 0) H += 360
  return { L: okL, C, H }
}

/** Convert OKLCH back to a hex colour, clamping out-of-gamut channels. */
export const oklchToHex = (L: number, C: number, H: number): string => {
  const hRad = (H * Math.PI) / 180
  const okA = C * Math.cos(hRad)
  const okB = C * Math.sin(hRad)

  const l_ = L + 0.3963377774 * okA + 0.2158037573 * okB
  const m_ = L - 0.1055613458 * okA - 0.0638541728 * okB
  const s_ = L - 0.0894841775 * okA - 1.291485548 * okB

  const l = l_ * l_ * l_
  const m = m_ * m_ * m_
  const s = s_ * s_ * s_

  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
  const b = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s

  return `#${toHex(linearToSrgb(r))}${toHex(linearToSrgb(g))}${toHex(linearToSrgb(b))}`
}

// --- Theme-aware shade derivation ---------------------------------------

/** The `--background` values from index.css, mirrored so shades stay in sync. */
export const LIGHT_BG = oklchToHex(1, 0.005, 264)
export const DARK_BG = oklchToHex(0.145, 0.012, 264)

const AA = 4.5

type Shade = { primary: string; primaryForeground: string }

/**
 * Lower (light theme) or raise (dark theme) the OKLCH lightness of the brand
 * hue from `startL` until the resulting colour reaches AA contrast against
 * `bg`. Chroma and hue are preserved; termination is guaranteed because pure
 * black/white bound the search and clear AA against any single background.
 */
const shadeForBackground = (
  brand: Oklch,
  bg: string,
  startL: number,
  direction: -1 | 1
): Shade => {
  const step = 0.01
  let L = startL
  let primary = oklchToHex(L, brand.C, brand.H)
  while (contrastRatio(primary, bg) < AA && L > 0 && L < 1) {
    L = Math.min(1, Math.max(0, L + direction * step))
    primary = oklchToHex(L, brand.C, brand.H)
  }
  return { primary, primaryForeground: readableForeground(primary) }
}

/**
 * Derive per-theme `--primary` / `--primary-foreground` from a brand hex.
 * Light theme darkens toward the near-white page; dark theme lightens toward
 * the near-black page. Both are pinned to AA against their background, and the
 * derived foreground keeps the solid button label legible (#222).
 */
export const deriveThemePrimaries = (
  brandHex: string
): { light: Shade; dark: Shade } => {
  const brand = hexToOklch(brandHex)
  return {
    light: shadeForBackground(brand, LIGHT_BG, 0.45, -1),
    dark: shadeForBackground(brand, DARK_BG, 0.8, 1),
  }
}

/**
 * Install the derived brand shades as a stylesheet so the `.dark` class cascade
 * selects the correct shade per theme. An inline `documentElement.style` write
 * cannot do this: it beats the `.dark` selector and can only carry one shade.
 */
export const applyPrimaryColour = (brandHex: string): void => {
  const { light, dark } = deriveThemePrimaries(brandHex)
  const css =
    `:root { --primary: ${light.primary}; ` +
    `--primary-foreground: ${light.primaryForeground}; }\n` +
    `.dark { --primary: ${dark.primary}; ` +
    `--primary-foreground: ${dark.primaryForeground}; }`

  let style = document.getElementById("brand-primary") as HTMLStyleElement | null
  if (style === null) {
    style = document.createElement("style")
    style.id = "brand-primary"
    document.head.appendChild(style)
  }
  style.textContent = css
}
