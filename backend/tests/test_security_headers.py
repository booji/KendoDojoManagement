import re

from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_x_frame_options_deny() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.headers["x-frame-options"] == "DENY"


async def test_x_content_type_options_nosniff() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"


async def test_referrer_policy() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_content_security_policy() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.headers["content-security-policy"] == (
        "default-src 'self'; img-src 'self' blob: data:; "
        "object-src 'none'; base-uri 'self'"
    )


async def test_csp_allows_blob_and_data_images() -> None:
    """Admin Settings previews an upload from a `blob:` URL while the request
    is in flight, and Vite inlines small assets as `data:` URIs in the built
    CSS. Both fall back to default-src without an explicit img-src, so both
    are blocked in the production image and in nothing else — the e2e suite
    drives Vite, which never passes a response through this middleware."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    img_src = [
        directive.strip()
        for directive in response.headers["content-security-policy"].split(";")
        if directive.strip().startswith("img-src")
    ]
    assert img_src, "CSP must set img-src explicitly, not leave it to default-src"
    assert "blob:" in img_src[0]
    assert "data:" in img_src[0]


async def test_spa_html_has_no_inline_script() -> None:
    """The production image serves index.html *through this middleware*, so an
    inline <script> in it is dead code in production however well it works
    under Vite (#385). Checked against the source file rather than the build
    output because frontend/dist is gitignored and absent in CI.

    Keep the pre-paint theme script in frontend/public/theme.js: a same-origin
    file needs no hash or nonce, so nothing has to be re-synced when it
    changes.
    """
    import os
    from pathlib import Path

    root = (
        Path(os.environ["REPO_ROOT"])
        if "REPO_ROOT" in os.environ
        else Path(__file__).parent.parent.parent
    )
    html = (root / "frontend" / "index.html").read_text()

    inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert not inline, (
        f"frontend/index.html has {len(inline)} inline <script> tag(s) "
        f"({inline}); CSP script-src 'self' blocks them in the production "
        "image. Move the code to frontend/public/ and load it with src=."
    )


async def test_security_headers_on_non_health_route() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/members")

    assert "x-frame-options" in response.headers
    assert "x-content-type-options" in response.headers
    assert "referrer-policy" in response.headers
    assert "content-security-policy" in response.headers


async def test_cors_allows_webauthn_origin_by_default() -> None:
    from app.config import WEBAUTHN_ORIGIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/health",
            headers={
                "Origin": WEBAUTHN_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.headers.get("access-control-allow-origin") == WEBAUTHN_ORIGIN
