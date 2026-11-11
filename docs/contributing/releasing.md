# Releasing

Maintainer steps. The decisions behind them are
[ADR-0004](../adr/0004-published-images-pinned-by-major-tag.md) and
[ADR-0009](../adr/0009-pre-1-0-releases-pin-by-minor.md); the contributor side
is [`CONTRIBUTING.md`](https://github.com/booji/KendoDojoManagement/blob/develop/CONTRIBUTING.md).

The branches follow git-flow:

| Branch | Holds | Merges into |
|--------|-------|-------------|
| `develop` | the next release; the default branch. Feature PRs are squash-merged here. | — |
| `release/X.Y.Z` | one release being prepared, cut from `develop`; carries the rc tags | `main`, by merge commit |
| `hotfix/X.Y.Z` | an urgent fix, cut from `main` | `main`, by merge commit |
| `main` | released code only; every release tag is on it | `develop`, after each release |

Release when ready; a hotfix goes out at once.

## Pick the version

List what `develop` has that `main` does not, and look for the `breaking`
label:

```bash
git fetch origin
git log --oneline origin/main..origin/develop
gh pr list --base develop --state merged --label breaking --search "merged:>=$(git log -1 --format=%cs origin/main)"
```

- Any merged PR labelled `breaking` → bump **Y** and reset the patch:
  `0.1.4` → `0.2.0`. This starts a new Release line.
- Otherwise, features and fixes alike → bump the patch **Z**: `0.1.4` → `0.1.5`.

From 1.0 the same rule bumps the major instead of Y.

## Cut the release branch

```bash
git switch -c release/X.Y.Z origin/develop
```

**On a new Release line only**, move the deployment bundle and the operator
docs to its pin in this branch, so the image and the docs published for the
line show it. Start with `RELEASE_PIN` in `backend/tests/deploy_contract.py`,
then list every mention of the old pin (here `0.1`) and update each, along with
the next line the comments name as the one to move to:

```bash
git grep -n -e ':0\.1\b' -e '0\.1\.x' -- README.md docs mkdocs.yml \
  setup.sh entrypoint.sh docker-compose.yml .env.example deploy
```

The backend tests then fail on any shipped file or page that still names a
different image pin, and the release workflow refuses to push a release tag
whose pin the bundle and the docs do not name.

Then write the upgrade notes. In [Upgrading](../install/upgrading.md), add an
"Upgrading to X.Y" section and copy into it the **Operator action** section of
every `breaking` PR in the release, under Compose and Quadlet headings as each
applies. Replace the "None yet" line on the first one. A patch release needs no
upgrading section.

Commit those to the release branch and push it.

## Rehearse a release candidate

Tag the release branch and push the tag:

```bash
git tag -a vX.Y.Z-rc1 -m vX.Y.Z-rc1
git push origin vX.Y.Z-rc1
```

An rc tag runs the full suite (`tests.yml`) and publishes an image under its
exact tag only, never the moving tags operators pin, and its docs publish
nowhere.

The GHCR package must be public, or every operator's anonymous pull fails
with `unauthorized`. A package is created private on its first push, and
GitHub has no API to change that: if the package was ever recreated, make it
public under its **Package settings**. Check with an anonymous pull before
rehearsing, from the clean host (never logged in to `ghcr.io`):

```bash
podman pull ghcr.io/booji/kendodojomanagement:$RC_TAG   # e.g. RC_TAG=X.Y.Z-rc1
```

Rehearse on a clean host: install from the rc image with
[Quick self-host](../install/quick-self-host.md), and upgrade a host running the
previous release to it by following your own upgrading notes. A fix found
here goes on the release branch, and the next rc is `-rc2`.

## Release

1. Open a PR from `release/X.Y.Z` into `main`. Merge it with a **merge commit**,
   not a squash: `main` must contain the commits `develop` already has, or the
   back-merge conflicts.
2. Tag the merge commit on `main` and push the tag:

    ```bash
    git fetch origin && git switch main && git merge --ff-only origin/main
    git tag -a vX.Y.Z -m vX.Y.Z
    git push origin vX.Y.Z
    ```

    The tag publishes the image as `X.Y.Z`, `X.Y` and `latest`, plus `X` from
    1.0 on, and the docs for its Release line: `0.Y.x` before 1.0, `X.x`
    after.

3. Publish the GitHub release from the tag with generated notes; they are
   grouped by label, `breaking` first. On a new Release line, check the
   operator actions are there and link the upgrading section.
4. Merge `main` back into `develop` with a PR (merge commit), so the release
   branch's commits reach `develop`.
5. Delete `release/X.Y.Z`.

## Hotfix

A fix that cannot wait for `develop`, usually a security fix:

1. `git switch -c hotfix/X.Y.Z origin/main`, with Z one above the latest
   release.
2. Fix it there and open a PR into `main`. The PR runs the full suite;
   rehearse an rc as above if there is time.
3. Merge with a merge commit, tag `vX.Y.Z` on `main`, and publish the release
   exactly as in [Release](#release), back-merge into `develop` included.

A security fix that has to break ships as a patch all the same, with its
operator action under a **Security** heading in the release notes and in
Upgrading; see [`SECURITY.md`](https://github.com/booji/KendoDojoManagement/blob/develop/SECURITY.md).
