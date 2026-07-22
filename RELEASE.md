# Release manifest

This document records how a GeoLens release stays coherent: one authoritative
version number, and the set of surfaces that must agree on it. It describes the
mechanics that already exist in the repo — it is not a roadmap or a commitment
to a schedule.

## The authoritative version

The canonical version is **`backend/pyproject.toml` `[project].version`**. Every
other surface derives from it. A release is the act of stamping that single
version across the surfaces below and publishing them together.

## Surfaces that must match

A release at version `X.Y.Z` is coherent when all of these agree:

1. **Git tag + GitHub Release** — tag `vX.Y.Z` and the GitHub Release built from
   the matching `CHANGELOG.md` section.
2. **GHCR images** — `geolens-api`, the worker (built from the same API image),
   and `geolens-frontend`, all tagged `X.Y.Z`.
3. **PyPI packages** — `geolens` (`sdks/python/pyproject.toml`) and
   `geolens-cli` (`cli/pyproject.toml`).
4. **npm package** — `@geolens/sdk` (`sdks/typescript/package.json`).
5. **OpenAPI + generated SDKs** — `backend/openapi.json` `info.version`, the
   generated Python SDK (`sdks/python/pyproject.toml`,
   `sdks/python/.openapi-python-client.yaml`), and the generated TypeScript SDK.
6. **CHANGELOG + docs** — a `## [X.Y.Z]` section in `CHANGELOG.md` and any
   version references in the docs.
7. **Installer default** — `scripts/install.sh` resolves the highest published
   release tag and writes it to `GEOLENS_VERSION`, so a fresh install pulls the
   `X.Y.Z` images by default.
8. **Demo build** — the public demo VM is pinned to a released image tag.
9. **Helm chart** — the community chart in
   [geolens-deployments](https://github.com/geolens-io/geolens-deployments)
   defaults its `appVersion` / image tags to `X.Y.Z`. It lives in a sibling
   repository, so it trails the tag by one manual bump PR rather than being
   enforced by this repo's CI.

## Gates that enforce coherence

These run in CI and do not require manual checking:

- **Source coherence** — `make version-check` (which runs
  `scripts/check_version_coherence.py`) asserts that every in-tree version site
  agrees with the canonical `backend/pyproject.toml` version. The companion
  writer, `scripts/bump_version.py`, enumerates the same set of sites.
- **Published coherence** — `.github/workflows/verify-published.yml` runs after
  a release and confirms, in a clean container, that PyPI `geolens` +
  `geolens-cli`, npm `@geolens/sdk`, the GHCR images, and the GitHub Release are
  all present at the tagged version (with bounded retry for registry lag).

## Cutting a release

A release is triggered by pushing the `vX.Y.Z` tag at a merged, version-bumped
commit:

1. Merge a release-prep change that bumps the canonical version, adds the
   `## [X.Y.Z]` CHANGELOG section, and regenerates OpenAPI + SDKs. Wait for green
   CI (`make version-check` is part of it).
2. Tag the merge commit `vX.Y.Z`. The tag auto-builds the GitHub Release and the
   GHCR images, and triggers the PyPI/npm publishes.
3. SDK and CLI publishes pause for one-click approval before they ship; image
   and release builds do not.
4. `verify-published.yml` runs after the publishes complete and confirms every
   surface matches.

The maintainer owns the tag cut and the publish approval. This document does not
auto-publish or announce anything.

## Release notes and credits

`CHANGELOG.md` is the source of truth for release notes: the release workflow
extracts the `## [X.Y.Z]` section verbatim as the GitHub Release body. Entries
are written for operators — what changed and why it matters — not as a PR list.

Credits:

- A change contributed from outside the maintainer team is credited in its
  CHANGELOG entry: `(thanks @user, #123)`.
- The release workflow appends GitHub's auto-generated **New Contributors**
  section and the **Full Changelog** compare link below the curated notes.
- Security reporters are credited in the release notes of the fix, per the
  [security policy](.github/SECURITY.md), unless they prefer anonymity.

## Hotfixes and backports

Only the latest release line is patched (see the
[security policy](.github/SECURITY.md)), and fixes normally ship from `main` as
the next `X.Y.(Z+1)`. There are no standing release branches. If `main` has
moved past what should ship — unreleased breaking work on top of the current
release — and that release needs an urgent fix:

1. Cut `release/X.Y` from the existing `vX.Y.Z` tag.
2. Cherry-pick the fix commit(s) onto it.
3. Run the release-prep step there (version bump + CHANGELOG section) and tag
   `vX.Y.(Z+1)` from that branch — the tag pipeline behaves identically.
4. Delete the branch after the release. Release branches are on-demand and
   short-lived, never maintained in parallel.
