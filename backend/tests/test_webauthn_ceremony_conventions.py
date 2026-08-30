"""Structural guards for the WebAuthn begin-ceremony seam (issue #354).

Three endpoints answer for any identifier, registered or not, and must be
indistinguishable whether or not it is known::

    POST /auth/register/passkey/begin
    POST /auth/login/passkey/begin
    POST /auth/invites/redeem/begin

Their responses used to be built in two modules (`passkey_service` and
`invite_service`) held in step by matching comments and one private import
across the seam. Four shape rules had to agree on both sides per call --
resident-key requirement, user-verification level, user-id byte width and
version nibbles, and where the challenge comes from -- and each one was
enforced by a docstring asking the next author to remember. That convention
failed three times (#239 shape tells, #267 `allowCredentials`, #300 the
stable-vs-random `user.id` oracle).

`app.auth.webauthn_ceremony` now owns the ceremony, with real-vs-decoy as an
internal branch. These tests keep it that way: a fourth begin path, or an
edit by someone who has not read the other module, cannot reintroduce a
second construction site without failing here.

No database: the structural checks parse source, and the parity checks call
the ceremony functions directly, which touch nothing but config.
"""

import ast
import json
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
CEREMONY = APP / "auth" / "webauthn_ceremony.py"

# The two calls that decide the shape of a begin response. Every one of the
# four rules is an argument to one of these, so a second call site is exactly
# the drift this issue closes.
_OPTION_BUILDERS = {
    "generate_registration_options",
    "generate_authentication_options",
}


def _python_sources() -> list[Path]:
    """Every module under app/, `__init__.py` included.

    An empty package file parses to an empty tree and matches nothing, so
    excluding them buys no speed -- and re-exports are exactly the kind of
    thing that accumulates there.
    """
    return sorted(APP.rglob("*.py"))


def _called_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


def test_only_the_ceremony_module_builds_webauthn_options() -> None:
    """One module owns the four shape rules.

    Anywhere else calling `generate_registration_options` or
    `generate_authentication_options` is a second place the resident-key
    requirement, user-verification level, user-id width or challenge source
    can be chosen -- which is what #239, #267 and #300 each turned out to be.
    """
    offenders = {
        path.relative_to(APP).as_posix(): sorted(
            _called_names(ast.parse(path.read_text())) & _OPTION_BUILDERS
        )
        for path in _python_sources()
        if path != CEREMONY
    }
    offenders = {path: calls for path, calls in offenders.items() if calls}

    assert offenders == {}, (
        "WebAuthn options are built outside app/auth/webauthn_ceremony.py: "
        f"{offenders}. The begin-response shape must have exactly one "
        "construction site -- see this module's docstring for the three "
        "enumeration bugs that parity-by-convention produced."
    )


def test_no_auth_module_imports_private_names_from_another() -> None:
    """No module in `app/auth` reaches into another's private helpers.

    `invite_service` used to import `_decoy_user_id` (and three more) from
    `passkey_service`. That import was the seam: it made two modules share a
    derivation while leaving each free to choose the surrounding shape
    independently.

    Scoped to `app/auth` because that is the boundary this issue is about.
    Elsewhere in the app a cross-module private import is untidy; here it is
    the mechanism three enumeration bugs travelled along.
    """
    offenders: dict[str, list[str]] = {}
    for path in _python_sources():
        if path.parent != APP / "auth":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            # `node.level > 0` is a relative import -- always in-app, and
            # `node.module` is then the bare submodule name
            # ("passkey_service"), so an `app.` prefix check alone would wave
            # through exactly the import this test exists to catch.
            if node.level == 0 and not (node.module or "").startswith("app."):
                continue
            private = [a.name for a in node.names if a.name.startswith("_")]
            if private:
                offenders.setdefault(path.relative_to(APP).as_posix(), []).extend(
                    f"{node.module}.{name}" for name in private
                )

    assert offenders == {}, (
        f"private names imported across app/auth modules: {offenders}. A shared "
        "private helper is a seam held by convention -- give it a home that "
        "owns the whole decision instead."
    )


# ---------------------------------------------------------------------------
# Body-length parity
#
# The four shape rules govern the fields webauthn_ceremony chooses.
# `user_name` is a fifth, supplied by the caller, and it is the one field
# whose width the module cannot equalise on its own. These two tests record
# where that lands today.
# ---------------------------------------------------------------------------

_EMAILS = (
    "a@b.co",
    "sam@dojo.test",
    "a-fairly-long-address@some-dojo.example.org",
)


def _body_length(ceremony) -> int:
    return len(json.dumps(ceremony.response))


def test_register_begin_real_and_decoy_bodies_are_the_same_length() -> None:
    """The register decoy echoes the caller's own email, so it matches the
    real path exactly at every address width -- no Content-Length oracle."""
    from app.auth.webauthn_ceremony import Subject, register_begin

    for email in _EMAILS:
        real = _body_length(register_begin(email, Subject("u" * 36, email)))
        decoy = _body_length(register_begin(email, subject=None))
        assert real == decoy, (
            f"register begin bodies differ for {email!r}: real={real} "
            f"decoy={decoy} -- response size is a one-call oracle that the "
            "constant-time middleware does not cover, it pads latency only"
        )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known residual, see app.auth.webauthn_ceremony.invite_begin. The "
        "invite decoy synthesises a fixed-width name because it cannot know "
        "the invitee's address; equalising it means the REAL path must "
        "synthesise one too, which is what the invitee's authenticator shows "
        "them at every login. Product call, not a refactor call. Tokens are "
        "unguessable, so this enumerates nothing -- it only tells the holder "
        "of one link whether that link is still usable."
    ),
)
def test_invite_begin_real_and_decoy_bodies_are_the_same_length() -> None:
    from app.auth.webauthn_ceremony import Subject, invite_begin

    for email in _EMAILS:
        real = _body_length(invite_begin("tok", Subject("u" * 36, email)))
        decoy = _body_length(invite_begin("tok", subject=None))
        assert real == decoy, (
            f"invite begin bodies differ for {email!r}: real={real} decoy={decoy}"
        )
