---
phase: 1044
plan: "01"
subsystem: i18n
tags: [i18n, localization, mapbuilder, parity-gate, POL-22]
dependency_graph:
  requires: []
  provides: [de/builder.json parity, es/builder.json parity, fr/builder.json parity]
  affects: [frontend/src/i18n/resources.test.ts]
tech_stack:
  added: []
  patterns: [i18next, JSON locale files]
key_files:
  created: []
  modified:
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - .planning/phases/1044-cross-cutting-closeout/1044-01-TRANSLATIONS.md
decisions:
  - German typographic quotation marks „" must use U+201E + U+201C (not ASCII " around {{name}}) to avoid JSON parse errors
  - German suggestions strings kept with proper Unicode typographic quotes already present in original file
metrics:
  duration: "~45 minutes"
  completed: "2026-05-15"
  tasks: 3
  files_modified: 3
---

# Phase 1044 Plan 01: i18n locale fill for de/es/fr (POL-22) Summary

**One-liner:** Native-language translations for all 56 missing v1.5 builder keys plus 30 English-passthrough replacements across de/es/fr, bringing all three locales to 770-key parity with en.

## What Was Done

### Keys Added Per Locale (~56 inserts each)
- **Group A (a11y.*):** 4 drag-from-catalog screen-reader announcement keys (dragPickup, dragPosition, dragDropped, dragCancelled)
- **Group B (basemapGroup/basemapSublayer):** railLabel, toggleExpand, casingColor, casingWidth, strokeColor, strokeWidth (6 keys)
- **Group C (layerEditor.source):** noColumns (1 key)
- **Group D (search.*):** 16 keys including dragHandle, retry, browseCatalogCta, basemap, inUse, anotherRendering, swap, importData, filters, previewAlt, previewUnavailable, allTypes, vector, raster, metadata.{type,source,count,crs,attribution}
- **Group E (settings.*):** 22 keys for the settings panel (regionLabel, panelTitle, closePanel, terrainLabel, widgetsLabel, projectionLabel, terrainActiveHint, terrainInactiveCollapsedHint, exaggeration, terrainExaggerationAria, boundTo, terrainInactiveHint, widgetsEnabledCount, noWidgets, widgetsGroupAria, disableAction, enableAction, toggleWidget, projectionMercator, projectionGlobe, projectionAria, globeDisclaimer)
- **Group F (toasts):** datasetAdded, basemapChanged (2 keys)
- **Group G (unifiedStack):** browseAllShort, emptyHelpBody (2 keys)

### English-Passthrough Values Replaced (~30 replacements each)
- **bulkActions block (22 keys):** selectedCount, toolbarLabel, liveAnnouncement, visibility, visibilityAriaLabel, opacity, opacityAriaLabel, group, groupAriaLabel, groupDisabledTooltip, ungroup, ungroupAriaLabel, ungroupDisabledTooltip, delete, deleteAriaLabel, deleteConfirmLabel, deleteConfirmAction, deleteConfirmCancel, errorUpdateRolledBack, errorDeleteRolledBack, selectRow, selectGroup
- **unifiedStack.listboxLabel (1 key)**
- **terrain block (7 keys):** enabled, source, sourcePlaceholder, exaggeration, noDem, unitsUnknown, unitsNonMeter

### Additional Fixes (deviation from plan scope — Rule 1 bugs)
- Fixed duplicate `unifiedStack` key in both de and fr (JSON had the block twice)
- Fixed entirely English blocks in de/fr for stackRow, basemapGroup, basemapSublayer, demEditor, folderGroup, layerEditor that were English passthrough
- Fixed `layerItem.backToLayers` which was "Back to layers" in all three locales
- Added `styleJson` full translation in de (was English passthrough in original)
- Added `history` block full translation in de/es/fr (was English passthrough)
- Added `dock` block full translation in de/es/fr (was English passthrough)
- Translated `chat.commands`, `chat.suggestions` remaining English stubs in de/es/fr
- Fixed `chat.undo`, `chat.undoApplied`, `chat.layersDropdown`, `chat.commandsDropdown`, `chat.mentionHint` English stubs in de/es/fr

## 5-Key Spot-Check (Native Translation Evidence)

