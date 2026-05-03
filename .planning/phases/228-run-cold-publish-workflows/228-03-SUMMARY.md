---
phase: 228-run-cold-publish-workflows
plan: 03
status: complete
subsystem: release
tags: [pypi, npm, trusted-publishing, github-actions, live-publish]

requires:
  - phase: 228-run-cold-publish-workflows
    plan: 02
    provides: release credentials and PyPI Trusted Publishers configured
provides:
  - geolens 1.0.0 published to PyPI as the Python SDK
  - geolens-cli 1.0.0 published to PyPI as the CLI distribution
  - "@geolens/sdk 1.0.0 verified on npm"
  - live publish workflow run URLs for SDK and CLI artifacts
affects: [228-04, release-publish, docs-publishing]

tech-stack:
  added: []
  patterns:
    - "Dry-run-first release cadence before immutable registry writes"
    - "PyPI Trusted Publishing through GitHub Actions OIDC"
    - "Package-name pivot: Python SDK uses geolens; CLI distribution uses geolens-cli"

key-files:
  created:
    - .planning/phases/228-run-cold-publish-workflows/228-03-SUMMARY.md
  modified: []

key-decisions:
  - "Publish the Python SDK as `geolens` on PyPI."
  - "Publish the CLI as `geolens-cli` on PyPI while preserving the executable name `geolens`."
  - "Keep the TypeScript SDK as `@geolens/sdk` on npm."
  - "Do not publish or keep using `geolens-sdk`; the stale pending-publisher entry should be removed from PyPI account settings."

requirements-completed:
  - PUBLISH-02
  - PUBLISH-03

completed: 2026-05-03
---

# Phase 228 Plan 03: Hot Publish Triggers Summary

**The live package publish is complete.** The public install names are:

- Python SDK: `pip install geolens`
- CLI: `pip install geolens-cli` then run `geolens`
- TypeScript SDK: `npm install @geolens/sdk`

## Workflow Runs

| Workflow | Purpose | Run | Result |
|---|---|---:|---|
| Publish SDKs | Dry-run validation | [25266579270](https://github.com/geolens-io/geolens/actions/runs/25266579270) | success |
| Publish SDKs | First live attempt | [25266623747](https://github.com/geolens-io/geolens/actions/runs/25266623747) | failed before upload |
| Publish SDKs | Live Python SDK publish | [25266789877](https://github.com/geolens-io/geolens/actions/runs/25266789877) | success |
| Publish CLI | Dry-run validation | [25266579277](https://github.com/geolens-io/geolens/actions/runs/25266579277) | success |
| Publish CLI | Live CLI publish | [25266798787](https://github.com/geolens-io/geolens/actions/runs/25266798787) | success |

## Registry Confirmation

```text
$ python -m pip index versions geolens
geolens (1.0.0)
Available versions: 1.0.0, 0.0.0

$ python -m pip index versions geolens-cli
geolens-cli (1.0.0)
Available versions: 1.0.0

$ npm view @geolens/sdk version --json
"1.0.0"
```

`@geolens/sdk@1.0.0` was already present when the final live Python SDK publish ran, so it was verified rather than re-published. npm versions are immutable; a duplicate publish of `1.0.0` would fail.

## Issues Encountered

The first live SDK run failed with:

```text
403 Invalid API Token: OIDC scoped token is not valid for project 'geolens'
```

Root cause: the PyPI Trusted Publisher setup still reflected the pre-pivot `geolens-sdk` path. The fix was to align PyPI project publishers with the final names:

- `geolens`: workflow `publish-sdks.yml`
- `geolens-cli`: workflow `publish-cli.yml`

After the publisher alignment, `publish-sdks.yml` successfully published `geolens==1.0.0`.

## Follow-Up Cleanup

`geolens-sdk` is not a live PyPI package:

```text
$ python -m pip index versions geolens-sdk
ERROR: No matching distribution found for geolens-sdk
```

The remaining cleanup is account-side only: remove the stale `geolens-sdk` pending publisher entry from PyPI account settings.
