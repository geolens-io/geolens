---
phase: 1053-quickstart-docs-environment-hardening
plan: "03"
subsystem: docs-cross-repo
tags: [docs, quickstart, api-key, prerequisites, install-sh]
dependency_graph:
  requires: [1053-02]
  provides: [DOC-02, DOC-03, DOC-05]
  affects: [~/Code/getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx]
tech_stack:
  added: []
  patterns: []
key_files:
  created: []
  modified:
    - ~/Code/getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx
decisions:
  - "DOC-02 resolved docs-only (no script change to seed-ago-data.py) per CONTEXT.md locked decision"
  - "DOC-05 Aside documents priority order: env var first, then TTY prompt, then default — matching actual install.sh prompt_value() logic"
  - "DOC-05 final-fallback language updated from 'refuses to start' to 'uses defaults' to accurately reflect prompt_value() behavior (falls back to 'admin'/'admin' defaults, not an error)"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-19T21:13:05Z"
  tasks_completed: 4
  files_changed: 1
---

# Phase 1053 Plan 03: API-key creation + Python/httpx prereqs + install.sh credential prompt Summary

DOC-02 + DOC-03 + DOC-05 closed via cross-repo commit `30e9361` to `~/Code/getgeolens.com/` — adds API-key 5-step recipe, seeder-scoped Python/httpx prerequisites, and an Aside documenting install.sh's interactive vs unattended credential modes.

## Cross-Repo Commit

**Repository:** `~/Code/getgeolens.com`
**Commit SHA:** `30e9361` (full: `30e93618906d218658ead65a4df32deadcf24988`)
**Branch:** `main`
**Not pushed.**

Commit sequence in sibling repo:
```
30e9361 docs(quickstart): document API-key creation, Python/httpx prereqs, install.sh credential prompt (DOC-02, DOC-03, DOC-05)
d50b9ec docs(quickstart): add Seed sample data section, demote demo overlay (DOC-01, EW-01)
```

Plan 02 (`d50b9ec`) landed first; Plan 03 (`30e9361`) extends it — exactly as sequenced.

## Anchor Resolution

The `#create-your-first-api-key` anchor that Plan 02 added as a forward reference in the "Seed live ArcGIS Online data" subsection now resolves correctly. Astro Starlight derives anchor slugs from heading text: `### Create your first API key` → `#create-your-first-api-key`. The subsection is positioned immediately after the "Seed live ArcGIS Online data" block (within the same `## 4. Seed sample data` section), so clicking the Plan 02 link scrolls to it inline.

## What Was Built

### Task 1 — DOC-03: Seeder prerequisites subsection

Replaced the one-line stub ("Both seeders need Python 3.10+ and `httpx`...") with a `### Seeder prerequisites` subsection at the top of `## 4. Seed sample data`. Content:
- Python 3.10 or newer (with `python --version` check hint)
- `httpx` with `pip install httpx` install command
- Note that seeders run on the host, not inside docker network, with `--base-url` override option

Top-level `## Prerequisites` table is unchanged — no Python row added there.

### Task 2 — DOC-02: Create your first API key subsection

Added `### Create your first API key` subsection after the "Seed live ArcGIS Online data" block. Contains:
- 5-step numbered recipe: sign in → gear icon → API Keys tab → Create Key → copy immediately
- One-shot display caveat ("shown once in a confirmation modal")
- Both `GEOLENS_API_KEY` env var (Option A) and `--api-key` flag (Option B) usage patterns
- Tip Aside explaining admin-user key inherits admin permissions (relevant for ingestion)

No changes to `scripts/seed-ago-data.py` (docs-only path per CONTEXT.md locked decision).

### Task 3 — DOC-05: install.sh interactive vs unattended Aside

Replaced the "For unattended installs, set..." paragraph with a structured `<Aside type="note">` block explaining both modes:
- Interactive (default): TTY prompt via `/dev/tty`, defaults accepted on Enter
- Unattended: env vars (`GEOLENS_ADMIN_USERNAME` / `GEOLENS_ADMIN_PASSWORD`) read when no TTY, with runnable example using `openssl rand -base64 16`
- Final-fallback note: when neither env vars nor TTY prompt provide values, defaults (`admin`/`admin`) are used

The idempotency note ("Re-running the script is idempotent — existing `.env` values are preserved") was merged into the preceding paragraph.

## Deviations from Plan

### Auto-fixed: DOC-05 fallback language accuracy

**Rule 1 (Bug — inaccurate documentation)**
- **Found during:** Task 3 implementation after reading `scripts/install.sh` `prompt_value()` function
- **Issue:** The plan's Aside draft said "If neither the env vars NOR the TTY prompt provide values, the application refuses to start at first boot (the empty-string guard from Phase 273 SEC-15)." This is inaccurate: `prompt_value()` always falls back to the `$default` argument (`admin`/`admin`) when neither env var nor TTY yields a value. The app does NOT refuse to start — it starts with the default credentials.
- **Fix:** Changed the final-fallback sentence to: "If neither the env vars NOR the TTY prompt provide values, the defaults (`admin`/`admin`) are used and the application starts normally — rotate the password immediately after first login."
- **Files modified:** `~/Code/getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx`
- **Commit:** `30e9361`

Note: The "SEC-15 empty-string guard" mentioned in the plan applies to the _existing_ `.env` values that ship empty — the `Manual install` Aside (already present from Plan 02) correctly documents that case. The install.sh interactive flow is separate.

## Requirements Closed

- **DOC-02:** API-key creation recipe (5-step UX-01 trace) documented inline with `seed-ago-data.py`. Docs-only path confirmed.
- **DOC-03:** Python 3.10+ and `httpx` documented in seeder-scoped `### Seeder prerequisites` subsection. Top-level prereqs unchanged.
- **DOC-05:** `install.sh` interactive credential prompt (TTY mechanic + defaults) and env-var fallback (`GEOLENS_ADMIN_USERNAME` / `GEOLENS_ADMIN_PASSWORD`) both documented with runnable example.

## Self-Check: PASSED

- [x] Modified file exists: `~/Code/getgeolens.com/docs/src/content/docs/guides/quickstart/index.mdx`
- [x] Sibling-repo commit `30e9361` exists and is HEAD on `main`
- [x] Plan 02 commit `d50b9ec` is the parent commit
- [x] Anchor `#create-your-first-api-key` resolves — heading slug matches Plan 02 forward reference
- [x] `grep -q "Python 3.10"` passes
- [x] `grep -q "pip install httpx"` passes
- [x] `grep -q "Create your first API key"` passes
- [x] `grep -q "GEOLENS_API_KEY"` passes
- [x] `grep -q "Interactive"` passes
- [x] `grep -q "GEOLENS_ADMIN_USERNAME"` passes
- [x] Python NOT in top-level `## Prerequisites` table
- [x] No push to remote