| Key | DE | ES | FR |
|-----|----|----|-----|
| `bulkActions.delete` | Löschen | Eliminar | Supprimer |
| `bulkActions.deleteConfirmLabel` | {{count}} Layer löschen? Diese Aktion kann nicht rückgängig gemacht werden. | ¿Eliminar {{count}} capas? Esta acción no se puede deshacer. | Supprimer {{count}} couches ? Cette action est irréversible. |
| `a11y.dragPickup` | {{name}} aufgenommen. Pfeiltasten zum Wählen einer Position verwenden, Eingabe zum Ablegen, Escape zum Abbrechen. | Se tomó {{name}}. Use las teclas de flecha para elegir una posición, Intro para soltar, Escape para cancelar. | {{name}} saisi. Utilisez les flèches pour choisir une position, Entrée pour déposer, Échap pour annuler. |
| `settings.terrainInactiveHint` | Kein Terrain-Layer ist aktiv. Einen DEM-Layer in den Terrain-Modus wechseln, um die globale Terrain-Überhöhung zu aktivieren. | No hay ninguna capa de terreno activa. Cambie una capa DEM al modo Terreno para habilitar la exageración global del terreno. | Aucune couche de terrain n'est active. Basculez une couche DEM en mode Terrain pour activer l'exagération globale du terrain. |
| `toasts.datasetAdded` | {{name}} zur Karte hinzugefügt | {{name}} agregado al mapa | {{name}} ajouté à la carte |

All five keys confirm native-language values with no English passthrough.

## Parity Gate Result

- `npm run test:i18n` — 2 tests passed (ships every namespace + key parity)
- `npm run check:i18n:changed` — builder.json recognized as changed across all locales
- `npx tsc -b --noEmit` — 0 type errors
- `python3 -c "import json; [json.load(...)]"` — all four builder.json parse as valid JSON

Final key counts: en=770, de=770, es=770, fr=770 (exact parity).

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1+2 | Translation table + apply to locales | c48ddf3c | de/builder.json, es/builder.json, fr/builder.json |
| 3 | Verification (no files modified) | — | — |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed broader English-passthrough beyond plan scope**
- **Found during:** Task 2 — when writing complete corrected files, discovered that the original de/fr files had extensive English content in stackRow, basemapGroup, basemapSublayer, demEditor, folderGroup, layerEditor, styleJson, history, dock, chat.commands/suggestions/undo blocks in addition to the plan's specified blocks
- **Fix:** Translated all English-passthrough values found while rewriting the files
- **Files modified:** All three locale files
- **Commit:** c48ddf3c

**2. [Rule 1 - Bug] Fixed duplicate `unifiedStack` key in de/fr builder.json**
- **Found during:** Task 2 pre-flight — JSON had `unifiedStack` block appearing twice (once at ~line 750, once at ~line 774)
- **Fix:** Merged into single canonical block with all required keys
- **Files modified:** de/builder.json, fr/builder.json
- **Commit:** c48ddf3c

**3. [Rule 1 - Bug] Fixed German typographic quote JSON parse error**
- **Found during:** Task 2 verification — `„{{name}}"` strings broke JSON when the closing ASCII `"` terminated the string value prematurely
- **Fix:** Replaced with U+201C/U+201D Unicode typographic quotes that don't conflict with JSON string delimiters
- **Files modified:** de/builder.json
- **Commit:** c48ddf3c

## Pattern Lessons for v1010+

1. **Ship native translations alongside English** when introducing new keys — do not commit English-placeholder values in non-English locale files. The i18n debt accumulated across v1008/v1009 required ~86 translations across 3 locales in a single catch-up plan.
2. **Validate locale files structurally at PR time** — a pre-commit hook or CI step running `python3 -c "import json; json.load(...)"` + `vitest run src/i18n/resources.test.ts` would catch English passthroughs and parity violations before they accumulate.
3. **German typographic quotes „"** in JSON values are safe only when the closing character is U+201C (LEFT DOUBLE QUOTATION MARK, `“`), not ASCII `"` (U+0022). Use a linter or the resources.test.ts suite to catch JSON parse failures.
4. **Duplicate JSON keys** are silently allowed by most parsers (last value wins) but break parity tests — always validate JSON with strict parsers before committing.

## Known Stubs

None — all translated values are complete native-language strings. No English passthrough remains in de/es/fr builder.json.

## Self-Check: PASSED

- `frontend/src/i18n/locales/de/builder.json` FOUND (770 keys, JSON valid)
- `frontend/src/i18n/locales/es/builder.json` FOUND (770 keys, JSON valid)
- `frontend/src/i18n/locales/fr/builder.json` FOUND (770 keys, JSON valid)
- Commit c48ddf3c FOUND in git log
- `npm run test:i18n` passes with 2 tests
