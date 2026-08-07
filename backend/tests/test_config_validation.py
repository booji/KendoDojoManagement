"""
Red-phase tests for Issue #256 — JWT_SECRET is not validated at startup.

`app/config.py` currently has `JWT_SECRET: str = os.getenv("JWT_SECRET", "")`
with no validation anywhere; `app/auth/token.py::_key()` only raises the
first time a token is encoded/decoded, so a deployment with an unset/blank
JWT_SECRET boots cleanly and looks healthy until someone actually logs in.

These tests are pure unit tests: no DB, no network. They exercise:

1. A single validation entry point, `app.config.validate_startup_config()`,
   that raises a clear error naming `JWT_SECRET` when it is unset, empty, or
   whitespace-only, and is silent when it holds a real value.
2. That `app.main.lifespan` calls this validation *before* DB init, so a
   misconfigured deployment fails fast at startup rather than at first auth
   attempt.
3. That `app/config.py` no longer supplies a fallback default for
   JWT_SECRET (source-level assertion, mirroring the style used in
   tests/test_docker_config.py).

No Playwright/e2e stub is included for this issue: refusal to start is a
process-level, operator-facing failure with no observable browser behaviour
to assert on. A browser can't be driven against a server that never comes
up, so a strict-xfail e2e stub here would never be promotable to a real
assertion — it would sit as permanent dead weight. The acceptance criteria
are fully covered by the unit tests below plus the existing "does the app
still boot/e2e-suite-pass with a valid secret" coverage that already runs
on every full `docker compose -f docker-compose.test.yml run --rm test`
pass (if JWT_SECRET is ever wrongly rejected when valid, the whole suite
fails to start).
"""

import inspect
import re
from pathlib import Path

import pytest

import app.config as config

CONFIG_PATH = Path(__file__).parent.parent / "app" / "config.py"


# ---------------------------------------------------------------------------
# validate_startup_config() — direct unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", ["", "   ", "\t\n"])
def test_validate_startup_config_raises_when_jwt_secret_missing(
    monkeypatch: pytest.MonkeyPatch, bad_value: str
) -> None:
    monkeypatch.setattr(config, "JWT_SECRET", bad_value)

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "JWT_SECRET" in str(exc_info.value)


def test_validate_startup_config_raises_when_jwt_secret_unset_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates a deployment where JWT_SECRET was never exported at all."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(config, "JWT_SECRET", "")

    with pytest.raises(RuntimeError) as exc_info:
        config.validate_startup_config()

    assert "JWT_SECRET" in str(exc_info.value)


def test_validate_startup_config_passes_with_real_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "JWT_SECRET", "a-real-non-empty-secret-value")

    # Should not raise.
    config.validate_startup_config()


def test_validate_startup_config_entry_point_exists() -> None:
    """A single validation entry point must exist so future required config
    (other secrets) can slot in without inventing a new pattern each time."""
    assert hasattr(config, "validate_startup_config")
    assert callable(config.validate_startup_config)


# ---------------------------------------------------------------------------
# app.main.lifespan — validation must run before DB init
# ---------------------------------------------------------------------------


async def test_lifespan_raises_before_db_init_when_jwt_secret_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    monkeypatch.setattr(config, "JWT_SECRET", "   ")

    db_init_called = False

    async def _fake_init_db() -> None:
        nonlocal db_init_called
        db_init_called = True

    monkeypatch.setattr(main_module, "_init_db", _fake_init_db)

    with pytest.raises(RuntimeError) as exc_info:
        async with main_module.lifespan(main_module.app):
            pass

    assert "JWT_SECRET" in str(exc_info.value)
    assert db_init_called is False, (
        "DB init must not run when startup config validation fails — "
        "validation must happen before _init_db(), not after"
    )


async def test_lifespan_proceeds_to_db_init_when_jwt_secret_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    monkeypatch.setattr(config, "JWT_SECRET", "a-real-non-empty-secret-value")

    db_init_called = False

    async def _fake_init_db() -> None:
        nonlocal db_init_called
        db_init_called = True

    monkeypatch.setattr(main_module, "_init_db", _fake_init_db)

    async with main_module.lifespan(main_module.app):
        pass

    assert db_init_called is True


# ---------------------------------------------------------------------------
# Source-level assertion — no fallback default may be reintroduced
# ---------------------------------------------------------------------------


def test_config_source_has_no_jwt_secret_default() -> None:
    source = CONFIG_PATH.read_text()
    # The old, insecure form: os.getenv("JWT_SECRET", "") or os.getenv("JWT_SECRET", <anything>)
    match = re.search(r'os\.getenv\(\s*["\']JWT_SECRET["\']\s*,', source)
    assert match is None, (
        "app/config.py must not supply a fallback default for JWT_SECRET — "
        'found a call of the form os.getenv("JWT_SECRET", <default>). '
        'JWT_SECRET must be read with os.getenv("JWT_SECRET") (no default) '
        'or os.environ["JWT_SECRET"], with absence/blankness caught by '
        "validate_startup_config() instead."
    )


def test_validate_startup_config_signature_takes_no_required_args() -> None:
    """Keeps the entry point trivially callable from the lifespan with no
    wiring — a future required secret should slot into the same function
    body, not require the caller to pass new arguments."""
    sig = inspect.signature(config.validate_startup_config)
    required_params = [
        p
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind
        not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
    ]
    assert required_params == []
