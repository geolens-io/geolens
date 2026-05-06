#!/usr/bin/env bash
# validate-v13-8.sh — Run all six v13.8 phase VALIDATION.md files end-to-end.
# Authored by v13.9 Phase 253 Plan 03; closes VALID-07 from REQUIREMENTS.md.
#
# Usage:   bash scripts/validate-v13-8.sh
# Or via:  make validate-v13-8
#
# Exit codes:
#   0 — all 33+ checks across Phases 246..251 pass
#   1 — a check failed (fail-fast: prints which Phase + Requirement ID)
#   2 — infrastructure prerequisite missing (e.g., API container down)
set -euo pipefail

# -----------------------------------------------------------------------------
# Color helpers (only when stdout is a TTY and NO_COLOR is unset)
# -----------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_GREEN=$'\033[32m'
  C_RED=$'\033[31m'
  C_YELLOW=$'\033[33m'
  C_RESET=$'\033[0m'
else
  C_GREEN=""
  C_RED=""
  C_YELLOW=""
  C_RESET=""
fi

# -----------------------------------------------------------------------------
# Repo-root anchoring (script must work whether invoked from `make` or directly)
# -----------------------------------------------------------------------------
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$REPO_ROOT"

# -----------------------------------------------------------------------------
# Pre-flight: detect API container service name and verify it's running
# -----------------------------------------------------------------------------
API_SERVICE="api"
if ! docker compose ps "$API_SERVICE" 2>/dev/null | grep -qE "Up|running"; then
  API_SERVICE="geolens-api-1"
  if ! docker compose ps "$API_SERVICE" 2>/dev/null | grep -qE "Up|running"; then
    echo "${C_RED}ERROR${C_RESET}: API container is not running."
    echo "Hint: docker compose up -d api"
    exit 2
  fi
fi

# Resolve the actual container name for `docker exec` usage
API_CONTAINER="$( docker compose ps -q "$API_SERVICE" 2>/dev/null | head -1 )"
if [ -z "$API_CONTAINER" ]; then
  # Fallback: container name on Docker Compose v2 default scheme
  API_CONTAINER="geolens-api-1"
fi
# Use container name (not ID) so docker exec produces stable output.
# `docker compose ps -q` returns the container ID; convert to name via `docker inspect`.
if API_NAME="$( docker inspect --format='{{.Name}}' "$API_CONTAINER" 2>/dev/null | sed 's|^/||' )"; then
  if [ -n "$API_NAME" ]; then
    API_CONTAINER="$API_NAME"
  fi
fi

# -----------------------------------------------------------------------------
# Counters and timing
# -----------------------------------------------------------------------------
TOTAL=0
START_TS=$( date +%s )

# -----------------------------------------------------------------------------
# Helper: run_check — runs a labeled command, prints PASS/FAIL, exits on FAIL
# -----------------------------------------------------------------------------
run_check() {
  local label="$1"; shift
  local cmd="$*"
  TOTAL=$((TOTAL + 1))
  printf "  [%s] running: %s\n" "$label" "$cmd"
  # Run each check in a subshell so any `cd` inside the command does not leak
  # into the next check. The subshell starts from REPO_ROOT every time.
  if ( cd "$REPO_ROOT" && eval "$cmd" ) >/tmp/validate-v13-8-last.log 2>&1; then
    printf "  ${C_GREEN}[%s] PASS${C_RESET}\n" "$label"
  else
    local rc=$?
    printf "  ${C_RED}[%s] FAIL${C_RESET} (exit %d)\n" "$label" "$rc"
    echo "----- last 40 lines of output -----"
    tail -40 /tmp/validate-v13-8-last.log
    echo "----- end -----"
    exit 1
  fi
}

