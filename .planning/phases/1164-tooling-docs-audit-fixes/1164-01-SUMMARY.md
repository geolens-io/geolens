---
phase: 1164-tooling-docs-audit-fixes
plan: 01
subsystem: tooling-docs
tags: [docs, tooling, plugin-platform, audit-command, rename]
requires:
  - "Phases 1161/1162/1163 complete (maps.widgets->plugins, map-widgets/->map-plugins/, plugins i18n namespace)"
provides:
  - "docs/plugin-development.md (plugin authoring guide)"
  - ".claude/commands/plugin-audit.md (renamed + corrected deep audit command)"
  - "Updated /plugin-audit cross-references in map-audit.md and builder-audit.md"
affects:
  - ".claude/commands/map-audit.md"
  - ".claude/commands/builder-audit.md"
tech-stack:
  added: []
  patterns:
    - "Audit commands derive built-in plugin set from register-plugins.ts (registry is source of truth)"
key-files:
  created:
    - docs/plugin-development.md
    - .claude/commands/plugin-audit.md
  modified:
    - .claude/commands/map-audit.md
    - .claude/commands/builder-audit.md
  renamed:
    - ".claude/commands/widget-audit.md -> .claude/commands/plugin-audit.md (see decision note: not a git mv)"
decisions:
  - "TOOL-01 'rename' implemented as fresh-add + rm, NOT git mv. `.claude/` is gitignored and widget-audit.md was never git-tracked, so `git mv` failed ('not under version control'). Created plugin-audit.md via `git add -f` and removed the untracked widget-audit.md from disk with `rm`. Net effect (old file gone, new file present, same audit logic) is identical; git history is not carried because there was none to carry."
  - "map-audit.md saved-map field reads changed `widgets` -> `plugins` (lines 74/472-475/616/708). VERIFIED the backend field is ALREADY `plugins` (Phases 1161-1163 shipped the full DB/API/FE/i18n rename: models.py:87 `plugins:`, schemas.py:669, `enabled_plugins` in persistent_config.py:674, frontend types/api.ts:957/1035 `plugins?:`). The live API returns `plugins`, so the old `m.get('widgets')` reads were stale and would read a nonexistent key."
  - "Corrected plan `<interfaces>` drift: the store lives at frontend/src/stores/map-plugin-store.ts (NOT builder/state/), real __tests__ are registry.test.ts + plugin-availability.test.ts + PluginHost.test.tsx, the store test is at frontend/src/stores/__tests__/map-plugin-store.test.ts, and no WidgetHost.test.tsx leftover exists."
metrics:
  duration: ~40m
  completed: 2026-05-31
---

# Phase 1164 Plan 01: Plugin Tooling + Docs + Audit Fixes Summary

Created the plugin authoring guide (DOCS-01), renamed the `widget-audit` slash command to
`plugin-audit` with full plugin vocabulary (TOOL-01), and fixed the 3 audit review findings inside
the renamed command — dangling doc ref, missing read-list file, hardcoded built-ins (TOOL-04).
Docs/tooling only; no production app source touched.

## What Was Built

- **`docs/plugin-development.md`** (185 lines, DOCS-01) — a plugin authoring guide accurate to the
  post-1163 `map-plugins/` tree. Covers the registry (`registerPlugin`/`getPlugins`/`getPlugin`),
  built-in registration (`register-plugins.ts`), the `PluginDefinition` shape + `PluginContext`
  (from `types.ts`), availability gating (`getEnabledPluginDefinitions`/`isPluginIdAvailable`/
  `resolveAvailablePluginIds`/`getDefaultPluginIds`/`samePluginIds`), the host/panel contract
  (`PluginHost`/`PluginSidebar`/`usePartitionedPlugins`/`PluginPanel`/`PluginErrorBoundary`), the
  `usePluginStore` methods (`open`/`close`/`toggle`/`replace`), how to register a new plugin, and the
  `index.ts` barrel exports. Every symbol transcribed from live source.

- **`.claude/commands/plugin-audit.md`** (TOOL-01 + TOOL-04) — replaces `widget-audit.md`, rewritten
  in plugin vocabulary. Step-2 read list points only at real files (+ includes `plugin-availability.ts`);
  references `docs/plugin-development.md`; instructs deriving the built-in set from `register-plugins.ts`;
  output path `docs-internal/audits/plugin-audit-{YYYYMMDD}.md`; Step-6 rg patterns use
  `registerPlugin`/`map-plugins`/`enabled_plugins`.

- **Cross-refs** (TOOL-01) — `map-audit.md` (`register-widgets.ts` -> `register-plugins.ts`,
  "registered plugin IDs", `plugins` field reads, added `/plugin-audit` pointer) and `builder-audit.md`
  line 1132 (`/widget-audit` -> `/plugin-audit`, clean plugin vocabulary).

## Tasks Completed

