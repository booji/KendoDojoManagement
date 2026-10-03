# The app connects as a least-privilege database user

The official PostgreSQL image makes `POSTGRES_USER` (`kendo`) a superuser, and
every process used to connect as it — including the internet-facing web app. A
compromised app (SQL injection, code execution in its container) could then run
shell commands in the database container with `COPY … TO PROGRAM`, read and
write server files, drop the schema, and create users. The app needs none of
that: it never changes the schema at runtime. So the web app and `app/cli.py`
connect as a second database user that can only read and write rows, and `kendo`
stays the superuser for migrations, backup and restore. The goal is to contain a
compromised app, not to hide data from it: the app user still reads and writes
every app table.

- **Two URLs.** `DATABASE_URL` is the app user's login everywhere; a new
  `MIGRATION_DATABASE_URL` holds the superuser login and is given only to the
  migration step, so the superuser password never reaches the app container.
- **The migration step maintains the app user.** `app/db/bootstrap.py` already
  runs as superuser before every app start. After `alembic upgrade head` it
  creates the user named in `DATABASE_URL` if missing, sets its password from
  the secret, and re-applies the grants, on every run: existing volumes are
  covered, drift is repaired, and rotating the password is changing the secret.
- **Grants:** `SELECT, INSERT, UPDATE, DELETE` on app tables, `USAGE, SELECT` on
  sequences, `SELECT` only on `alembic_version` (so a compromised app cannot
  fake the schema version), set as default privileges for tables `kendo`
  creates later. No `TRUNCATE`, `TRIGGER`, `REFERENCES` or `CREATE`.
- **No sliding back.** The app refuses to start when connected as a superuser,
  and the e2e tests run the server as the app user, so a missing grant fails in
  CI rather than tempting someone to point `DATABASE_URL` back at `kendo`.

## Considered Options

- **A third user owning the schema**, non-superuser, for migrations, leaving the
  superuser to backup and restore only. Rejected for now: the migration step is
  short-lived and on the backend network only, while moving ownership off the
  bootstrap superuser cannot be done with `REASSIGN OWNED` and means altering
  every object. The internet-facing app was the risk worth paying for.
- **Creating the app user in a `docker-entrypoint-initdb.d` script.** Rejected:
  it runs only on an empty volume, so existing volumes miss it and a password
  change becomes a manual `ALTER ROLE`.
- **Grants in an Alembic migration.** Rejected: the password is a secret and
  cannot live in the chain, so user creation would be split across two places.

Decided in issue #453.
