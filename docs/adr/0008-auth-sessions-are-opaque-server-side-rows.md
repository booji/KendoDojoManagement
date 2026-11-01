# Auth Sessions are opaque server-side rows, not JWTs

Auth Sessions used to be stateless HS256 JWTs carrying `role` and `is_active`,
re-read from the database only at renewal. Nothing could revoke one: a stolen
cookie lived out its 7-day ceiling, a demotion took up to half a token life to
bite, and logout only cleared the cookie. Worse, a leaked `JWT_SECRET` let an
attacker mint an Auth Session for any Account, or a recovery token, which is
enough to enrol their own passkey on it and keep it.

Now every Auth Session is a row in `auth_sessions`. The table is not called
`sessions`, because a **Session** is a training event. The cookie carries a
random id (`secrets.token_urlsafe(32)`) and the table stores only its SHA-256,
so a database dump or backup yields no live Auth Session. The guard looks the
row up on every authenticated request and joins the Account and its Member,
so role and whether the Member may sign in always come from the database.

- **Revocation is deleting rows, and the foreign keys do most of it.** Logout
  deletes the row; "sign out everywhere" deletes all of the Account's rows,
  the current one included. `account_id` is `ON DELETE CASCADE`, so erasure
  revokes with no code. Each row records the passkey it signed in with
  (`passkey_id`, nullable, `ON DELETE CASCADE`), so removing a lost device's
  passkey ends that device's Auth Sessions. A demotion needs no revocation
  hook: the next request reads the new row. Archiving or suspending is refused
  the same way, and also deletes the Account's rows (see the #484 amendment).
- **Recovery tokens are rows too**, with a `kind` of `recovery` and a
  15-minute life, still sent as a Bearer header and refused in the cookie.
  They are single-use: the row is deleted once the new passkey is enrolled.
  Redeeming one does not revoke the Account's other Auth Sessions; "sign out
  everywhere" is the tool for that. This removes the last JWT, so `joserfc`
  goes. `JWT_SECRET` stays, because it also keys the HMAC behind the decoy
  user ids in `webauthn_ceremony.py`, but leaking it no longer grants access.
  It and `JWT_EXPIRE_MINUTES` keep their names: they are deployment surface,
  and renaming them is not worth breaking every instance's env file.
- **Lifetime is unchanged:** 8 hours idle, 7 days absolute. `expires_at` slides
  forward once an Auth Session is past the halfway mark of its idle window,
  not on every request. The cookie's `max_age` is the absolute ceiling and is
  set once, at sign-in; the server enforces the idle window. The cookie is
  never re-set mid-session, so `SessionRenewalMiddleware` and its logout race
  go away. The slide is written in the guard, before the route runs, and most
  guarded routes are reads that never commit, so
  `SqlAuthSessionRepository.slide` commits itself: the one repository that
  does, and safe only because nothing else is pending at that point. The cost
  of a cookie set only once is that it can outlive its idle-expired row, which
  is the stale cookie #397 fixed: accepted, because the id it carries is
  refused and the SPA routes to /login on the 401.
- **Expired rows are deleted at sign-in**, in one indexed statement, and
  refused when read. There is no scheduler.
- **"Sign out everywhere" is the Account's own.** An Admin version waits for a
  deactivate action to exist.
- **No Auth Session list on the profile.** Naming a device means storing a
  User-Agent and IP: personal data that erasure would have to cover, for a
  feature "sign out everywhere" already covers.

## Considered Options

- **Keep the JWT and add a `jti` checked against a table.** Rejected: once every
  request reads the table, the signature proves nothing the row doesn't, and a
  leaked `JWT_SECRET` would still forge recovery tokens.
- **Keep role and active status in the token, and delete Auth Sessions when
  they change.** Rejected: every future write to either needs a matching
  revocation call, and missing one is a silent privilege bug. The per-request
  read is one indexed join.
- **Removing any passkey revokes all the Account's other Auth Sessions.**
  Rejected: the `passkey_id` foreign key ends exactly the lost device's
  sessions, with no code.
- **Clean up expired rows in the migrate step.** Rejected: it runs only when the
  app restarts, which a long-running instance rarely does.

Deploying this signs everyone out once: existing JWT cookies have no row.

Decided in issue #455.

Amended by #484: whether an Account may sign in is its Member's
**Membership Status**, not an Account flag. `archived` and `suspended` are
refused at sign-in, recovery, passkey enrolment and on every authenticated
request (401, as for no Auth Session); `inactive` keeps access. The rule is
`app.auth.accounts.MAY_SIGN_IN`, one SQL predicate every check uses, the
Auth Session join included. `accounts.is_active`, which nothing ever set
false, is dropped.

Barring a Member also deletes every Auth Session row of their Account, of both
kinds, in the same transaction as the status change. The per-request refusal
alone left the rows in place, so an Admin reinstating the Member before they
expired revived them: a session the Member, or whoever held their cookie, had
when they were barred came back with no new sign-in. The refusal stays the
guarantee while the bar lasts; the deletion makes the bar final for every
session that predates it. This is the one place a status change revokes, and
it does not reopen the rejected "delete Auth Sessions when they change"
option: missing the call would only bring back the revival, never let a
barred Member in.
