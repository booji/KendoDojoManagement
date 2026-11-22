import ipaddress
import logging
import os
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from publicsuffixlist import PublicSuffixList

load_dotenv(override=False)

# Every API router is mounted under this prefix so the SPA and the API share
# one origin (ADR-0001). Anything matching on a request path — the
# constant-time middleware's endpoint set above all — must build its paths from
# this, or a change here silently stops it matching.
API_PREFIX = "/api"


def read_secret(name: str) -> str:
    """The secret `name`, from the file `<name>_FILE` names, else `<name>`.

    Production mounts each secret as a file (#462): an environment variable
    shows up in `podman inspect` and /proc/<pid>/environ and is inherited by
    every child process. The plain variable is the fallback dev and test use.
    """
    path = os.getenv(f"{name}_FILE")
    if not path:
        return os.getenv(name) or ""
    try:
        with open(path) as f:
            # A trailing newline is the editor's or `echo`'s, never the secret's.
            return f.read().rstrip("\r\n")
    except OSError as e:
        # Not a fallback to the variable: that would surface as "<name> must
        # be set" and send the operator looking in the wrong place.
        raise RuntimeError(
            f"{name}_FILE names {path}, which cannot be read: {e}"
        ) from e


DATABASE_URL: str = read_secret("DATABASE_URL")

# The superuser login, given only to the migration step (ADR-0007): the app
# itself connects as the restricted user named in DATABASE_URL and must never
# see this one.
MIGRATION_DATABASE_URL: str = read_secret("MIGRATION_DATABASE_URL")

# development | production. Explicit and never inferred from other settings
# (e.g. COOKIE_SECURE) — production-only checks below key off this alone.
# Normalized (stripped + lowercased) at import so every comparison against
# it — here and in validate_startup_config() — is exact-value safe. Without
# this, APP_ENV=Production/PRODUCTION/"production " (a trailing space is an
# easy copy-paste artifact from a .env file) would silently fall through to
# the permissive development path and skip every production-only WebAuthn
# check below with no signal that it happened (#310). An unrecognized value
# after normalization is rejected outright in validate_startup_config()
# rather than silently defaulting to development — see the check there.
APP_ENV: str = os.getenv("APP_ENV", "development").strip().lower()

JWT_SECRET: str = read_secret("JWT_SECRET")

# Pre-provisioned secret that gates claiming the first admin account
# (ADR-0003). Required unconditionally, claimed or not: making it conditional
# on unclaimed state needs a DB query in lifespan() and invites an operator to
# delete the secret after claiming — which boots fine until the database is
# restored or wiped, and then reopens the claim to whoever finds it first.
SETUP_TOKEN: str = read_secret("SETUP_TOKEN")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
# An Auth Session's idle window is JWT_EXPIRE_MINUTES (the name predates
# ADR-0008 and is deployment surface). This is its absolute ceiling, however
# continuously it is used: sliding keeps an active Auth Session alive, which would
# mean "signed in forever" without this cap. Past it the user signs in again —
# one passkey touch.
SESSION_MAX_MINUTES: int = int(os.getenv("SESSION_MAX_MINUTES", str(60 * 24 * 7)))
COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

# Trust X-Forwarded-For for client IP (rate limiting, lockout). Enable ONLY when
# the app is reachable solely through a trusted reverse proxy (Traefik in
# UAT/PROD) that overwrites the header; leaving it off keeps dev spoof-proof.
TRUST_PROXY_XFF: bool = os.getenv("TRUST_PROXY_XFF", "false").lower() == "true"

# IANA timezone the dojo runs in. Sourced from the container's TZ env var so the
# calendar feed anchors event wall-clock times to the dojo's zone (with correct
# DST) instead of emitting floating time. Defaults to UTC.
TIMEZONE: str = os.getenv("TZ", "UTC")

