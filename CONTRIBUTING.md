# Contributing

Thanks for helping. The [contributing docs](docs/contributing/) cover the dev stack, the tests and the TDD workflow; this page is the branch
and pull request rules.

## Branches

- Branch from `develop` and open your pull request against `develop`. It is
  the integration branch, and the repository's default.
- Released code lives on `main` and its `v*` tags. Nothing is merged into `main`
  except a release or a hotfix, by the maintainer
  ([Releasing](docs/contributing/releasing.md)).
- Feature pull requests are squash-merged, so the pull request title becomes
  the commit on `develop`.

### What GitHub enforces

Repository rulesets (#553) back these rules. A push the rules refuse fails
with `GH013: Repository rule violations`.

| Ref | Rules | Who can bypass |
|---|---|---|
| `develop` | Changes land only through a pull request, merged by squash or merge commit. `Backend suite (pytest, no e2e)` and `Frontend checks (eslint, tsc, vitest)` must pass. No force push, no deletion. | nobody |
| `main` | Changes land only through a pull request, merged with a merge commit. The two checks above, plus `Full suite (pytest + Playwright)`, must pass. No force push, no deletion. | nobody |
| `release/*`, `hotfix/*` | Changes land through a pull request. No force push, no deletion. | the maintainer |
| `v*` tags | Only the maintainer creates, moves or deletes one. | the maintainer |

Every change, the maintainer's included, reaches `develop` or `main` as a
green pull request. No approval count is required: only accounts with write
access can merge, and a first-time contributor's fork PR runs its checks only
after the maintainer approves it.

## Pull request titles

Use a [Conventional Commits](https://www.conventionalcommits.org/) title:
`feat: …`, `fix: …`, `docs: …`, `chore: …`, and so on, with a scope if it
helps (`fix(auth): …`). Reference the issue in the body (`Closes #123`).

## Breaking changes

A **Breaking change** (see [`GLOSSARY.md`](GLOSSARY.md)) is one an operator
cannot take by the routine upgrade alone: it needs a manual step (a new
setting, secret or unit change), or its migration cannot be undone by returning
to the previous release image. The REST API is not part of this promise.

A pull request with a Breaking change needs all three of:

1. The `breaking` label.
2. A `!` in its title: `feat!: …` or `feat(auth)!: …`.
3. An **Operator action** section in its body: what an operator must do, on
   which deployment path (Compose, Quadlet or both), and what happens if they
   do not. The maintainer copies it into the upgrade notes at release.

A Breaking change bumps the Release line (`0.1` to `0.2`), so operators only
meet it when they change their pin on purpose. A renamed or removed setting
must make the upgrade stop with an error naming the old one, never run on
without it.

## Deployment files

Once installed, the deployment files are the operator's, and no upgrade step
overwrites them: the routine upgrade is back up, pull, restart
([Upgrading](docs/install/upgrading.md)). A change to one therefore reaches a
host only if the operator makes it.

So a pull request that changes any of `deploy/quadlet`, `deploy/systemd`,
`deploy/bin`, `docker-compose.yml`, `deploy/env`, `.env.example`,
`deploy/traefik` or `setup.sh` writes an **Operator action** section in its body, breaking
or not. Put it under a Compose heading, a Quadlet heading, or both, as each
applies. Say which file changed, what to change in the operator's copy, and
what happens if they do not. When the old file keeps working, say so: then
the change is not breaking. A new setting with a safe default in
`app/config.py` needs no action.

## Before you open the pull request

Run the full suite, not only the backend tests; see
[Running tests](docs/contributing/tests.md). CI runs the backend suite on every
pull request.

## Security issues

Do not open a public issue. See [SECURITY.md](SECURITY.md).
