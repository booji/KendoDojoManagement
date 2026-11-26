# Claim the admin account (the setup token gates it)

> **On the quick self-host** the token is `SETUP_TOKEN` in `.env`, and the
> commands below that name `kendo-app` or a podman secret are the Quadlet
> spellings: the claim itself is the same request either way.

The instance is now reachable. Claiming the first admin account requires the
`kendo_setup_token` secret from [section 2-4](../deployment.md#2-4-lay-it-all-down-as-kendo) — the setup endpoints answer
`401 {"detail": "Invalid setup token"}` without it (ADR-0003). Nothing to race:
an opportunistic scanner that finds the host minutes after Traefik's Let's
Encrypt certificate hits the certificate transparency logs cannot claim
anything without that value.

The token is required whether or not the instance is already claimed: the app
refuses to start without it, so do not delete the secret after claiming. A
database restore or wipe would otherwise boot an unclaimed instance with no
gate in front of it.

**The browser is the way you do this.** Open `https://<your-domain>/`: the
setup page asks for the admin's first name, surname and email, and the setup
token. The claim creates the admin's member record as well as their account —
every account belongs to a member, the first admin included — and the email
is the one they will sign in with. Paste the token into the "Setup token"
field and complete the passkey registration. The page sends
it as an `X-Setup-Token` header on `/api/setup/passkey/begin` and
`/api/setup/passkey/complete`, and a wrong token comes back on the form as
"Invalid setup token". The value is never stored in the browser — reloading the
page means pasting it again.

No shell access is needed to claim the account, so the URL and the token can go
to whoever is becoming the admin. The `curl` below is for debugging a claim
that is not working, not a step:

```bash
curl -sS -X POST https://<your-domain>/api/setup/passkey/begin \
  -H 'Content-Type: application/json' \
  -H "X-Setup-Token: $SETUP_TOKEN" \
  -d '{"email":"admin@your-dojo","first_name":"Ai","surname":"Sato"}'
# 401 {"detail":"Invalid setup token"} -> wrong or missing token.
# 404 {"detail":"Setup already completed"} -> claimed; the token is irrelevant.
```

Then confirm the window is shut.

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://<your-domain>/api/setup
# 404 -> setup is closed, an account exists.
# 200 -> still unclaimed (the token is still required to claim it).
# anything else (000, 502, ...) -> the check never reached the app. That is not
# a closed window; fix the request and re-run before you believe it.
```

The instance is claimed once an Admin Account exists, and stays claimed even
if that Admin later deletes every passkey. An abandoned ceremony leaves only a
member Account, which does **not** count, so an operator whose browser died
mid-ceremony is never locked out.

**Lost the token?** Rotate it — nothing in the database has to change:

```bash
# Keep the value: a podman secret cannot be read back, so piping straight into
# `secret create` leaves you with a token nobody knows.
token=$(openssl rand -base64 32 | tr -d '\n')
podman secret rm kendo_setup_token
printf '%s' "$token" | podman secret create kendo_setup_token -
systemctl --user restart kendo-app
echo "$token"   # hand it over out of band, then clear your scrollback
```

`app/cli.py create-recovery-token` does **not** cover a never-claimed instance:
it resolves an Account by email, and an unclaimed instance has none. Rotation
is the only path there, and it costs seconds.