| Task | Name | Commit | Files |
| --- | --- | --- | --- |
| 1 | Create plugin authoring guide (DOCS-01) | `1fd142ef` | docs/plugin-development.md |
| 2 | Rename widget-audit -> plugin-audit + 3 audit fixes (TOOL-01, TOOL-04) | `a1b4fc2d` | .claude/commands/plugin-audit.md (+ rm widget-audit.md) |
| 3 | Repoint map-audit cross-ref to /plugin-audit (TOOL-01) | `ec71e294` | .claude/commands/map-audit.md |
| 3b | Repoint builder-audit cross-ref to /plugin-audit (TOOL-01 fixup) | `4f9e1c33` | .claude/commands/builder-audit.md |

All on `main`. Task 3 split into two commits: `ec71e294` landed the map-audit.md edit, but the
builder-audit.md edit in that step had not actually applied (the Edit was in a tool batch that was
cancelled mid-flight). The post-commit self-check caught the stale `/widget-audit` line still in
builder-audit.md; the fixup commit `4f9e1c33` applied it correctly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `git mv` failed — `.claude/` is gitignored / untracked**
- **Found during:** Task 2
- **Issue:** The plan's `git mv .claude/commands/widget-audit.md .claude/commands/plugin-audit.md`
  returned exit 128 ("fatal: not under version control"). `.claude/` is in `.gitignore` and the
  command files are tracked only via `git add -f`; `widget-audit.md` had never been added, so there
  was nothing for `git mv` to move.
- **Fix:** Wrote `plugin-audit.md` directly and staged it with `git add -f`; removed the untracked
  `widget-audit.md` from disk with `rm` (NOT `git rm` — it was never tracked; NOT `git clean`).
- **Files:** .claude/commands/plugin-audit.md, .claude/commands/widget-audit.md (deleted)
- **Commit:** `a1b4fc2d`

**2. [Rule 1 - Bug] map-audit.md read stale `widgets` field — backend is already `plugins`**
- **Found during:** Task 3
- **Issue:** I first assumed the backend field was still `widgets` and that Plan 02 owned the
  DB/API rename, so I initially left the `m.get('widgets')` reads with a "renamed in v1036, check the
  live key" hedge. On verifying the source, the backend field is ALREADY `plugins` (Phase 1161
  shipped it: `models.py:87`, `schemas.py:669`, `enabled_plugins`; frontend `types/api.ts:957/1035`).
  The live API returns `plugins`, so the old reads were stale and would read a nonexistent key.
- **Fix:** Changed every `widgets` occurrence in `map-audit.md` to `plugins` (lines 74, 472-475, 616,
  708) and simplified the line-473 wording. Confirmed via ROADMAP that Plan 02 = TOOL-02/TOOL-03/DOCS-02
  only and does not touch `map-audit.md`, so this file is wholly Plan 01's.
- **Files:** .claude/commands/map-audit.md
- **Commit:** `ec71e294`

**3. [Rule 3 - Blocking] Plan `<interfaces>` store path / test list were stale**
- **Found during:** Task 1 / Task 2 (pre-write source verification)
- **Issue:** The plan specified the store at `frontend/src/components/builder/state/map-plugin-store.ts`
  (does not exist — real path `frontend/src/stores/map-plugin-store.ts`, per the `@/stores/map-plugin-store`
  imports), listed `map-plugins/__tests__/map-plugin-store.test.ts` and a `__tests__/WidgetHost.test.tsx`
  leftover (neither exists). Real `map-plugins/__tests__/` files are `registry.test.ts`,
  `plugin-availability.test.ts`, `PluginHost.test.tsx`; the store test is at
  `frontend/src/stores/__tests__/map-plugin-store.test.ts`.
- **Fix:** Used real paths in both the doc and the plugin-audit Step-2 list (all 15 read-list paths
  verified present on disk before commit).
- **Files:** docs/plugin-development.md, .claude/commands/plugin-audit.md
- **Commit:** `1fd142ef`, `a1b4fc2d`

**4. [Rule 1 - Bug] Doc draft named nonexistent store methods**
- **Found during:** Task 1 (symbol-accuracy self-check)
- **Issue:** First draft described the store with `setActivePlugins` + `reset(enabledPluginIds)`,
  which do not exist. The real store exposes `open`/`close`/`toggle`/`replace` over `activePlugins: Set<string>`.