# Minimum wall-clock duration (ms) the passkey begin endpoints must take,
# regardless of whether the email is known/authorized (real path) or
# unknown/unauthorized (decoy path). Closes a timing side channel: the real
# path does strictly more DB work (credential SELECT, pending_challenge
# UPDATE, commit) than the decoy path, which otherwise lets an attacker
# enumerate registered emails from response latency alone. This value MUST
# stay above the real path's p99 latency, or the floor stops masking the
# asymmetry it exists to hide.
#
# 100ms is calibrated, not guessed (#268): measured against PostgreSQL, the
# real path's p99 is 16.8ms and its worst observed case 27.9ms with requests
# arriving one at a time. The headroom over that is deliberate — the
# measurement is from a developer workstation, and the commit that dominates
# the real path is slower on production storage. Full method, numbers and the
# reasoning for this figure: docs/auth-timing-calibration.md.
#
# Raising this further is not the fix for a *saturated* server: past ~4
# simultaneous begin requests, queueing alone puts the p99 beyond any sane
# floor. ConstantTimeAuthMiddleware logs a warning on every overrun; treat that
# as a capacity or rate-limit signal.
#
# A non-positive value would make the pad never fire and silently restore the
# leak, so a typo or a well-meaning "disable this in dev" is treated as
# misconfiguration rather than honoured. Same for a non-integer.
_AUTH_BEGIN_MIN_DURATION_DEFAULT = 100
try:
    AUTH_BEGIN_MIN_DURATION_MS: int = int(
        os.getenv("AUTH_BEGIN_MIN_DURATION_MS", str(_AUTH_BEGIN_MIN_DURATION_DEFAULT))
    )
except ValueError:
    AUTH_BEGIN_MIN_DURATION_MS = _AUTH_BEGIN_MIN_DURATION_DEFAULT
    logging.getLogger(__name__).warning(
        "AUTH_BEGIN_MIN_DURATION_MS is not an integer; falling back to %dms",
        _AUTH_BEGIN_MIN_DURATION_DEFAULT,
    )
if AUTH_BEGIN_MIN_DURATION_MS <= 0:
    logging.getLogger(__name__).warning(
        "AUTH_BEGIN_MIN_DURATION_MS must be positive; falling back to %dms. "
        "A non-positive floor disables timing-side-channel protection on the "
        "passkey begin endpoints.",
        _AUTH_BEGIN_MIN_DURATION_DEFAULT,
    )
    AUTH_BEGIN_MIN_DURATION_MS = _AUTH_BEGIN_MIN_DURATION_DEFAULT


def _strip_origin_whitespace_and_trailing_slash(origin: str) -> str:
    """Strip surrounding whitespace and a bare trailing slash (not a real
    path) from a WEBAUTHN_ORIGIN-shaped value.

    This runs unconditionally at IMPORT time, not just inside
    validate_startup_config(). CORS_ORIGINS falls back to `[WEBAUTHN_ORIGIN]`
    a few lines below, and that fallback list is captured by reference into
    CORSMiddleware in app/main.py — also at import time, via
    `app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, ...)`,
    which runs and freezes its kwargs before `lifespan()` (and therefore
    `validate_startup_config()`) ever executes. A later rebind of
    `config.WEBAUTHN_ORIGIN`/`config.CORS_ORIGINS` from inside
    validate_startup_config() would be too late to reach that already-built
    middleware stack — unlike WEBAUTHN_RP_ID/WEBAUTHN_ORIGIN reads elsewhere
    (`config.WEBAUTHN_RP_ID` in passkey_service.py/invite_service.py), which
    are live attribute lookups at call time and do see a later writeback.
    So the derived-origin normalization that matters for CORS has to happen
    here, before CORS_ORIGINS is computed, not later in
    validate_startup_config() (which remains the place that *rejects*
    outright-invalid shapes in production; it re-applies this same
    normalization too, harmlessly, for values monkeypatched after import).

    Only a same-shaped ("scheme://host/") trailing slash is stripped — a
    real path, query, fragment or userinfo is left untouched so
    validate_startup_config() can still reject it by name in production.
    """
    stripped = origin.strip()
    parsed = urlsplit(stripped)
    if (
        parsed.scheme
        and parsed.hostname
        and parsed.path == "/"
        and not parsed.query
        and not parsed.fragment
    ):
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    return stripped


WEBAUTHN_RP_ID: str = os.getenv("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_ORIGIN: str = _strip_origin_whitespace_and_trailing_slash(
    os.getenv("WEBAUTHN_ORIGIN", "http://localhost:5173")
)
WEBAUTHN_CHALLENGE_TTL_SECONDS: int = int(
    os.getenv("WEBAUTHN_CHALLENGE_TTL_SECONDS", "300")
)

# CORS_ORIGINS' fallback deliberately reuses the already-normalized
# WEBAUTHN_ORIGIN above (not a fresh read of the env var) — see
# _strip_origin_whitespace_and_trailing_slash's docstring for why that
# normalization has to happen before this fallback is built. An explicitly
# configured CORS_ORIGINS is a separately-operator-supplied list (often
# multiple origins) and is intentionally left as-is beyond its existing
# per-entry whitespace strip — it was not derived from WEBAUTHN_ORIGIN, so
# the coupling above does not apply to it.
_cors_origins_env: str = os.getenv("CORS_ORIGINS", "")
CORS_ORIGINS: list[str] = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else [WEBAUTHN_ORIGIN]
)