# -----------------------------------------------------------------------------
# Phase 246 — style-config-and-layer-diffs (STYLE-01..03 + SAVE-01..03)
# -----------------------------------------------------------------------------
run_phase_246() {
  echo "${C_YELLOW}==> Phase 246 (style-config-and-layer-diffs)${C_RESET}"
  run_check "STYLE-01-backend"  "docker exec $API_CONTAINER sh -c \"cd /app && /app/.venv/bin/pytest tests/test_maps.py -k 'paint or style_config' -q\""
  run_check "STYLE-01-frontend" "cd frontend && npm run test -- --run src/components/builder/__tests__/LayerStyleEditor.test.tsx src/components/builder/__tests__/layer-adapters.test.ts"
  run_check "STYLE-02-grep"     "grep -nE 'Builder-only state lives under builder' backend/openapi.json"
  run_check "STYLE-03-pytest"   "cd backend && uv run pytest tests/test_map_style_config_migration.py -q"
  run_check "STYLE-03-file"     "test -f backend/alembic/versions/0004_style_config_paint_cleanup.py"
  run_check "SAVE-01-backend"   "docker exec $API_CONTAINER sh -c \"cd /app && /app/.venv/bin/pytest tests/test_maps.py -k 'patch_map_layers' -q\""
  run_check "SAVE-01-openapi"   "grep -nE '/maps/\\{map_id\\}/layers' backend/openapi.json"
  run_check "SAVE-02-frontend"  "cd frontend && npm run test -- --run src/components/builder/hooks/__tests__/use-builder-save.test.ts src/components/builder/hooks/__tests__/use-builder-layers.test.ts"
  run_check "SAVE-02-sdk"       "test -f sdks/python/geolens/models/map_layer_diff_request.py && test -f sdks/typescript/src/client/types.gen.ts"
  run_check "SAVE-03-frontend"  "cd frontend && npm run test -- --run src/components/builder/hooks/__tests__/use-builder-save.test.ts"
  run_check "SAVE-03-backend"   "docker exec $API_CONTAINER sh -c \"cd /app && /app/.venv/bin/pytest tests/test_maps.py -k 'full_replacement' -q\""
}

# -----------------------------------------------------------------------------
# Phase 247 — raster-line-zoom-styling (frontend only)
# -----------------------------------------------------------------------------
run_phase_247() {
  echo "${C_YELLOW}==> Phase 247 (raster-line-zoom-styling)${C_RESET}"
  run_check "RASTER-01"      "cd frontend && npm run test -- --run src/components/builder/__tests__/RasterLayerControls.test.tsx"
  run_check "RASTER-02-test" "cd frontend && npm run test -- --run src/components/builder/__tests__/RasterLayerControls.test.tsx"
  run_check "RASTER-02-grep" "grep -nE 'style\\.raster\\.reset' frontend/src/components/builder/RasterLayerControls.tsx"
  run_check "LINE-01-test"   "cd frontend && npm run test -- --run src/components/builder/__tests__/LayerStyleEditor.test.tsx src/components/builder/__tests__/layer-adapters.test.ts"
  run_check "LINE-01-grep"   "grep -nE 'line-gap-width|line-blur|line-offset' frontend/src/components/builder/LayerStyleEditor.tsx"
  run_check "LINE-02-test"   "cd frontend && npm run test -- --run src/components/builder/__tests__/layer-adapters.test.ts"
  run_check "LINE-02-grep"   "grep -nE 'line-gradient' frontend/src/components/builder/LayerStyleEditor.tsx"
  run_check "ZOOM-01"        "cd frontend && npm run test -- --run src/lib/__tests__/zoom-expressions.test.ts"
  run_check "ZOOM-02"        "cd frontend && npm run test -- --run src/components/builder/__tests__/ZoomExpressionEditor.test.tsx src/components/builder/__tests__/LayerStyleEditor.test.tsx src/components/builder/__tests__/label-layer-utils.test.ts"
}

