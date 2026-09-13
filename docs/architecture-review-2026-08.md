# Architecture review — August 2026

Deepening opportunities found by walking the hot spots of the preceding ~50
commits. Vocabulary is deliberate: **module** (interface + implementation),
**interface** (everything a caller must know, not just the signature),
**depth** (behaviour per unit of interface), **seam** (where an interface
lives), **adapter** (a thing satisfying an interface at a seam), **leverage**
(what callers gain), **locality** (what maintainers gain).

Two rules of thumb applied throughout: the **deletion test** — if deleting a
module concentrates complexity it earns its keep, if it merely moves it the
module was a pass-through — and **one adapter is a hypothetical seam, two is a
real one**.

Candidate 01 (the duplicated Federation Membership card) shipped as #361. The
four below are open, in the order I would take them.

---

## 02 — "What a Member may see of a Session" has no home

**Strength:** strong.

**Files:** `backend/app/sessions/router.py` (~280–350), `app/sessions/ical.py`,
`app/sessions/models.py`.

**Problem.** Three read paths each re-derive the same rule in their own handler
body:

- `GET /sessions` composes `_strip_coach_notes(_strip_cancelled(...))`;
- `GET /sessions/{id}` writes `result["coach_notes"] = None` inline and **does
  not filter cancelled sessions**;
- `ical.py` carries a third, prose-documented allow-list.

`_normalize_instance` must additionally be remembered at five call sites. This
is an authorisation rule scattered across handlers: it is reachable only
through an ASGI request, so every test of it costs an authenticated client, and
a fourth read endpoint is correct only if its author copies carefully.

**Proposed shape.** `app/sessions/projection.py`, owning one question — what
does a caller with this Role see?

    visible_session(record, *, role)
    visible_sessions(records, *, role)

Behind that interface: normalisation to `SessionInstanceRead`, cancellation
filtering, and admin-only field redaction. Handlers keep what is genuinely
HTTP. This is the shape `app/sessions/templates.py` established for the Session
Template lifecycle in #352, applied to reads instead of writes.

**Payoff.** The next admin-only field on a Session is redacted once. Redaction
becomes a table test with no request, no DB, no fixtures — alongside
`test_checkin_window.py`, which already has that shape.

---

## 03 — The repository seam speaks `dict[str, Any]`

**Strength:** worth exploring. Right direction, wrong as a big bang.

**Scale:** 240 occurrences across 26 modules under `backend/app/`;
`backend/tests/fake_repositories.py` is 673 lines.

**Problem.** Every repository Protocol returns an untyped dict, so the interface
is not the signature — it is every key name, every "this is an ISO string, not a
`date`" convention, and every default, none of which a type checker can hold.
The cost is visible: callers write `date.fromisoformat(template["start_date"])`,
routers re-apply `_normalize_*` to fill missing optionals, and the fake
repositories re-implement the dict shaping the real ones do, because the shape
is written down nowhere else.

**History confirms it hurts.** #345 "settle the date type at the repository
seam"; #345 "delete the date guards the member stubs were propping up"; #348
"one member fake for eleven partial stubs".

**Proposed shape.** Repositories return the Pydantic Read models `models.py`
already defines. The seam does not move; only its currency changes.
`SessionInstanceRead` becomes the return type, `_normalize_instance`
disappears, and the fake constructs the same model as the real repository.
`app/member_federations/` already has a typed `MemberFederationRecord` — the
precedent exists.

**Sequencing.** One repository per PR under the existing red-green slicing,
starting with `sessions`. Judge after the first before spreading.

---

## 04 — The load / save / error ladder, repeated

**Strength:** worth exploring.

**Files:** `AdminSettingsPage.tsx` (47 `useState`, 1405 lines),
`MemberDetailPage.tsx` (36), `SessionDetailPage.tsx` (27),
`SettingsPage.tsx` (20).

**Problem.** Every card re-declares the same ladder — `data`, `loading`,
`loadError`, `saveStatus`, `saveError` — plus a
`useEffect(fetch).then(set).catch(setError)` and a try/catch save handler. Each
is a shallow module: the interface (the state names) is as large as the
implementation (two setters and a fetch), and nothing is shared, so changing how
API failures surface is a thirty-site edit.

**Proposed shape.** Two hooks in `frontend/src/lib/`, built on the
`request`/`isApiError` module `api/client.ts` already centralises (#343):

    useResource(fetcher, deps)  -> { data, error, reload }
    useAction(fn)               -> { run, status, error }

Deliberately stops short of TanStack Query, which brings caching and
invalidation nobody has asked for.

**Payoff.** Cards shed ~10 lines of state plumbing each and become nearly pure
render functions, which the existing `__tests__/` suite is good at.

---

## 05 — The current User is fetched once per page

**Strength:** speculative. Listed for completeness; do not start here.

**Files:** `App.tsx` plus six pages calling `getMe()`; 45 `isAdmin` references;
`contexts/DojoSettingsProvider.tsx` and `contexts/ThemeProvider.tsx` as the
established pattern.

**Problem.** The Role of the current User is global knowledge being re-derived
locally, then threaded down as a prop.

**Why it stays speculative.** The duplicate fetches are cheap, the threading is
harmless, and `isAdmin` as an explicit prop makes components *easier* to render
in tests than a context would. Revisit if a third Role appears and the boolean
stops being enough.

---

## Incidental findings

- `GET /sessions/{id}` does not filter cancelled sessions for a non-admin,
  while `GET /sessions` does. Folded into candidate 02, but it is a live
  inconsistency today.
- `UBIQUITOUS_LANGUAGE.md` gained **Federation Membership** with #361. No
  `CONTEXT.md` or `docs/adr/` exists in this repo, so no candidate here
  contradicts a recorded decision — there are none to contradict.
