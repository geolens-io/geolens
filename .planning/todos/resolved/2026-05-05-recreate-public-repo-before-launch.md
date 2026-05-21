---
created: 2026-05-05T17:34:52.587Z
resolved: 2026-05-21T11:40:00.000Z
resolved_during: v1016
resolution: stale
title: Recreate public repo before launch
area: general
files:
  - README.md
  - README.es.md
  - README.fr.md
  - README.de.md
  - .github/workflows/verify-published.yml
  - .github/workflows/publish-sdks.yml
---

## Resolution (2026-05-21, v1016)

Moot — `1.0.0` shipped publicly on 2026-04-01 from the existing `geolens-io/geolens`
repository. The "before launch" framing assumed a pre-launch decision window that
has now closed. PyPI / npm / GHCR all expose `1.0.0` against this repo; recreating
it would orphan those artifacts.

The residual baggage concern (pre-public tags, tracked planning files in history,
workflow logs) is still real but no longer a clean-slate option. If GitHub housekeeping
is desired later, the targeted remedy is a separate "history audit" deliberation
(squash old planning commits, prune workflow logs, etc.), not full-repo recreation.

## Problem

Before making GeoLens public, decide whether to recreate the GitHub repository as a true clean-slate public launch repo instead of relying on cleanup commits or force-pushed history. The current private repo had pre-public tags, tracked planning files in history, workflow logs, release metadata, and internal branch history. These are mostly cleaned from the current refs, but a new repository would avoid residual GitHub baggage and make the first public impression easier to reason about.

## Solution

Recommended launch path:

1. Rename or archive the current private repository as the internal archive.
2. Create a fresh `geolens-io/geolens` repository for public launch.
3. Push a sanitized tree as a fresh initial public commit or a short clean release history.
4. Publish corrected artifacts under the next public patch version, likely `v1.0.3`, because PyPI/npm already expose `1.0.0` and cannot be republished.
5. Recreate public repo settings: description, homepage, topics, social preview, branch protection/rulesets, Actions secrets, PyPI trusted publishing, npm token, GHCR package visibility, seeded issues, and seeded discussions.
