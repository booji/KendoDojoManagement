"""Image content sniffing — pure functions, no I/O.

An upload's `content_type` header and filename extension are both supplied by
the client and are evidence of nothing. `sniff_image_kind` decides an upload's
real type from its leading bytes, so the caller can reject a payload whose
contents disagree with what it claims to be.

Deliberately narrow: it recognises exactly the formats the dojo settings
uploads accept, and returns None for everything else. SVG is excluded — it is
an XML document that can carry script, and serving one from our own origin
would be stored XSS.
"""

from __future__ import annotations

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF_MAGICS = (b"GIF87a", b"GIF89a")
_RIFF_MAGIC = b"RIFF"
_WEBP_TAG = b"WEBP"

# Enough bytes to cover the longest signature we check: RIFF (4) + size (4)
# + "WEBP" (4).
_HEADER_BYTES = 12


def sniff_image_kind(contents: bytes) -> str | None:
    """Return the MIME type implied by `contents`, or None if unrecognised.

    Only the formats accepted by the settings uploads are recognised. A
    truncated or partial signature is not a match.
    """
    header = contents[:_HEADER_BYTES]

    if header.startswith(_PNG_MAGIC):
        return "image/png"
    if header.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if header.startswith(_GIF_MAGICS):
        return "image/gif"
    # WEBP is a RIFF container; the form-type tag at offset 8 is what
    # distinguishes it from WAV, AVI and friends.
    if header.startswith(_RIFF_MAGIC) and header[8:12] == _WEBP_TAG:
        return "image/webp"
    return None
