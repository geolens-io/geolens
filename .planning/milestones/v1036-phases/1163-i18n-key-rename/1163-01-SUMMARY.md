---
phase: 1163-i18n-key-rename
plan: 01
subsystem: i18n
tags: [i18n, rename, widget-to-plugin, locale, parity]
requires: []
provides: ["plugin-namespaced-locale-keys"]
affects: ["i18n", "frontend"]
tech-stack:
  added: []
  patterns: ["loanword value-translation (swap only the widget-noun token, keep localized phrasing)"]
key-files:
  created:
    - .planning/phases/1163-i18n-key-rename/1163-01-SUMMARY.md
  modified:
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/en/admin.json
    - frontend/src/i18n/locales/es/admin.json
    - frontend/src/i18n/locales/fr/admin.json
    - frontend/src/i18n/locales/de/admin.json
decisions:
  - "Renamed all THREE distinct keys literally named `widgets` (mapStack.badges.widgets, tooltips.widgets, top-level widgets object) per the key-mapping table"
  - "KEY-only renames (pluginsEnabledCount, enablePlugin, disablePlugin) keep values byte-identical — no widget-word existed in those values"
  - "Plugin ID literals measurement/legend preserved as object keys with unchanged leaf values"
metrics:
  duration: ~35m
  completion-date: 2026-05-31
---

# Phase 1163 Plan 01: i18n Key Rename (Wave 1 — locale files) Summary

Renamed the ~64 `widget`-namespaced i18n keys to the `plugin` namespace across all 8 locale files (en/es/fr/de × builder.json/admin.json), translating user-visible values per-locale (Plugin/Plugins loanword for es/fr/de), with full 4-locale key parity preserved and the `measurement`/`legend` plugin ID literals untouched.

## What Was Built

The i18n locale surface now uses an honest `plugins.*` vocabulary consistent with the already-renamed backend (`maps.plugins`), API (`plugins`/`enabled_plugins`), and frontend identifiers (`Plugin*`, `map-plugins/`). All 16 widget-namespaced key paths (13 in each builder.json + 1 nested object spanning 3 grep lines in each admin.json) were renamed across the 4 locales. Zero `widget` substrings remain in the locale directory (verified `grep -rin widget frontend/src/i18n/locales/` = 0).

This is the **locale-file half of I18N-01**. It deliberately does NOT touch any `t()` call site — that is Plan 02 (Wave 2), which depends on these renamed keys existing first. After this wave alone the frontend will not render lookups correctly (call sites still reference old keys); that is expected and is why typecheck was NOT run as a Wave-1 gate.

## Key Implementation Details

- **Three keys named `widgets`** were disambiguated by parent path and all renamed: `mapStack.badges.widgets`→`plugins` (value `"{{count}} widget"`→`"{{count}} plugin"`), `tooltips.widgets`→`plugins` (value `"Widgets"`→`"Plugins"`), and the top-level `widgets` object→`plugins`.
- **Top-level object rename** changed only the object key + its `closeWidget`→`closePlugin` / `widgetError`→`pluginError` children. The `measurement` and `legend` sub-object keys and every leaf value under them (en Measure/Legend; es Medir/Leyenda; fr Mesurer/Légende; de Messen/Legende) are byte-identical — the milestone-wide plugin-ID invariant.
- **Value-translation rule**: only the widget-noun token was swapped inside the existing localized phrasing (e.g. es `"Controla si cada widget aparece en el mapa."`→`"...cada plugin..."`, de `"Steuert, ob jedes Widget auf der Karte erscheint."`→`"...jedes Plugin..."`). UTF-8 accents (`gestoßen`, `apparaît`, `encontró`) preserved.
- **KEY-only renames** (`widgetsEnabledCount`→`pluginsEnabledCount`, `enableWidget`→`enablePlugin`, `disableWidget`→`disablePlugin`) kept their values byte-identical because no widget-word appeared in them (`"{{count}} enabled"`, `"Enable {{name}}"`, localized forms `activados`/`activés`/`aktiviert`, `{{name}} aktivieren`).
- **Parity contract preserved**: builder namespace = 905 leaf keys, admin namespace = 534 leaf keys — identical key sets across all 4 locales (measured by flattening each namespace and diffing against en). The full `npm run test:i18n` parity gate runs in Plan 02 after call sites are repointed.
- Baseline line anchors in the plan (HEAD `e3c4c67c`) matched the current `main` (HEAD `203b7804`) exactly — no drift.

## Files

- `frontend/src/i18n/locales/{en,es,fr,de}/builder.json` — 13 key paths renamed per file (commit `896e2d66`)
- `frontend/src/i18n/locales/{en,es,fr,de}/admin.json` — `settings.widgets`→`settings.plugins` object (title + description) per file (commit `ea7a972b`)
- `.planning/phases/1163-i18n-key-rename/1163-01-SUMMARY.md` — this summary

## Requirement Status

**I18N-01 is PARTIALLY complete** — the locale-file half is done by this plan. The call-site (`t()`) repoint is Wave 2 (Plan 1163-02). Do NOT flip I18N-01 to fully complete until Plan 02 lands and the phase-level parity + typecheck + grep gate passes. I18N-01 is intentionally left unchecked in REQUIREMENTS.md.

## Deviations from Plan

None functional — plan executed exactly as written, all key-mapping items 1–14 applied, both `<automated>` verifies pass.

Process note (not a plan deviation): an early batch of edits to es/fr/de builder.json and all 4 admin.json failed the Read-before-Edit guard because those files had not yet been Read in this session; the en/builder.json edits in that batch succeeded. Additionally, the `mapStack.badges.widgets` edit's anchor line (`"copy": ...`) differed per-locale (`Copy`/`Copia`/`Copie`/`Kopie`) so the first attempt with the en text didn't match es/fr/de. Both were resolved by Reading each file's exact region first, then re-applying the edit with the correct per-locale anchor. No incorrect content was written and no commit captured a partial state — each task was fully verified (zero widget + key presence) before its commit.

## Concurrent-Branch Recovery

None required. The concurrent session (`builder-audit-fixes-20260530`) did not switch the branch out from under this work — `git branch --show-current` returned `main` before and after every commit. All commits (`896e2d66`, `ea7a972b`) are on `main`.

## How to Verify

```bash
# 1. All 8 files valid JSON
cd frontend && node -e "['en','es','fr','de'].forEach(l=>{for(const ns of ['builder','admin']){JSON.parse(require('fs').readFileSync(\`src/i18n/locales/\${l}/\${ns}.json\`,'utf8'));}});console.log('all 8 valid JSON')"

# 2. Zero widget across the locale dir (expect 0)
grep -rin "widget" frontend/src/i18n/locales/ | wc -l

# 3. Key-set parity (builder 770, admin 107 across en/es/fr/de) — full gate runs in Plan 02:
npm run test:i18n
```

## Self-Check: PASSED

- FOUND: all 8 locale files exist and parse as valid JSON
- FOUND: `grep -rin widget frontend/src/i18n/locales/` = 0 (per-file = 0 for all 8)
- FOUND: builder parity = 905 leaf keys identical across en/es/fr/de; admin parity = 534 leaf keys identical
- FOUND: commit `896e2d66` (builder.json ×4) on `main`
- FOUND: commit `ea7a972b` (admin.json ×4) on `main`
- FOUND: plugin ID literals `measurement`/`legend` preserved (leaf values unchanged per-locale)
