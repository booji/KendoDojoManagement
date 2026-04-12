"""WCAG 2.1 contrast utility — pure functions, no I/O."""


def relative_luminance(hex_colour: str) -> float:
    """Return the WCAG 2.1 relative luminance of a hex colour string."""
    h = hex_colour.lstrip("#")
    r_int = int(h[0:2], 16)
    g_int = int(h[2:4], 16)
    b_int = int(h[4:6], 16)

    def _linearise(val: int) -> float:
        srgb = val / 255
        if srgb <= 0.03928:
            return srgb / 12.92
        return ((srgb + 0.055) / 1.055) ** 2.4

    r = _linearise(r_int)
    g = _linearise(g_int)
    b = _linearise(b_int)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Return the WCAG 2.1 contrast ratio between two hex colours."""
    l1 = relative_luminance(hex1)
    l2 = relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def passes_wcag_aa(hex1: str, hex2: str) -> bool:
    """Return True if the two colours meet WCAG AA contrast ratio (4.5:1)."""
    return contrast_ratio(hex1, hex2) >= 4.5
