# Claiming the first admin account requires a pre-provisioned setup token

The operator provisions a `SETUP_TOKEN` before first boot — a podman secret
injected as env under Quadlet, a value in the env file for the Compose
self-host — and `POST /api/setup/passkey/complete` requires it. The app reads
it from config like any other secret, compares it in constant time, and
refuses to start without it. `GET /api/setup` and `/api/setup/passkey/begin`
are unchanged, and the existing `_has_registered_user()` guard still runs
first, so a claimed instance stays 404 regardless of what token is presented.

## Context

`/api/setup`, `/api/setup/passkey/begin` and `/api/setup/passkey/complete` are
unauthenticated and guarded only by `_has_registered_user()` — `count(
PasskeyCredential) > 0` — and `complete` promotes whoever finishes the ceremony
to `role="admin"`. Until someone deliberately finishes, anyone who loads the
page takes the dojo (#388).

Counting credentials rather than users is correct and stays: an abandoned
ceremony leaves a user row with no credential, and counting those would lock
out an operator whose browser died mid-registration. The consequence is that
the window never closes on its own.

The hostname is not a secret. Traefik's Let's Encrypt certificate reaches the
certificate transparency logs the moment it is issued, so a public deployment
is discoverable by an opportunistic scanner within minutes of first boot —
plausibly before the operator has opened a browser. The only mitigation today
is a paragraph in `docs/deployment.md` telling the operator to claim the
account immediately, which asks them to win a race they were not told they
were in until they read it.

That opportunistic scanner is the realistic attacker, not someone targeting
this dojo by name. The LAN UAT box and the public PROD box therefore differ in
exposure but not in the right policy: the LAN box is simply one the attacker
rarely reaches, and a policy that only PROD gets is a policy that is wrong on
the day a UAT box gets a public DNS name. One policy covers both.

The deployment already has the shape this needs.
`deploy/quadlet/kendo-app.container` injects two podman secrets as environment:

```
Secret=kendo_database_url,type=env,target=DATABASE_URL
Secret=kendo_jwt_secret,type=env,target=JWT_SECRET
```

A third entry is a line of unit file and a `podman secret create`. Nothing in
the app has to learn a new way to hold a secret, and nothing has to learn a new
way to hand one to the operator.

## Considered options

**A pre-provisioned `SETUP_TOKEN` (chosen).** It is config, not state: no
table, no migration, no process-scoped value to re-fetch, and no retrieval path
to invent. It survives restarts, which matters under `Restart=always` — a
crash-looping unclaimed instance must not invalidate the token the operator is
part-way through using. It does not require shell access from the person who
claims the account, so an operator can hand a URL and a token to a dojo
secretary. Rotation is `podman secret rm`/`create` plus a restart.

Its costs are real and accepted. It adds a step before first boot, which the
deployment runbook must carry. The plaintext exists wherever the operator
generated it — shell history, unless they pipe it (`openssl rand -base64 32 |
podman secret create kendo_setup_token -`). Under Compose there are no podman
secrets, so it lives in the same env file that already holds the database
password: the same exposure class as what is there, not a new one.

**A token generated at boot and printed to the container log.** Attractive
because `podman logs kendo-app` is already in the day-2 table, and it needs no
provisioning step. Rejected on the Quadlet specifics. Container stdout goes to
journald, so the token persists at journald's retention rather than in
something ring-buffer-shaped, and log aggregation would carry it off-box;
"the token dies with the process" bounds its *validity*, not where the string
is written. Worse, `Restart=always` means an unclaimed instance that
crash-loops issues a fresh token per restart, silently invalidating the one the
operator copied a minute ago and failing their correctly-filled form with a
401. The runbook would have to say "re-read the logs after any restart", which
is a bad instruction to have to give during first setup.

**A token minted through the CLI** (`app/cli.py`, alongside
`create-recovery-token`), retrieved with `podman exec kendo-app ...`. This
works with no extra wiring — `DATABASE_URL` is already injected as env and
exec inherits it — and keeps the secret out of the journal. Rejected because it
needs persisted token state, a table and a migration, to deliver a secret that
config can carry for free, and because it makes shell access a hard requirement
for first setup, which forecloses handing a URL to a non-technical dojo
secretary.

**A pre-seeded admin email in the env file**, with setup refusing any other
address, carries no new secret and uses a value the operator already sets per
host. Rejected as insufficient alone: it authenticates an address, not a
person, so a scanner that guesses or learns the dojo's contact address is back
inside the window. It narrows the race rather than closing it.

**Binding the window to a boot deadline** — setup answers only within N minutes
of process start — composes with anything here but does not stop this
attacker. A CT-log scanner arrives within minutes of first boot, inside any
window generous enough not to strand an operator on a slow start, and the
option adds a liveness and clock dependency for that partial benefit. Not
adopted; revisit only if the token proves insufficient.

**Keeping setup open and making it observable** would be the honest minimum if
the current design were right for this threat model. It is not: the problem is
an unbounded window on a publicly discoverable host, not the absence of a
signal about it. The observability is not lost — an unclaimed instance still
logs one startup line saying so, carrying the claim URL and no secret.

## Consequences

**A missing `SETUP_TOKEN` fails startup, claimed or not.** It joins
`_REQUIRED_STARTUP_VARS` in `app/config.py` alongside `JWT_SECRET` and
`DATABASE_URL`, so a misconfigured deployment dies at boot with a named error
instead of booting into a claimable instance. Validating it only while the
instance is unclaimed was considered and rejected: it needs a database query in
`lifespan()` to decide, and it invites an operator to delete the secret after
claiming — which boots fine until the day the database is restored or wiped,
and then fails at exactly the wrong moment. One unconditional rule is smaller
and fails in the safe direction. `.env.example` gains the variable, and
development needs a value like any other required secret.

**Redeploy against an existing database does not reopen anything.** Claimed
state lives in `PasskeyCredential` rows; the existing guard runs first, so a
restarted or upgraded claimed instance returns 404 as it does today. The token
is a second gate in front of that guard, never a replacement for it — and an
instance whose token leaks after it is claimed is not thereby claimable.

**No migration and no new state.** The token is a config value compared with
`secrets.compare_digest` at `complete`. `begin` stays open: it creates only the
phantom user rows it creates today, and gating it would add a second place to
get the check wrong without closing anything `complete` does not already close.
`GET /setup` stays open so the SPA can decide whether to render the setup page.

**Lockout is a rotation, not a rebuild.** An operator who loses the token
recreates the secret and restarts; nothing in the database has to change. The
existing break-glass path does not cover a never-claimed instance and is not
being stretched to — `app/cli.py create-recovery-token` resolves a `User` row
by email, and on an unclaimed instance there is none. That gap is acceptable
because rotation costs seconds.

**The runbook gains a step and loses a race.** `docs/deployment.md` currently
tells the operator to claim the account before a stranger does; it will instead
tell them to create the secret before first boot. The `curl /api/setup` check
stays useful and its meaning is unchanged.
