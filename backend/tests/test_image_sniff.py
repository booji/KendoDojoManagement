"""
Tests for issue #240 — upload content sniffing.

`upload_logo` / `upload_background` previously trusted the client-supplied
`content_type` header and the filename extension, neither of which is evidence
of anything. These tests pin a pure `sniff_image_kind` helper that decides an
image's real type from its leading bytes, plus the HTTP-level rejection it
enables.

Pure unit tests — no DB, no I/O.
"""

from __future__ import annotations

import pytest

from app.settings.images import sniff_image_kind

# ---------------------------------------------------------------------------
# Minimal real headers for each accepted format
# ---------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF87 = b"GIF87a" + b"\x00" * 16
GIF89 = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP" + b"\x00" * 16


class TestAcceptsRealImages:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (PNG, "image/png"),
            (JPEG, "image/jpeg"),
            (GIF87, "image/gif"),
            (GIF89, "image/gif"),
            (WEBP, "image/webp"),
        ],
    )
    def test_recognises_supported_format(self, payload: bytes, expected: str) -> None:
        assert sniff_image_kind(payload) == expected


class TestRejectsEverythingElse:
    def test_empty_payload(self) -> None:
        assert sniff_image_kind(b"") is None

    def test_arbitrary_bytes(self) -> None:
        assert sniff_image_kind(b"fake-png-bytes") is None

    def test_truncated_png_signature(self) -> None:
        """A prefix of the PNG magic is not a PNG."""
        assert sniff_image_kind(b"\x89PNG") is None

    def test_svg_is_not_accepted(self) -> None:
        """SVG can carry script; it is deliberately not in the allowed set."""
        assert sniff_image_kind(b'<svg xmlns="http://www.w3.org/2000/svg"/>') is None

    def test_html_disguised_as_png(self) -> None:
        """The actual attack: HTML body, image/png content-type, .png filename."""
        assert sniff_image_kind(b"<html><script>alert(1)</script></html>") is None

    def test_riff_container_that_is_not_webp(self) -> None:
        """RIFF alone is not enough — a WAV must not pass as an image."""
        assert sniff_image_kind(b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE") is None
