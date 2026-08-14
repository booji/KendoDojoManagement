"""
Red-phase tests for Issue #269 — remove the legacy embedded-file DB driver,
fail closed on production-shaped
config defaults.

`app.config.validate_startup_config()` already exists (added for Issue #256,
covered in `tests/test_config_validation.py`) and is the single startup
validation entry point invoked from `app.main.lifespan` before any DB or
network I/O. This file extends that same entry point with two more checks it
does not yet perform:

1. DATABASE_URL must be set to a non-blank value. `app/config.py` has no
   fallback default, so an unset DATABASE_URL must be caught here exactly
   like JWT_SECRET is today, rather than booting against nothing.

2. In a production deployment (signalled by the explicit `APP_ENV=production`
   environment variable — never inferred from `COOKIE_SECURE` or any other
   proxy), leaving `WEBAUTHN_RP_ID` or `WEBAUTHN_ORIGIN` at their localhost
   dev defaults must refuse to start, naming the offending variable. Outside
   production (APP_ENV unset or "development"), the localhost defaults are
   expected and must NOT raise — developers must not be nagged.

No Playwright/e2e stub is included for this issue: every acceptance
criterion here is a process-level startup check with no observable browser
behaviour — a server that refuses to start can't be driven by a browser, and
a strict-xfail stub that can never be promoted to a real UI assertion would
be dead weight. Coverage lives entirely in these unit tests plus the
existing "app still boots against Postgres" coverage that runs on every full
`docker compose -f docker-compose.test.yml run --rm test` pass.
"""

import pytest

import app.config as config

# ---------------------------------------------------------------------------
# DATABASE_URL — must be set, non-blank
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n", None])
def test_validate_startup_config_raises_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch, bad_value: str | None
) -> None:
    monkeypatch.setattr(config, "JWT_SECRET", "a-real-non-empty-secret-value")
    monkeypatch.setattr(config, "DATABASE_URL", bad_value)

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "DATABASE_URL" in str(exc_info.value)


def test_validate_startup_config_passes_with_database_url_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "JWT_SECRET", "a-real-non-empty-secret-value")
    monkeypatch.setattr(
        config,
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/kendo",
    )
    monkeypatch.setattr(config, "APP_ENV", "development", raising=False)

    # Should not raise.
    config.validate_startup_config()


# ---------------------------------------------------------------------------
# APP_ENV=production — WEBAUTHN_RP_ID / WEBAUTHN_ORIGIN must not be left at
# their localhost dev defaults.
# ---------------------------------------------------------------------------


def _set_required_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sets the non-webauthn required vars to valid values so each test below
    isolates only the webauthn-related failure it's checking."""
    monkeypatch.setattr(config, "JWT_SECRET", "a-real-non-empty-secret-value")
    monkeypatch.setattr(
        config,
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@db:5432/kendo",
    )


def test_validate_startup_config_raises_when_production_rp_id_is_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "localhost")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://dojo.example.com")

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "WEBAUTHN_RP_ID" in str(exc_info.value)


def test_validate_startup_config_raises_when_production_origin_is_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "dojo.example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "http://localhost:5173")

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "WEBAUTHN_ORIGIN" in str(exc_info.value)


def test_validate_startup_config_passes_in_production_with_real_webauthn_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "dojo.example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://dojo.example.com")

    # Should not raise.
    config.validate_startup_config()


@pytest.mark.parametrize("dev_app_env", [None, "development"])
def test_validate_startup_config_allows_localhost_defaults_outside_production(
    monkeypatch: pytest.MonkeyPatch, dev_app_env: str | None
) -> None:
    """Developers must not be nagged: APP_ENV unset or 'development' with the
    stock localhost WEBAUTHN_RP_ID/WEBAUTHN_ORIGIN defaults must not raise."""
    _set_required_baseline(monkeypatch)
    if dev_app_env is None:
        monkeypatch.delattr(config, "APP_ENV", raising=False)
    else:
        monkeypatch.setattr(config, "APP_ENV", dev_app_env, raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "localhost")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "http://localhost:5173")

    # Should not raise.
    config.validate_startup_config()