# Names of module-level globals in this file that MUST hold a non-blank
# string at startup. A misconfigured deployment (unset/empty/whitespace-only)
# must fail fast here rather than boot cleanly and fail later at first use
# (e.g. JWT_SECRET only used at the first passkey ceremony for an unknown email). Add
# future required secrets to this tuple — validate_startup_config() reads
# each by name from this module's globals at call time, so no other wiring
# is needed.
_REQUIRED_STARTUP_VARS: tuple[str, ...] = ("JWT_SECRET", "DATABASE_URL", "SETUP_TOKEN")

# Below, "production-shaped" validation for WEBAUTHN_RP_ID/WEBAUTHN_ORIGIN is
# done by *shape*, not by comparing against the literal dev defaults
# ("localhost" / "http://localhost:5173"). An earlier version of this check
# only rejected those two exact strings, which let *any other* wrong value —
# a bare hostname with no scheme, an http:// origin against a real domain, an
# IP literal RP ID, an unfilled ".env.example" template placeholder, or an
# RP ID that doesn't actually match the origin's domain — sail through
# uncaught and boot happily into a broken (or spoofable) passkey setup.
# Checking the *shape* WebAuthn actually requires catches all of those, the
# two literal defaults included, in one pass. Still gated on APP_ENV (after
# normalization — see the module-level assignment near the top of this file)
# being "production" so developers running the stock .env are never nagged.


def _reject_template_placeholder(name: str, value: str) -> None:
    """.env.example ships WEBAUTHN_RP_ID=<your-domain.com> and
    WEBAUTHN_ORIGIN=https://<your-domain.com>. Both contain a dot, so without
    this explicit check they would sail past the shape checks below and boot
    with a placeholder as the real domain."""
    if "<" in value or ">" in value:
        raise RuntimeError(
            f"{name} still contains a template placeholder ('{value}'). "
            f"Set {name} to the dojo's real value from .env.example."
        )


def _validate_production_origin(origin: str) -> str:
    """Validate WEBAUTHN_ORIGIN is an absolute https:// URL with a host and
    nothing else, and return the normalized origin string that should
    replace it everywhere.

    WEBAUTHN_ORIGIN is never re-parsed at the call sites — it's passed raw
    as `expected_origin` to py_webauthn's verify functions, which
    string-compare it against the browser's Origin header. That header is
    always bare scheme+host: never a path, query, fragment, or userinfo. Any
    of those in WEBAUTHN_ORIGIN would therefore break every registration and
    authentication ceremony in production, so they're rejected here — except
    a bare trailing slash ("https://dojo.example.com/"), which is a likely
    copy-paste artifact rather than a deliberate path and carries no
    information worth failing startup over. That one case is normalized away
    instead of rejected, and the caller MUST use the returned value (not the
    original `origin` argument) everywhere WEBAUTHN_ORIGIN is read —
    stripping the slash only here and leaving it in the exported global
    would just move the bug from this function to every ceremony.
    """
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError(
            f"WEBAUTHN_ORIGIN ('{origin}') must be an absolute URL with an "
            "https:// scheme and a host, e.g. https://dojo.example.com. "
            "WebAuthn refuses to register credentials against a non-secure "
            "or unparseable origin outside localhost."
        )
    if "@" in parsed.netloc:
        raise RuntimeError(
            f"WEBAUTHN_ORIGIN ('{origin}') must not contain userinfo "
            "(user:pass@) — browsers never send credentials in the Origin "
            "header. Set WEBAUTHN_ORIGIN to just the scheme and host, e.g. "
            "https://dojo.example.com."
        )
    if parsed.query:
        raise RuntimeError(
            f"WEBAUTHN_ORIGIN ('{origin}') must not include a query string "
            "— browsers never send one in the Origin header. Set "
            "WEBAUTHN_ORIGIN to just the scheme and host, e.g. "
            "https://dojo.example.com."
        )
    if parsed.fragment:
        raise RuntimeError(
            f"WEBAUTHN_ORIGIN ('{origin}') must not include a fragment — "
            "browsers never send one in the Origin header. Set "
            "WEBAUTHN_ORIGIN to just the scheme and host, e.g. "
            "https://dojo.example.com."
        )
    if parsed.path not in ("", "/"):
        raise RuntimeError(
            f"WEBAUTHN_ORIGIN ('{origin}') must not include a path — "
            "browsers never send one in the Origin header. Set "
            "WEBAUTHN_ORIGIN to just the scheme and host, e.g. "
            "https://dojo.example.com."
        )
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


