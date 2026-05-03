---
phase: 228-run-cold-publish-workflows
plan: 04
status: complete
subsystem: release
tags: [verification, docs, pypi, npm, docker-smoke]

requires:
  - phase: 228-run-cold-publish-workflows
    plan: 03
    provides: published PyPI and npm artifacts
provides:
  - verify-published.yml clean-machine smoke run passed
  - npm verifier fixed to install from a temporary project directory
  - Phase 228 consolidated verification artifact
  - docs and changelog aligned with final package names
affects: [release-publish, homebrew-follow-up]

tech-stack:
  added: []
  patterns:
    - "Clean-machine package verification in python:3.13-slim and node:22-slim"
    - "npm smoke test runs from /tmp project to avoid root-directory npm state errors"

key-files:
  created:
    - .planning/phases/228-run-cold-publish-workflows/228-04-SUMMARY.md
    - .planning/phases/228-run-cold-publish-workflows/228-VERIFICATION.md
  modified:
    - .github/workflows/verify-published.yml
    - docs/sdks.md
    - docs/cli.md
    - CHANGELOG.md
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
    - .planning/STATE.md

requirements-completed:
  - PUBLISH-04

completed: 2026-05-03
---

# Phase 228 Plan 04: Published Package Verification Summary

**Clean-machine verification passed for all published package surfaces.**

## Verification Runs

| Workflow | Run | Result | Notes |
|---|---:|---|---|
| Verify Published Packages | [25266829097](https://github.com/geolens-io/geolens/actions/runs/25266829097) | failed | Python passed; TypeScript hit npm `Tracker "idealTree" already exists` from running in container root |
| Verify Published Packages | [25266870449](https://github.com/geolens-io/geolens/actions/runs/25266870449) | success | Python and TypeScript clean-machine jobs passed |

## Fix Applied

Commit `424ebdc3` changed `.github/workflows/verify-published.yml` so the TypeScript job creates `/tmp/geolens-sdk-smoke`, runs `npm init -y`, installs `@geolens/sdk`, and asserts `createGeolensClient` is a function.

Manual Docker smoke passed before the workflow rerun:

```text
npm install --no-save @geolens/sdk
createGeolensClient export ok
```

The final verifier run proved:

- `pip install --no-cache-dir geolens geolens-cli`
- `geolens --version`
- `from geolens import GeolensClient`
- `npm install --no-save @geolens/sdk`
- `createGeolensClient` runtime export

## Documentation Alignment

The public docs now use the final package names:

- SDK docs: Python SDK is `geolens`; TypeScript SDK is `@geolens/sdk`.
- CLI docs: PyPI distribution is `geolens-cli`; executable remains `geolens`.
- Changelog: pending-publish language removed for SDK and CLI entries.
- Planning requirements and roadmap: PUBLISH-02..04 now reference `geolens`, `geolens-cli`, and `@geolens/sdk`.

## Remaining Manual Account Cleanup

PyPI does not expose the account-side pending-publisher cleanup through the local repo. Remove the stale pending publisher for `geolens-sdk` from the PyPI account UI. No live `geolens-sdk` package exists on PyPI.
