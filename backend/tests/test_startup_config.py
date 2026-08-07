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