# ---------------------------------------------------------------------------
# JWT_SECRET — regression guard. Issue #256 already covers this behaviour in
# tests/test_config_validation.py; these two are a minimal in-file smoke
# check so this file also fails loudly if a refactor of
# validate_startup_config() ever drops the JWT_SECRET check while adding the
# DATABASE_URL / webauthn checks above.
# ---------------------------------------------------------------------------


def test_validate_startup_config_still_raises_when_jwt_secret_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "JWT_SECRET", "")
    monkeypatch.setattr(
        config,
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@db:5432/kendo",
    )

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "JWT_SECRET" in str(exc_info.value)


def test_validate_startup_config_still_passes_with_real_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "JWT_SECRET", "a-real-non-empty-secret-value")
    monkeypatch.setattr(
        config,
        "DATABASE_URL",
        "postgresql+asyncpg://user:pass@db:5432/kendo",
    )
    monkeypatch.setattr(config, "APP_ENV", "development", raising=False)

    # Should not raise.
    config.validate_startup_config()


# ---------------------------------------------------------------------------
# Issue #292 — shape validation, not literal-equality-to-dev-default.
#
# The checks above only ever caught the exact strings "localhost" /
# "http://localhost:5173". Any other non-production-shaped value (a bare
# hostname with no scheme, an http:// origin against a real domain, an IP
# literal RP ID, a template placeholder straight out of .env.example, or an
# RP ID/origin pair that don't agree on domain) sailed through uncaught.
# These tests describe the shape-based replacement.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_origin",
    [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://192.168.1.5",
        "http://kendo.example.com",
        "kendo.example.com",  # bare hostname, no scheme — not a parseable absolute URL
    ],
)
def test_validate_startup_config_raises_when_production_origin_is_not_https(
    monkeypatch: pytest.MonkeyPatch, bad_origin: str
) -> None:
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "kendo.example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", bad_origin)

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "WEBAUTHN_ORIGIN" in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_rp_id",
    [
        "https://kendo.example.com",  # scheme present
        "kendo.example.com:8443",  # port present
        "kendo.example.com/path",  # path/slash present
        "192.168.1.5",  # IPv4 literal
        "2001:db8::1",  # IPv6 literal
        "localhost",
        "dojo.localhost",  # .localhost subdomain
        "kendo",  # no dot — not a registrable domain shape
    ],
)
def test_validate_startup_config_raises_when_production_rp_id_is_not_bare_hostname(
    monkeypatch: pytest.MonkeyPatch, bad_rp_id: str
) -> None:
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", bad_rp_id)
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://kendo.example.com")

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "WEBAUTHN_RP_ID" in str(exc_info.value)


@pytest.mark.parametrize(
    "var_name, bad_value, other_name, other_value",
    [
        (
            "WEBAUTHN_RP_ID",
            "<your-domain.com>",
            "WEBAUTHN_ORIGIN",
            "https://kendo.example.com",
        ),
        (
            "WEBAUTHN_ORIGIN",
            "https://<your-domain.com>",
            "WEBAUTHN_RP_ID",
            "kendo.example.com",
        ),
    ],
)
def test_validate_startup_config_raises_on_unfilled_template_placeholder(
    monkeypatch: pytest.MonkeyPatch,
    var_name: str,
    bad_value: str,
    other_name: str,
    other_value: str,
) -> None:
    """.env.example ships WEBAUTHN_RP_ID=<your-domain.com>; a deploy that
    forgets to fill this in must be rejected by name, not silently accepted
    because '<your-domain.com>' happens to contain a dot."""
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, var_name, bad_value)
    monkeypatch.setattr(config, other_name, other_value)

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert var_name in str(exc_info.value)