# -----------------------------------------------------------------------------
# Phase 248 — dem-and-terrain (frontend + 1 container-routed backend selector)
# -----------------------------------------------------------------------------
run_phase_248() {
  echo "${C_YELLOW}==> Phase 248 (dem-and-terrain)${C_RESET}"
  run_check "DEM-01-test"        "cd frontend && npm run test -- --run src/components/builder/__tests__/layer-adapters.test.ts src/components/builder/__tests__/map-sync.raster.test.ts"
  run_check "DEM-01-grep"        "grep -nE 'raster-dem' frontend/src/components/builder/layer-adapters/hillshade-adapter.ts"
  run_check "DEM-02-test"        "cd frontend && npm run test -- --run src/components/builder/__tests__/RasterLayerControls.test.tsx"
  run_check "DEM-02-grep"        "grep -nE 'is_dem|isDem|dem.*hillshade' frontend/src/components/builder/RasterLayerControls.tsx"
  run_check "TERRAIN-01"         "cd frontend && npm run test -- --run src/components/builder/__tests__/TerrainControls.test.tsx"
  run_check "TERRAIN-02-backend" "docker exec $API_CONTAINER sh -c \"cd /app && /app/.venv/bin/pytest tests/test_maps.py -k 'terrain' -q\""
  run_check "TERRAIN-02-front"   "cd frontend && npm run test -- --run src/components/builder/__tests__/BuilderMap.unit.test.ts src/components/viewer/__tests__/use-viewer-terrain.test.ts"
  run_check "TERRAIN-02-alembic" "test -f backend/alembic/versions/0005_map_terrain_config.py"
  run_check "TERRAIN-03-test"    "cd frontend && npm run test -- --run src/components/builder/__tests__/TerrainControls.test.tsx"
  run_check "TERRAIN-03-grep"    "grep -nE 'vertical|meter|exaggeration|caveat' frontend/src/components/builder/TerrainControls.tsx"
}

# -----------------------------------------------------------------------------
# Phase 249 — style-json-and-symbols (host backend + frontend)
# -----------------------------------------------------------------------------
run_phase_249() {
  echo "${C_YELLOW}==> Phase 249 (style-json-and-symbols)${C_RESET}"
  run_check "STYLEX-01-backend"  "cd backend && uv run pytest tests/test_maps_style_json.py -k 'build_maplibre_style' -q"
  run_check "STYLEX-01-frontend" "cd frontend && npm run test -- --run src/components/builder/__tests__/StyleJsonDialog.test.tsx src/components/builder/__tests__/MapToolbar.test.tsx"
  run_check "STYLEX-02-backend"  "cd backend && uv run pytest tests/test_maps_style_json.py -k 'parse_maplibre_style_import' -q"
  run_check "STYLEX-02-frontend" "cd frontend && npm run test -- --run src/components/builder/__tests__/StyleJsonDialog.test.tsx"
  run_check "STYLEX-03-backend"  "cd backend && uv run pytest tests/test_maps_style_json.py -k 'clean_sources or symbol_label or builder_style_config' -q"
  run_check "STYLEX-03-grep"     "grep -nE 'startswith\\(\"_\"\\)' backend/app/modules/catalog/maps/style_json.py"
  run_check "SYMB-01-test"       "cd frontend && npm run test -- --run src/components/builder/__tests__/layer-adapters.test.ts"
  run_check "SYMB-01-file"       "test -f frontend/src/components/builder/layer-adapters/symbol-adapter.ts"
  run_check "SYMB-02-backend"    "docker exec $API_CONTAINER sh -c \"cd /app && /app/.venv/bin/pytest tests/test_map_sprites.py -q\""
  run_check "SYMB-02-file"       "test -f backend/app/modules/catalog/maps/sprites.py"
  run_check "SYMB-03-test"       "cd frontend && npm run test -- --run src/components/builder/__tests__/LayerStyleEditor.test.tsx"
  run_check "SYMB-03-grep"       "grep -nE 'iconImage|iconSize' frontend/src/components/builder/LayerStyleEditor.tsx"
  run_check "SYMB-04-test"       "cd frontend && npm run test -- --run src/components/builder/__tests__/layer-adapters.test.ts src/components/builder/__tests__/LayerStyleEditor.test.tsx"
  run_check "SYMB-04-grep"       "grep -nE 'text-field|text-size|consolidat' frontend/src/components/builder/layer-adapters/symbol-adapter.ts"
}

