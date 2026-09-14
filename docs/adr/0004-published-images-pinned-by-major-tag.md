# Deployments run a published image pinned by major tag

Tagged releases build the `prod` stage and push to GHCR as
`ghcr.io/booji/kendodojomanagement` with `1.0.0`, `1.0`, `1` and `latest`. Both
deployment paths reference that image — `docker-compose.yml` in place of
`build: .`, `deploy/quadlet/kendo-app.container` and `kendo-migrate.container`
in place of `localhost/kendodojo:latest` — and the documented pin for an
operator is the **major** tag, `:1`. The image also carries the deployment
bundle it needs — the compose file, the `.example` config, the Quadlet units,
the backup scripts and `setup.sh` — extracted with `podman run --rm <image>
init | tar -x`, so an operator never clones. Building from source stays
supported and becomes optional.

## Context

Every operator today must clone the repository and run `make build` before
anything starts. That is the single largest barrier to a stranger self-hosting
this: it requires a git checkout, a working build toolchain on the target host,
and several minutes of build time before the first line of the setup
instructions has any visible effect. The target operator for the quick
self-host is a technical hobbyist with a VPS and a domain — not someone who
wants to own a build.

A published image removes the toolchain and the build. It does not, on its
own, remove the clone: the app is only half of what a host needs, and the other
half is text — `docker-compose.yml`, `.env.example`, the Traefik `.example`
files, `deploy/quadlet/`, `deploy/bin/kendo-*.sh` and the `setup.sh` that writes
them. Publishing the image while leaving that config on the git side gives one
deployment two distribution channels on two version axes, and a checkout of
`main` against an image pinned `:1` is config from the tip driving an app from
`1.x`.

It also raises a question the build-on-host model never had to answer: what does
an operator write in their config, and what does upgrading mean?

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

The same question applies to the config, and the answers are not independent
of it — whatever carries the config has to track the same axis the image is
pinned on.

**Clone the release branch** (`git clone -b release/1.x`). Free in git, one line
of documentation. Rejected because it keeps the clone in the install for the
sake of 170 KB of text, and leaves the two axes merely *conventionally* aligned:
nothing stops a `:1` pin against a `main` checkout.

**A release tarball asset per tag.** Correct pinning, but a second artefact to
publish, sign and document alongside the image.

**`curl … | bash` bootstrap** that fetches the rest at a pinned ref. Removes the
clone, but adds bootstrap logic the project owns and a pipe-to-shell install.

**The image carries the bundle (chosen).** Podman is already the prerequisite
and `podman run` needs no compose file, so the image can hand over its own
config before anything is configured: a `COPY` into `/bundle` in the `prod`
stage and an `init` branch in `entrypoint.sh` that tars it to stdout. Install is
three commands and no git. Skew is closed by construction rather than by
convention — the bundle comes out of the image it configures, so `setup.sh`
writes that exact tag into `.env` rather than guessing, and there is one version
axis instead of two.

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

The image gains a second mode. `entrypoint.sh` has been deliberately narrow —
one `exec uvicorn`, with migrations kept out of it so a failed migration never
looks like an app crash — and `init` is the first argument it interprets.
It stays a tar to stdout and nothing more: it writes no files, needs no mounts,
and cannot be reached once the app is running.

The bundle becomes a shipped surface. Anything under `/bundle` is published to
operators at that tag, so the dev-only paths (`deploy/certs/`,
`deploy/traefik/dev/`) must stay out of it, and a config change now lands in a
release rather than the moment it merges. `setup.sh upgrade` re-extracts the
bundle and reports what changed instead of overwriting an operator's filled-in
files.