_public_suffix_list: PublicSuffixList | None = None


def _get_public_suffix_list() -> PublicSuffixList:
    """Return a process-wide PublicSuffixList, built once from the package's
    bundled snapshot on first use.

    `PublicSuffixList()` with no `source` argument reads the PSL data that
    ships inside the wheel — it never fetches or updates the list over the
    network, which matters because this runs during startup validation,
    before any outbound I/O is expected (and possibly before it's even
    permitted, e.g. an egress-locked container). Building the list is not
    free, so it's done once lazily rather than at import time or on every
    call.
    """
    global _public_suffix_list
    if _public_suffix_list is None:
        _public_suffix_list = PublicSuffixList()
    return _public_suffix_list


def _validate_production_rp_id(rp_id: str) -> None:
    """Validate WEBAUTHN_RP_ID is a bare hostname: no scheme, no port, no
    path, not an IP literal, not localhost (or a .localhost subdomain), and
    shaped like a registrable domain (contains a dot)."""
    if "://" in rp_id or "/" in rp_id:
        raise RuntimeError(
            f"WEBAUTHN_RP_ID ('{rp_id}') must be a bare hostname with no "
            "scheme and no path — e.g. dojo.example.com, not a URL."
        )
    try:
        ipaddress.ip_address(rp_id)
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False
    if is_ip_literal:
        raise RuntimeError(
            f"WEBAUTHN_RP_ID ('{rp_id}') must be a hostname, not an IP "
            "address literal. Set it to the dojo's real domain."
        )
    if ":" in rp_id:
        raise RuntimeError(
            f"WEBAUTHN_RP_ID ('{rp_id}') must be a bare hostname with no "
            "port — e.g. dojo.example.com, not host:port."
        )
    if rp_id == "localhost" or rp_id.endswith(".localhost"):
        raise RuntimeError(
            f"WEBAUTHN_RP_ID is still set to '{rp_id}' while "
            "APP_ENV=production. Set it to the dojo's real domain."
        )
    if "." not in rp_id:
        raise RuntimeError(
            f"WEBAUTHN_RP_ID ('{rp_id}') has no dot, so it isn't a "
            "registrable domain. Set it to the dojo's real domain, e.g. "
            "dojo.example.com."
        )


