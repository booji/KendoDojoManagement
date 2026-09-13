# Deployments run a published image pinned by major tag

Tagged releases build the `prod` stage and push to GHCR as
`ghcr.io/booji/kendodojomanagement` with `1.0.0`, `1.0`, `1` and `latest`. Both
deployment paths reference that image — `docker-compose.yml` in place of
`build: .`, `deploy/quadlet/kendo-app.container` and `kendo-migrate.container`
in place of `localhost/kendodojo:latest` — and the documented pin for an
operator is the **major** tag, `:1`. Building from source stays supported and
becomes optional.

## Context

Every operator today must clone the repository and run `make build` before
anything starts. That is the single largest barrier to a stranger self-hosting
this: it requires a git checkout, a working build toolchain on the target host,
and several minutes of build time before the first line of the setup
instructions has any visible effect. The target operator for the quick
self-host is a technical hobbyist with a VPS and a domain — not someone who
wants to own a build.

A published image removes the clone, the toolchain and the build. It also
raises a question the build-on-host model never had to answer: what does an
operator write in their config, and what does upgrading mean?

Alembic is the real compatibility surface. The `migrate` service runs
`alembic upgrade head` against the operator's live database, unattended, before
`app` starts. An operator who pulls a new image is consenting to a schema
change whether or not they realise it, and the only true rollback for a
migration they did not want is a restore from backup. So the tag an operator
pins is not a cosmetic preference — it is the promise the project makes about
when their database will change shape under them.

## Considered options

**`:latest` only.** Simplest to publish and simplest to document. Rejected
because `pull && up -d` then drags the operator across any migration at all,
including a breaking one, with no way to express "I want fixes but not a schema
rewrite". The failure mode is silent and lands on the least experienced
operators hardest.

**Date tags (`:2026-09-13`).** Unambiguous and trivially ordered, but a date
carries no compatibility information. `:2026-09-13` to `:2026-10-01` tells the
operator nothing about whether their data survives, so it solves publishing
without solving the question publishing raises.

**Semver, pinned by major (chosen).** `:1` means "fixes and features, no
migration that requires a restore". Moving to `:2` is an explicit edit the
operator makes, at a time of their choosing, having read the release notes.
The narrower pins (`:1.0`, `:1.0.0`) remain available for operators who want
them, and `:latest` remains for anyone who genuinely wants the tip. Versioned
documentation follows the same axis: an operator on `:1` reads the `1.x` docs.

## Consequences

Cutting a major version becomes a real commitment rather than a number. Any
migration that cannot be rolled back by re-pointing at the previous image must
land in a new major, and the release notes for it have to say what an operator
must do. That discipline is the point — it is what makes `:1` worth pinning —
but it is a constraint on the migration chain that did not exist while every
deployment built from source.

GHCR images from a private repository are not anonymously pullable and count
against the account's package quota. The documented `podman-compose pull` path
therefore cannot be exercised as a stranger experiences it until the repository
is public; until then the workflow is proved by pulling with a token.

`localhost/kendodojo:latest` remains buildable and is still what a contributor
runs. Nothing here removes the build — it stops being mandatory.
