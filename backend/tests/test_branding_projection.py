"""
Unit tests for issue #213 — login screen branding projection.

Pure function tests — no I/O, no DB, no auth, no fixtures.

Acceptance criterion covered here (AC1):
  Maps raw settings {dojo_name, logo_url, background_image_url, primary_colour,
  login_show_name, login_show_logo, login_show_background} to a GATED public
  view:
    - dojo_name is null/omitted when login_show_name is off
    - logo_url is null/omitted when login_show_logo is off
    - background_image_url is null/omitted when login_show_background is off
    - primary_colour is ALWAYS included, regardless of any toggle
  Each toggle is covered independently on/off, plus combinations, plus the
  all-off default (everything gated out except primary_colour).
"""

from __future__ import annotations

from app.settings.branding import project_branding

_RAW: dict = {
    "dojo_name": "Tokyo Kendo Club",
    "logo_url": "/static/logos/abc.png",
    "background_image_url": "/static/backgrounds/xyz.jpg",
    "primary_colour": "#1D4ED8",
    "login_show_name": True,
    "login_show_logo": True,
    "login_show_background": True,
}


def _raw(**overrides) -> dict:
    data = dict(_RAW)
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# primary_colour always included
# ---------------------------------------------------------------------------


def test_primary_colour_always_included_when_all_toggles_on() -> None:
    result = project_branding(_raw())
    assert result.get("primary_colour") == "#1D4ED8"


def test_primary_colour_always_included_when_all_toggles_off() -> None:
    result = project_branding(
        _raw(
            login_show_name=False,
            login_show_logo=False,
            login_show_background=False,
        )
    )
    assert result.get("primary_colour") == "#1D4ED8"


# ---------------------------------------------------------------------------
# login_show_name toggle
# ---------------------------------------------------------------------------


def test_dojo_name_included_when_login_show_name_on() -> None:
    result = project_branding(_raw(login_show_name=True))
    assert result.get("dojo_name") == "Tokyo Kendo Club"


def test_dojo_name_gated_out_when_login_show_name_off() -> None:
    result = project_branding(_raw(login_show_name=False))
    assert result.get("dojo_name") is None


# ---------------------------------------------------------------------------
# login_show_logo toggle
# ---------------------------------------------------------------------------


def test_logo_url_included_when_login_show_logo_on() -> None:
    result = project_branding(_raw(login_show_logo=True))
    assert result.get("logo_url") == "/static/logos/abc.png"


def test_logo_url_gated_out_when_login_show_logo_off() -> None:
    result = project_branding(_raw(login_show_logo=False))
    assert result.get("logo_url") is None


# ---------------------------------------------------------------------------
# login_show_background toggle
# ---------------------------------------------------------------------------


def test_background_image_url_included_when_login_show_background_on() -> None:
    result = project_branding(_raw(login_show_background=True))
    assert result.get("background_image_url") == "/static/backgrounds/xyz.jpg"


def test_background_image_url_gated_out_when_login_show_background_off() -> None:
    result = project_branding(_raw(login_show_background=False))
    assert result.get("background_image_url") is None


# ---------------------------------------------------------------------------
# Combinations
# ---------------------------------------------------------------------------


def test_name_and_logo_on_background_off() -> None:
    result = project_branding(
        _raw(
            login_show_name=True,
            login_show_logo=True,
            login_show_background=False,
        )
    )
    assert result.get("dojo_name") == "Tokyo Kendo Club"
    assert result.get("logo_url") == "/static/logos/abc.png"
    assert result.get("background_image_url") is None
    assert result.get("primary_colour") == "#1D4ED8"


def test_name_off_logo_and_background_on() -> None:
    result = project_branding(
        _raw(
            login_show_name=False,
            login_show_logo=True,
            login_show_background=True,
        )
    )
    assert result.get("dojo_name") is None
    assert result.get("logo_url") == "/static/logos/abc.png"
    assert result.get("background_image_url") == "/static/backgrounds/xyz.jpg"


def test_only_background_on() -> None:
    result = project_branding(
        _raw(
            login_show_name=False,
            login_show_logo=False,
            login_show_background=True,
        )
    )
    assert result.get("dojo_name") is None
    assert result.get("logo_url") is None
    assert result.get("background_image_url") == "/static/backgrounds/xyz.jpg"
    assert result.get("primary_colour") == "#1D4ED8"


# ---------------------------------------------------------------------------
# All-off default — everything gated out except primary_colour
# ---------------------------------------------------------------------------


def test_all_toggles_off_gates_out_everything_except_primary_colour() -> None:
    result = project_branding(
        _raw(
            login_show_name=False,
            login_show_logo=False,
            login_show_background=False,
        )
    )
    assert result.get("dojo_name") is None
    assert result.get("logo_url") is None
    assert result.get("background_image_url") is None
    assert result.get("primary_colour") == "#1D4ED8"


def test_all_toggles_off_even_when_underlying_values_present() -> None:
    """Gating hides values even though the raw settings still have them set —
    confirms the projection actually gates rather than only omitting nulls."""
    result = project_branding(
        _raw(
            dojo_name="Should Not Leak",
            logo_url="/static/logos/should-not-leak.png",
            background_image_url="/static/backgrounds/should-not-leak.png",
            login_show_name=False,
            login_show_logo=False,
            login_show_background=False,
        )
    )
    assert "Should Not Leak" not in str(result.get("dojo_name"))
    assert result.get("dojo_name") is None
    assert result.get("logo_url") is None
    assert result.get("background_image_url") is None


# ---------------------------------------------------------------------------
# Default logo fallback (#615)
# ---------------------------------------------------------------------------


def test_logo_url_falls_back_to_app_logo_when_none_uploaded() -> None:
    result = project_branding(_raw(logo_url=None, login_show_logo=True))
    assert result.get("logo_url") == "/logo.svg"


def test_uploaded_logo_wins_over_app_logo() -> None:
    result = project_branding(
        _raw(logo_url="/static/logos/abc.png", login_show_logo=True)
    )
    assert result.get("logo_url") == "/static/logos/abc.png"


def test_app_logo_hidden_when_login_show_logo_off() -> None:
    result = project_branding(_raw(logo_url=None, login_show_logo=False))
    assert result.get("logo_url") is None