def test_validate_startup_config_raises_when_rp_id_and_origin_domains_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Individually each value is plausible production-shaped, but the RP ID
    is not a registrable suffix of the origin's host — passkeys created
    under this RP ID would never be usable from this origin."""
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "kendo.example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://kendo.other.com")

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    message = str(exc_info.value)
    assert "WEBAUTHN_RP_ID" in message or "WEBAUTHN_ORIGIN" in message


def test_validate_startup_config_passes_when_rp_id_is_registrable_suffix_of_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RP ID need not equal the origin host exactly — a shorter registrable
    suffix (e.g. RP_ID='example.com' for ORIGIN='https://kendo.example.com')
    is the standard WebAuthn pattern for scoping a credential across
    subdomains and must be accepted."""
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://kendo.example.com")

    # Should not raise.
    config.validate_startup_config()


def test_validate_startup_config_passes_when_rp_id_equals_origin_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "kendo.example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://kendo.example.com")

    # Should not raise.
    config.validate_startup_config()


@pytest.mark.parametrize(
    "rp_id, origin",
    [
        ("localhost", "http://localhost:5173"),
        ("localhost", "http://localhost:3000"),
        ("dojo.localhost", "http://dojo.localhost:5173"),
        ("kendo", "http://kendo:8000"),
    ],
)
def test_validate_startup_config_dev_env_unaffected_by_shape_checks(
    monkeypatch: pytest.MonkeyPatch, rp_id: str, origin: str
) -> None:
    """The new shape checks are gated on APP_ENV=='production' exactly like
    the old literal-equality checks were — development must never be nagged,
    regardless of what shape WEBAUTHN_RP_ID/WEBAUTHN_ORIGIN happen to have."""
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "development", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", rp_id)
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", origin)

    # Should not raise.
    config.validate_startup_config()


# ---------------------------------------------------------------------------
# Security review follow-up on #292 — WARNING 1: WEBAUTHN_ORIGIN is passed
# RAW (never re-parsed) as `expected_origin` to py_webauthn's verify
# functions, which string-compare it against the browser's Origin header. The
# browser never sends a trailing slash, path, query, fragment, or userinfo,
# so any of those in WEBAUTHN_ORIGIN would break every registration/
# authentication ceremony in production despite passing the shape checks
# above (https scheme + host only).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_origin",
    [
        "https://kendo.example.com/foo",
        "https://kendo.example.com?x=1",
        "https://kendo.example.com#f",
        "https://user:pass@kendo.example.com",
    ],
)
def test_validate_startup_config_raises_when_origin_has_extra_url_components(
    monkeypatch: pytest.MonkeyPatch, bad_origin: str
) -> None:
    """A path, query, fragment, or userinfo in WEBAUTHN_ORIGIN can never
    match the browser's Origin header, which is always bare scheme+host."""
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "kendo.example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", bad_origin)

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "WEBAUTHN_ORIGIN" in str(exc_info.value)


def test_validate_startup_config_normalizes_trailing_slash_on_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare trailing slash is a likely copy-paste artifact, not a real
    path, so it is normalized away rather than rejected. Critically, the
    normalized value (not the raw one with the slash) must be what ends up
    in config.WEBAUTHN_ORIGIN, since that global is read raw and passed
    straight to py_webauthn as expected_origin elsewhere in the app."""
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "kendo.example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://kendo.example.com/")

    # Should not raise.
    config.validate_startup_config()

    assert config.WEBAUTHN_ORIGIN == "https://kendo.example.com"


# ---------------------------------------------------------------------------
# Security review follow-up on #292 — WARNING 2: hostnames are
# case-insensitive. urlsplit(...).hostname always lowercases, but
# WEBAUTHN_RP_ID was compared as-is, so a legitimately-cased RP ID was
# wrongly rejected as a suffix mismatch against its own (lowercased) origin
# host.
# ---------------------------------------------------------------------------


def test_validate_startup_config_rp_id_suffix_match_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "Kendo.Example.com")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", "https://kendo.example.com")

    # Should not raise.
    config.validate_startup_config()

    # The lowercased value is what gets exported for use elsewhere, since
    # config.WEBAUTHN_RP_ID is read raw and passed straight to py_webauthn.
    assert config.WEBAUTHN_RP_ID == "kendo.example.com"


def test_validate_startup_config_strips_surrounding_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A trailing space copy-pasted from .env must not silently fail
    suffix/shape matching with a message that doesn't visibly show the
    invisible character — strip before validating, and export the stripped
    value since that's what the rest of the app actually reads."""
    _set_required_baseline(monkeypatch)
    monkeypatch.setattr(config, "APP_ENV", "production", raising=False)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", " kendo.example.com ")
    monkeypatch.setattr(config, "WEBAUTHN_ORIGIN", " https://kendo.example.com ")

    # Should not raise.
    config.validate_startup_config()

    assert config.WEBAUTHN_RP_ID == "kendo.example.com"
    assert config.WEBAUTHN_ORIGIN == "https://kendo.example.com"


