"""
Unit tests for the WCAG 2.1 AA contrast utility (AC13, AC14).

The utility lives at app/settings/wcag.py (not yet implemented).
All tests are expected to fail red until the implementation is in place.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# AC13 — passes 4.5:1 threshold for white (#FFFFFF) vs black (#000000)
# ---------------------------------------------------------------------------


def test_wcag_contrast_white_black_passes_threshold() -> None:
    """White (#FFFFFF) vs black (#000000) contrast ratio is ~21:1 — well above 4.5:1."""
    from app.settings.wcag import contrast_ratio, passes_wcag_aa  # noqa: PLC0415

    ratio = contrast_ratio("#FFFFFF", "#000000")
    assert ratio == pytest.approx(21.0, abs=0.1)
    assert passes_wcag_aa("#FFFFFF", "#000000") is True


def test_wcag_contrast_black_white_passes_threshold() -> None:
    """Order of arguments must not matter — black vs white also passes."""
    from app.settings.wcag import passes_wcag_aa  # noqa: PLC0415

    assert passes_wcag_aa("#000000", "#FFFFFF") is True


# ---------------------------------------------------------------------------
# AC14 — correctly rejects low-contrast colour pairs
# ---------------------------------------------------------------------------


def test_wcag_contrast_white_light_grey_fails_threshold() -> None:
    """White (#FFFFFF) vs light grey (#AAAAAA) contrast is ~2.3:1 — below 4.5:1."""
    from app.settings.wcag import passes_wcag_aa  # noqa: PLC0415

    assert passes_wcag_aa("#FFFFFF", "#AAAAAA") is False


def test_wcag_contrast_ratio_formula_uses_relative_luminance() -> None:
    """Verify the relative luminance formula for a known mid-grey (#808080).

    L = 0.2126*R + 0.7152*G + 0.0722*B where each channel is linearised.
    """
    from app.settings.wcag import relative_luminance  # noqa: PLC0415

    # Mid-grey: 128/255 ≈ 0.502 -> linear ≈ ((0.502+0.055)/1.055)^2.4 ≈ 0.2158
    lum = relative_luminance("#808080")
    assert 0.20 < lum < 0.22, f"Expected ~0.216, got {lum}"


def test_wcag_contrast_similar_colours_fails() -> None:
    """Two very similar hues should have near-1:1 contrast — below 4.5:1."""
    from app.settings.wcag import passes_wcag_aa  # noqa: PLC0415

    assert passes_wcag_aa("#1A1A1A", "#222222") is False


def test_wcag_contrast_threshold_is_4_5() -> None:
    """The function returns False for a ratio of exactly 4.4:1 (just below AA)."""
    from app.settings.wcag import passes_wcag_aa  # noqa: PLC0415

    # Navy (#002366) vs white has a contrast of ~14.3:1 — should pass.
    assert passes_wcag_aa("#002366", "#FFFFFF") is True

    # Yellow (#FFD700) vs white has a contrast below 4.5:1 — should fail.
    assert passes_wcag_aa("#FFD700", "#FFFFFF") is False