- **Fix:** Rewrote the store section to the real methods; noted callers seed defaults by passing
  `getDefaultPluginIds(...)` to `replace(...)`. (Also removed literal `getAllPlugins` / `isPluginAvailable`
  "there is no X" mentions and a `PluginDefinition.ts` meta-mention that tripped the plan's `! grep` gate.)
- **Files:** docs/plugin-development.md
- **Commit:** `1fd142ef`

## docs/plugin-development.md symbol-accuracy check

All 20 symbols named in the doc were grep-verified to exist in `frontend/src/components/map-plugins/`
(+ `frontend/src/stores/map-plugin-store.ts`): `PluginDefinition`, `PluginContext`, `PluginAnchor`,
`PluginPlacement`, `registerPlugin`, `getPlugins`, `getPlugin`, `getEnabledPluginDefinitions`,
`isPluginIdAvailable`, `resolveAvailablePluginIds`, `getDefaultPluginIds`, `samePluginIds`,
`PluginHost`, `PluginSidebar`, `usePartitionedPlugins`, `PluginPanel`, `PluginErrorBoundary`,
`usePluginStore`, `MeasurementPlugin`, `LegendPlugin`. Negative check passed: no `getAllPlugins`,
`isPluginAvailable`, `PluginDefinition.ts`, or any `Widget*` symbol present.

## Found-but-Deferred (production-adjacent leftovers — OUT OF SCOPE for this docs/tooling plan)

These live in `frontend/src/` production code and were intentionally NOT touched (this plan makes no
app-source changes). Flagging for a later cleanup:

1. **Stale `Widget "${def.id}"` console.warn** at `frontend/src/components/map-plugins/registry.ts:8`
   — DEV-only duplicate-id warning still says "Widget".
2. **Stale `Widget "${this.props.pluginId}" crashed`** logger string at
   `frontend/src/components/map-plugins/PluginErrorBoundary.tsx:17`.
3. **`legend-widget-${idx}` layer-id string** at `frontend/src/components/map-plugins/builtin/LegendPlugin.tsx:169`
   — cosmetic internal maplibre layerId prop, not a registered plugin ID. Low risk.

Note: the plan's `<interfaces>` claimed a stale `__tests__/WidgetHost.test.tsx` exists — it does NOT
(verified via `ls`/`find`). No such leftover to defer.

## Concurrent-session handling (builder-audit.md contention)

A concurrent session (`builder-audit-fixes-20260530`) shares this working dir and edits
`.claude/commands/builder-audit.md`. Handling:
- Edited `map-audit.md` first (uncontended), then `builder-audit.md` last.
- Immediately before the builder-audit.md edit: fresh `grep -n 'widget-audit'` (found at line **1132**,
  matching the plan; the brief's 1190 was stale), `git status --short` (empty — no foreign WIP), and a
  merge-conflict-marker scan (none).
- The single-line Edit on builder-audit.md had to be applied twice: the first attempt was in a tool
  batch that got cancelled, so it silently did not land (the Task-3 commit `ec71e294` therefore only
  contained map-audit.md). The plan's post-write self-check caught this — a fresh grep showed line 1132
  still read `/widget-audit`. I re-grepped (still line 1132, no drift), re-confirmed no conflict
  markers and no foreign WIP, re-applied the exact single-line Edit, and committed it as `4f9e1c33`.
  Final state: builder-audit.md has 0 `widget-audit` / 1 `plugin-audit`, no conflict markers, no
  residual platform "widget" words on the cross-ref line. Never touched `builder-audit-*` branches;
  never did a blanket checkout/overwrite; stayed on `main` throughout.
- No concurrent-branch recovery was needed — HEAD never left `main` during this plan. The
  double-apply was a tool-batch-cancellation artifact, not a contention conflict with the concurrent
  session (the line text was byte-identical on both reads, and the concurrent session never had
  uncommitted edits to this file at any point I observed).

## Requirements Closed

- **DOCS-01** — `docs/plugin-development.md` created (185 lines, accurate to live source).
- **TOOL-01** — `widget-audit.md` removed, `plugin-audit.md` created; cross-refs in `map-audit.md`
  and `builder-audit.md` repointed to `/plugin-audit`.
- **TOOL-04** — all 3 review findings fixed inside `plugin-audit.md` (doc ref, read-list completeness
  incl. `plugin-availability.ts`, derive-built-ins-from-registry).

REQUIREMENTS.md checkboxes AND the `## Traceability` table rows flipped to Complete for DOCS-01,
TOOL-01, TOOL-04. **TOOL-02, TOOL-03, and DOCS-02 remain Pending — they are Plan 1164-02's scope.**
Phase 1164 is therefore partially complete after this plan (1 of 2 plans done).

## Verification

- DOCS-01 gate: `OK-DOCS01` — has PluginDefinition / register-plugins.ts / plugin-availability.ts /
  PluginErrorBoundary / getPlugins / measurement+legend; no `getAllPlugins`, no `PluginDefinition.ts`.
- TOOL-01 + TOOL-04 gate: `OK-TOOL01-04` — widget-audit.md gone, plugin-audit.md present, zero stale
  `map-widgets|register-widgets|widget-development|getWidgets|enabled-widgets|enabled_widgets` tokens,
  zero platform "widget" vocabulary (measurement/legend excepted). All 15 Step-2 read-list paths exist.
- Cross-refs gate: `CROSSREFS=OK` — map-audit.md (0 widget-audit / 1 plugin-audit, 0 'widget' tokens
  total), builder-audit.md (0 widget-audit / 1 plugin-audit, no conflict markers).
- ID literals preserved: `measurement`/`legend` intact in plugin-audit.md, the doc, and map-audit.md.
- No production code: only `.claude/commands/*` + `docs/*` changed since `063910fa`.
- All commits on `main`; HEAD never left `main`.

## Self-Check: PASSED

- `docs/plugin-development.md` — FOUND
- `.claude/commands/plugin-audit.md` — FOUND
- `.claude/commands/widget-audit.md` — confirmed GONE
- Commit `1fd142ef` — FOUND
- Commit `a1b4fc2d` — FOUND
- Commit `ec71e294` — FOUND