# ---------------------------------------------------------------------------
# Security review follow-up on #292 — a second gap in the WARNING 1
# writeback: CORS_ORIGINS is computed at IMPORT time —
#     CORS_ORIGINS = [...] if CORS_ORIGINS env set else [WEBAUTHN_ORIGIN]
# — and captured by reference into CORSMiddleware via
# `app.main.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, ...)`,
# which also runs at import time (module-level `app.add_middleware(...)`
# call in app/main.py), before `validate_startup_config()` ever runs inside
# `lifespan()`. A `globals()["CORS_ORIGINS"] = ...` writeback from
# validate_startup_config() would rebind app.config's own attribute but
# NOT the list object already frozen into main.py's middleware stack — too
# late to have any effect. So unlike WEBAUTHN_RP_ID/WEBAUTHN_ORIGIN (read via
# `config.WEBAUTHN_RP_ID` attribute access at call time in
# passkey_service.py/invite_service.py, where a runtime writeback works
# fine), CORS_ORIGINS must be correct at IMPORT time — these tests reload
# app.config with env vars set, the same pattern test_passkey_timing.py uses
# for AUTH_BEGIN_MIN_DURATION_MS.
# ---------------------------------------------------------------------------


def test_cors_origins_fallback_uses_normalized_webauthn_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When CORS_ORIGINS is not explicitly set, it falls back to
    [WEBAUTHN_ORIGIN] — the common self-host case. A trailing slash or
    surrounding whitespace on WEBAUTHN_ORIGIN must not survive into that
    fallback, since CORS_ORIGINS is compared raw against the browser's
    Origin header, exactly like WEBAUTHN_ORIGIN itself is for py_webauthn."""
    import importlib

    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("WEBAUTHN_ORIGIN", " https://kendo.example.com/ ")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.WEBAUTHN_ORIGIN == "https://kendo.example.com"
        assert reloaded.CORS_ORIGINS == ["https://kendo.example.com"]
    finally:
        monkeypatch.delenv("WEBAUTHN_ORIGIN", raising=False)
        importlib.reload(config)


def test_cors_origins_explicit_value_is_not_touched_by_origin_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly configured CORS_ORIGINS must be left exactly as set —
    the normalization coupling only applies to the derived fallback."""
    import importlib

    monkeypatch.setenv(
        "CORS_ORIGINS", "https://kendo.example.com/, https://other.example.com/"
    )
    monkeypatch.setenv("WEBAUTHN_ORIGIN", "https://kendo.example.com/")
    reloaded = importlib.reload(config)
    try:
        # Explicit CORS_ORIGINS keeps its own (already-existing) whitespace
        # stripping only — no trailing-slash normalization is applied,
        # because it was not derived from WEBAUTHN_ORIGIN.
        assert reloaded.CORS_ORIGINS == [
            "https://kendo.example.com/",
            "https://other.example.com/",
        ]
    finally:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        monkeypatch.delenv("WEBAUTHN_ORIGIN", raising=False)
        importlib.reload(config)
