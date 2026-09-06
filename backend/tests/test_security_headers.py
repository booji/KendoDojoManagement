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

    assert response.headers["content-security-policy"] == "default-src 'self'"


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
