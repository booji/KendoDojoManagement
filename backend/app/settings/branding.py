"""Pure projection of raw dojo settings into the gated public branding view.

No I/O, no DB, no auth — a plain function safe to call from anywhere,
including the unauthenticated /settings/branding endpoint.
"""

from __future__ import annotations

from typing import Any

# The app's own logo, served by the frontend; the sidebar uses the same fallback.
DEFAULT_LOGO_URL = "/logo.svg"


def project_branding(settings: dict[str, Any]) -> dict[str, Any]:
    """Map raw settings to the gated public branding dict.

    - dojo_name is only included when login_show_name is truthy.
    - logo_url is only included when login_show_logo is truthy; with no
      uploaded logo it falls back to the app's own /logo.svg.
    - background_image_url is only included when login_show_background is truthy.
    - primary_colour is always included.
    """
    return {
        "dojo_name": settings["dojo_name"] if settings.get("login_show_name") else None,
        "logo_url": (
            (settings["logo_url"] or DEFAULT_LOGO_URL)
            if settings.get("login_show_logo")
            else None
        ),
        "background_image_url": (
            settings["background_image_url"]
            if settings.get("login_show_background")
            else None
        ),
        "primary_colour": settings["primary_colour"],
    }