# -----------------------------------------------------------------------------
# Phase 250 — map-edit-history (HIST-01..03)
# -----------------------------------------------------------------------------
run_phase_250() {
  echo "${C_YELLOW}==> Phase 250 (map-edit-history)${C_RESET}"
  run_check "HIST-01-backend"  "docker exec $API_CONTAINER sh -c \"cd /app && /app/.venv/bin/pytest tests/test_maps.py -k 'MapHistory' -q\""
  run_check "HIST-01-file"     "test -f backend/app/modules/catalog/maps/service_history.py"
  run_check "HIST-02-openapi"  "grep -nE '/maps/\\{map_id\\}/history' backend/openapi.json"
  run_check "HIST-03-frontend" "cd frontend && npm run test -- --run src/components/builder/__tests__/HistoryPanel.test.tsx src/components/builder/__tests__/BuilderRail.test.tsx"
  run_check "HIST-03-file"     "test -f frontend/src/components/builder/HistoryPanel.tsx"
}

# -----------------------------------------------------------------------------
# Phase 251 — style-json-raster-dem-terrain-roundtrip (STYLEX-01/02 + audit gaps)
# -----------------------------------------------------------------------------
run_phase_251() {
  echo "${C_YELLOW}==> Phase 251 (style-json-raster-dem-terrain-roundtrip)${C_RESET}"
  # Requirement-level rows
  run_check "STYLEX-01-export"      "cd backend && uv run pytest tests/test_maps_style_json.py -k 'build_maplibre_style' -q"
  run_check "STYLEX-01-grep-rdem"   "grep -nE 'type\":\\s*\"raster-dem\"' backend/app/modules/catalog/maps/style_json.py"
  run_check "STYLEX-01-grep-terr"   "grep -nE 'style\\[\"terrain\"\\]\\s*=' backend/app/modules/catalog/maps/style_json.py"
  run_check "STYLEX-01-grep-hill"   "grep -nE '_HILLSHADE_PAINT_KEYS' backend/app/modules/catalog/maps/style_json.py"
  run_check "STYLEX-02-import"      "cd backend && uv run pytest tests/test_maps_style_json.py -k 'parse_maplibre_style_import or round_trip' -q"
  run_check "STYLEX-02-grep-comp"   "grep -nE '_builder_from_outline_companion|_builder_from_extrusion_companion' backend/app/modules/catalog/maps/style_json.py"
  # Audit-gap-level rows (INT-01/02 + FLOW-01/02/03 reuse the export/import selectors)
  run_check "INT-01-export"         "cd backend && uv run pytest tests/test_maps_style_json.py -k 'build_maplibre_style' -q"
  run_check "INT-02-import"         "cd backend && uv run pytest tests/test_maps_style_json.py -k 'parse_maplibre_style_import or round_trip' -q"
  run_check "FLOW-01"               "cd backend && uv run pytest tests/test_maps_style_json.py -k 'exports_terrain_block or omits_terrain_block' -q"
  run_check "FLOW-02"               "cd backend && uv run pytest tests/test_maps_style_json.py -k 'restores_outline_and_extrusion' -q"
  run_check "FLOW-03"               "cd backend && uv run pytest tests/test_maps_style_json.py -k 'restores_terrain or terrain_config' -q"
  # NEW-INT-01: backend selector + commit gates
  run_check "NEW-INT-01-backend"        "docker exec $API_CONTAINER sh -c \"cd /app && /app/.venv/bin/pytest tests/test_maps.py -k 'TestImportStyleJsonTerrain' -q\""
  run_check "NEW-INT-01-commit-exists"  "git log --oneline e46b96c6 -1"
  run_check "NEW-INT-01-commit-ancestor" "git merge-base --is-ancestor e46b96c6 HEAD"
}

# -----------------------------------------------------------------------------
# Main entrypoint
# -----------------------------------------------------------------------------
echo "Running v13.8 VALIDATION.md backfill checks (6 phases, ~33+ requirements)"
echo "API container: $API_CONTAINER"
echo

run_phase_246
run_phase_247
run_phase_248
run_phase_249
run_phase_250
run_phase_251

END_TS=$( date +%s )
DUR=$(( END_TS - START_TS ))
echo
printf "${C_GREEN}Validated v13.8 — %d checks across 6 phases in %ds${C_RESET}\n" "$TOTAL" "$DUR"