def validate_startup_config() -> None:
    """Raise RuntimeError naming the offending variable if any required
    startup config is unset, empty, or whitespace-only; if APP_ENV is
    missing or not a string; if APP_ENV, after normalization (stripped and
    lowercased), isn't "development" or "production"; or if a
    production-shaped deployment (normalized APP_ENV=="production") has a
    WEBAUTHN_RP_ID/WEBAUTHN_ORIGIN pair that isn't shaped like a real,
    matching production WebAuthn configuration.

    Reads each variable from this module's globals at call time (not at
    import time), so tests can monkeypatch e.g. `config.JWT_SECRET` and
    callers (app.main.lifespan) can invoke this with no arguments before any
    DB or network I/O.
    """
    for name in _REQUIRED_STARTUP_VARS:
        value = globals().get(name)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(
                f"{name} (or the file {name}_FILE names) must be set to a non-empty "
                "value. Refusing to start with a missing/blank secret."
            )

    # APP_ENV is normalized at import time (see the module-level assignment
    # above), but this function re-normalizes whatever it reads from
    # globals() rather than trusting that — tests monkeypatch
    # `config.APP_ENV` directly (e.g. to "Production" or " production ")
    # after import, bypassing the import-time normalization entirely, and
    # every other check in this function already follows the same
    # read-globals-at-call-time convention. Re-normalizing here is what
    # makes that monkeypatched value still hit the production path instead
    # of silently falling through to development (#310).
    #
    # The import-time assignment above (`os.getenv(...).strip().lower()`)
    # always produces a str, so a missing or non-string APP_ENV global here
    # can only mean the module state was tampered with after import (e.g. a
    # test monkeypatching it to None, or a deleted attribute) — never a
    # developer's unset environment variable, which the import-time default
    # already turns into "development" before this function ever runs.
    # Falling back to "development" for that case would reintroduce exactly
    # the silent skip #310 closed: every production-only check below would
    # be bypassed with no signal (#313).
    _raw_app_env = globals().get("APP_ENV")
    if not isinstance(_raw_app_env, str):
        raise RuntimeError(
            "APP_ENV is missing or not a string. Refusing to start rather "
            "than falling through to the permissive development path."
        )
    app_env = _raw_app_env.strip().lower()
    if app_env not in ("development", "production"):
        raise RuntimeError(
            f"APP_ENV ('{_raw_app_env}') must be 'development' or "
            "'production' (case/whitespace-insensitive). An unrecognized "
            "value is rejected outright here rather than silently falling "
            "through to the permissive development path and skipping every "
            "production-only check below with no signal (#310)."
        )

    if app_env == "production":
        # Stripped/lowercased here BECAUSE these values are read raw
        # elsewhere (passkey_service.py, invite_service.py) and passed
        # straight to py_webauthn — validating a cleaned-up copy while
        # leaving whitespace or mixed case in the exported global would
        # leave the underlying ceremony broken even though startup passed.
        # A trailing-space copy-paste from .env, or a legitimately-cased
        # hostname (hostnames are case-insensitive; urlsplit(...).hostname
        # always lowercases, so the raw RP ID must match that normalization
        # or every suffix comparison against a real origin false-positives)
        # must both be usable without failing startup.
        rp_id = (globals().get("WEBAUTHN_RP_ID") or "").strip().lower()
        origin = (globals().get("WEBAUTHN_ORIGIN") or "").strip()

        # Both secrets ship as angle-bracket placeholders in .env.example /
        # .env.prod.example, and a non-blank placeholder clears the
        # required-vars check above. A production deploy that copies the
        # template and misses one would otherwise boot with a value published
        # in this repo — for SETUP_TOKEN that is the claim gate handed to
        # anyone who reads it (ADR-0003).
        _reject_template_placeholder("JWT_SECRET", globals().get("JWT_SECRET") or "")
        _reject_template_placeholder("SETUP_TOKEN", globals().get("SETUP_TOKEN") or "")

        _reject_template_placeholder("WEBAUTHN_RP_ID", rp_id)
        _reject_template_placeholder("WEBAUTHN_ORIGIN", origin)

        origin = _validate_production_origin(origin)
        # Never empty: _validate_production_origin refuses an origin with no host.
        origin_host = urlsplit(origin).hostname or ""
        _validate_production_rp_id(rp_id)

        if rp_id != origin_host and not origin_host.endswith("." + rp_id):
            raise RuntimeError(
                f"WEBAUTHN_RP_ID ('{rp_id}') must be a registrable suffix "
                f"of WEBAUTHN_ORIGIN's host ('{origin_host}') — either "
                "equal to it, or the origin host must end with "
                f"'.{rp_id}'. Passkeys created under this RP ID would "
                "never be usable from this origin otherwise."
            )

        # Per the HTML "is a registrable domain suffix of, or is equal to"
        # algorithm, equality short-circuits the whole check: when the RP ID
        # is exactly the origin host, it is always valid and the Public
        # Suffix List is never consulted — that's the same shape as a
        # single-tenant deployment hosted directly on a PaaS root domain
        # (e.g. RP ID and origin host both literally "herokuapp.com"), and
        # rejecting it would be wrong per spec.
        #
        # Only in the strict-suffix branch (rp_id != origin_host) can the RP
        # ID itself be a *public suffix* — a domain anyone can register a
        # subdomain of (a PaaS wildcard domain like herokuapp.com, or a
        # multi-label ccTLD suffix like co.uk) rather than a real
        # registrable domain the operator controls. Browsers enforce this
        # client-side (a public-suffix RP ID triggers a SecurityError during
        # the WebAuthn ceremony), so a server that boots anyway is silently
        # broken — passkeys would appear to work at signup and then fail
        # every subsequent authentication. This check is a fail-fast
        # ergonomics guard, not a security boundary in itself: the browser
        # remains the actual enforcing boundary, but failing at startup
        # turns a confusing client-side ceremony failure into an immediate,
        # actionable server error.
        if rp_id != origin_host and _get_public_suffix_list().is_public(rp_id):
            raise RuntimeError(
                f"WEBAUTHN_RP_ID ('{rp_id}') is a public suffix — a domain "
                "anyone can register a subdomain of (e.g. a PaaS wildcard "
                "domain or a multi-label ccTLD), not a registrable domain "
                "this dojo controls. Browsers refuse to create or use "
                "passkeys under a public-suffix RP ID. Set WEBAUTHN_RP_ID "
                "to the full host instead, e.g. 'mydojo.herokuapp.com'."
            )

        globals()["WEBAUTHN_RP_ID"] = rp_id
        globals()["WEBAUTHN_ORIGIN"] = origin
