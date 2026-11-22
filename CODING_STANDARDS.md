# Coding standards

Read at review time, and before writing UI.

## UI Conventions

### Desktop Layout
Pages use full-width layout with `px-4` padding. No `max-w-*` constraint on page wrappers — content fills the available space beside the sidebar. Use responsive grid (`md:grid-cols-2`, `md:grid-cols-4` etc.) to structure content on wider screens rather than capping width.

### Copy to Clipboard
Clipboard copying goes through `frontend/src/components/CopyButton.tsx` — do
not hand-roll `navigator.clipboard.writeText` with its own `copied` state. Four
pages predate the component and still do (issue #367); if you are editing one
of them anyway, migrate it.

### Dismissing Dialogs
Dialogs do not close on an outside click; menus and sheets do. A stray click
must not throw away a half-filled form or a one-time secret, so the `Dialog`
wrapper (`frontend/src/components/ui/dialog.tsx`) sets
`disablePointerDismissal` for every dialog — do not override it per dialog.
Esc, the ✕ button and Cancel still close a dialog.

### Button Ordering (macOS HIG)
Action buttons are right-aligned (`justify-end`). Order left-to-right: most destructive → least destructive → primary/safe action. Example: `Cancel Series` | `Cancel Session` | `Edit`. The default/safe action always sits rightmost.

**Confirm dialogs are the exception.** A dialog that confirms an action the user just chose puts `Cancel` leftmost and the confirming action rightmost, even when that action is destructive: `Cancel` | `Delete permanently`. This is the HIG alert rule (Cancel on the leading side, the action on the trailing side); on small screens `DialogFooter` stacks them with Cancel at the bottom. For a destructive confirm, give Cancel the initial focus (`DialogContent initialFocus={cancelRef}`) so Enter on open never confirms. This follows the WAI-ARIA APG (focus the least destructive action) rather than the HIG's "no default button", which has no web equivalent short of focusing nothing. The exception: a dialog with an input, such as type-to-confirm, lets the input take focus instead. A destructive option that is *not* the dialog's main action still goes leftmost: `Discard` | `Cancel` | `Save`.

## Backend Conventions

### Feature Packages
Each feature is a package under `backend/app/<feature>/`, split by layer:

- `router.py`: the FastAPI routes
- `schemas.py`: Pydantic request and response models
- `db_models.py`: SQLAlchemy tables
- `repository.py`: data access
- `dependencies.py`: the `Depends` providers that wire the above together

`schemas.py` follows the common FastAPI convention, where `models` would read as
database tables. Six older features still name the file `models.py`, pending
the rename in #617; new code uses `schemas.py`. Extra modules (`service.py`,
`erasure.py`, `checkin_window.py`) are fine when they hide real logic; do not
add one only to forward calls.

### Repositories
Data access sits behind a `typing.Protocol` named `Abstract<Thing>Repository`,
implemented by `Sql<Thing>Repository` over an `AsyncSession`. Routes and
services depend on the Protocol, never the SQL class, so tests swap in the fakes
in `backend/tests/fake_repositories.py`. The SQL class is built in
`dependencies.py` by a `get_<thing>_repo` provider that takes the unit of work.

### Unit of Work
A request's transaction is the `AbstractUnitOfWork` from `app.dependencies.get_uow`.
The route commits through `uow.commit()`; repositories never commit. The one
exception is `SqlAuthSessionRepository.slide`, which commits because it runs in
the auth guard before any route, and its docstring says why. A new exception
needs the same justification in its docstring.

### Dependency Aliases
A router declares its dependencies once, as `Annotated` aliases at the top of
the module, and route signatures use the aliases:

```python
_Repo = Annotated[AbstractMemberRepository, Depends(get_member_repo)]
_UoW = Annotated[AbstractUnitOfWork, Depends(get_uow)]
_Admin = Annotated[AccountClaims, Depends(REQUIRE_ADMIN)]
```

### Authorization
Every route states who may call it in its signature, with a guard from
`app.auth.guards`: `REQUIRE_ADMIN`, `REQUIRE_MEMBER`, `require_role(...)` or
`require_passkey_enrolment`. Do not check roles inside the route body. Only
routes a caller reaches without a session go unguarded: the health check,
first-admin setup (`app/routers/setup.py`), the auth entry points in
`app/auth/router.py` (passkey login, invite and recovery redemption, logout),
`GET /branding` (the sign-in page shows it) and the iCal feed (calendar apps
cannot sign in; it serves only an allowlist of fields). A new unguarded route
needs a stated reason. `GET /session-types` is unguarded with none, pending
#620.

### Field Visibility
A field one audience must not see is kept out by that audience's response
model, never by blanking or deleting a key before returning a dict. The route
declares the model (`response_model` or a typed return), so a field the model
does not list cannot be sent. The iCal feed's `_PUBLIC_FIELDS` allowlist
(`app/sessions/ical.py`) is the reference; the REST session routes still strip
`coach_notes` by hand, pending #619.

### Admin Audit Events
An Admin's write to member personal data or Dojo settings, and every export,
logs a `log_admin_event` (`app.core.security_logger`, #460). An edit records
the field names from `changed_fields`, never their values: the values are the
personal data being audited. Other security-relevant events go through
`log_security_event`.

### Async and Tooling
Routes, repositories and the unit of work are `async`. Python 3.13. Ruff
(`E`, `F`, `I`, `UP`, line length 88) must pass both `ruff check` and
`ruff format --check`; CI enforces both.
ty is the type checker: `uv run ty check app` must exit 0, and CI enforces it
(#618). Suppress with `# ty: ignore[rule]` only where ty is wrong, with a
one-line reason.

### Docstrings and Comments
A docstring or comment says why, not what: the constraint, the trade-off, or
the case that is easy to break. Cite the issue that made the decision (`#340`).
