---
phase: 236-maps-service-decomposition
plan: 05
type: execute
wave: 5
depends_on:
  - 236-04
files_modified:
  - backend/app/modules/catalog/maps/service.py
  - backend/tests/test_layering.py
  - backend/tests/test_maps.py
autonomous: true
requirements:
  - MAPS-01
  - MAPS-02
  - MAPS-03
  - MAPS-04
  - MAPS-05
  - MAPS-06
must_haves:
  truths:
    - "service.py is a thin Phase 224-style facade that preserves the full public map service import surface."
    - "No router, admin, embed-token, dataset, AI/ProcessingPort, or existing test caller imports private maps service modules directly."
    - "Focused map regression tests cover CRUD, layer round-trips, sharing, thumbnails, dataset maps, and facade import stability."
    - "Existing Phase 214 User ORM import guard is maintained for legitimate SQL-attribute joins moved into maps private modules."
  artifacts:
    - path: backend/app/modules/catalog/maps/service.py
      provides: "Thin public facade"
      contains: "__all__"
    - path: backend/tests/test_maps.py
      provides: "Facade import and behavior regression coverage"
      contains: "test_maps_service_facade_exports_public_api"
    - path: backend/tests/test_layering.py
      provides: "Updated Phase 214 concrete User ORM import allowlist for decomposed maps modules"
      contains: "service_shared.py"
  key_links:
    - from: "backend/tests/test_maps.py"
      to: "backend/app/modules/catalog/maps/service.py"
      via: "facade export regression test"
      pattern: "test_maps_service_facade_exports_public_api"
    - from: "backend/app/modules/catalog/maps/service.py"
      to: "service_crud/service_layers/service_public/service_shared"
      via: "explicit re-export imports"
      pattern: "__all__"
---

<objective>
Finish the maps service decomposition by making the facade intentionally thin and adding focused regression coverage for import stability.

Purpose: close Phase 236 with executable proof that behavior and public imports survived the staged split.
Output: final facade cleanup plus test coverage.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/236-maps-service-decomposition/236-01-SUMMARY.md
@.planning/phases/236-maps-service-decomposition/236-02-SUMMARY.md
@.planning/phases/236-maps-service-decomposition/236-03-SUMMARY.md
@.planning/phases/236-maps-service-decomposition/236-04-SUMMARY.md
@backend/app/modules/catalog/maps/service.py
@backend/app/modules/catalog/maps/service_shared.py
@backend/app/modules/catalog/maps/service_crud.py
@backend/app/modules/catalog/maps/service_layers.py
@backend/app/modules/catalog/maps/service_public.py
@backend/app/modules/catalog/maps/router.py
@backend/tests/test_maps.py
@backend/tests/test_layering.py

<interfaces>
Final facade target, mirroring Phase 224 `catalog/datasets/domain/service.py`: a module docstring explaining the split, imports from focused sibling modules, and `__all__` listing every public symbol external callers already use.

Do not add the architecture guard here; Phase 238 owns private-module import guards and size budgets. This plan may add a focused facade import regression test only.

Existing architecture guard maintenance required in this plan: `backend/tests/test_layering.py::test_cross_domain_does_not_import_user_from_auth_models` currently allowlists `backend/app/modules/catalog/maps/service.py` because the old service file legitimately uses `User.username` as a SQLAlchemy attribute in joins/selects. After this split, those legitimate SQL-attribute uses move into `service_shared.py`, `service_crud.py`, and `service_public.py`. Update that existing Phase 214 guard's docstring and pathspec allowlist for those new maps modules. This is maintenance for an existing guard, not the new Phase 238 private-module boundary guard.
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Finalize thin service facade</name>
  <files>backend/app/modules/catalog/maps/service.py</files>
  <action>Reduce `service.py` to a Phase 224-style facade: module docstring, imports from `service_shared.py`, `service_crud.py`, `service_layers.py`, and `service_public.py`, and an explicit `__all__`. Remove leftover implementation imports that are no longer needed by the facade. The facade should preserve existing import names and avoid new product behavior. Keep private split modules free of imports from `app.modules.catalog.maps.service`.</action>
  <verify>
    <automated>cd backend && uv run python - <<'PY'
from app.modules.catalog.maps import service
required = {
    "DatasetMeta", "LayerRow", "check_map_ownership", "get_dataset_meta",
    "generate_default_style", "create_map", "get_map", "get_map_with_layers",
    "list_maps", "update_map", "delete_map", "bulk_check_dataset_access",
    "duplicate_map", "add_layer", "remove_layer", "validate_public_visibility",
    "find_public_maps_using_dataset", "create_share_token", "update_share_token",
    "get_active_share_token", "get_shared_map", "list_share_tokens",
    "revoke_share_token", "get_maps_for_dataset", "revoke_share_token_by_map",
}
missing = sorted(name for name in required if not hasattr(service, name))
assert not missing, missing
assert set(required).issubset(set(service.__all__))
PY</automated>
  </verify>
  <done>`service.py` is a stable, explicit facade with all existing public symbols available.</done>
</task>

<task type="auto">
  <name>Add facade regression and maintain existing architecture allowlist</name>
  <files>backend/tests/test_maps.py, backend/tests/test_layering.py</files>
  <action>Add a focused test near the top of `test_maps.py` named `test_maps_service_facade_exports_public_api`. It should import `app.modules.catalog.maps.service` and assert the existing public API names are present in `__all__` and as module attributes. Keep this test source-introspection-light: it should not inspect private module source blocks or enforce size budgets because Phase 238 owns that. Also update `test_cross_domain_does_not_import_user_from_auth_models` in `backend/tests/test_layering.py` so its docstring and git-grep pathspec allowlist cover the maps private modules that legitimately use `User` only as SQLAlchemy attributes after decomposition: `backend/app/modules/catalog/maps/service_shared.py`, `backend/app/modules/catalog/maps/service_crud.py`, and `backend/app/modules/catalog/maps/service_public.py`. Keep `backend/app/modules/catalog/maps/service.py` allowlisted if it still imports/re-exports in a way that trips the guard, but prefer removing it if the final facade no longer imports `User`. Do not update existing callers to private modules and do not add the Phase 238 private-module boundary guard here.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_maps.py::test_maps_service_facade_exports_public_api tests/test_maps.py::TestCreateMap tests/test_maps.py::TestMapLayers tests/test_maps.py::TestShareToken tests/test_maps.py::TestSharedMap tests/test_maps.py::TestMapThumbnail tests/test_maps.py::TestDatasetMaps tests/test_maps.py::TestLayerTypeRoundTrip tests/test_maps.py::TestShowInLegendRoundTrip tests/test_maps.py::test_update_map_layers_round_trip_sort_order tests/test_layering.py::test_cross_domain_does_not_import_user_from_auth_models -q</automated>
  </verify>
  <done>Facade import regression, focused behavior coverage, and the existing Phase 214 concrete User import guard pass after the split.</done>
</task>

<task type="auto">
  <name>Run decomposition lint and architecture smoke checks</name>
  <files>backend/app/modules/catalog/maps/service.py, backend/tests/test_maps.py, backend/tests/test_layering.py</files>
  <action>Run the focused lint/format/architecture checks for the touched maps modules and existing architecture tests. Fix only issues caused by this phase's files. Do not add Phase 238 boundary guards here and do not modify unrelated files.</action>
  <verify>
    <automated>cd backend && uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py app/modules/catalog/maps/service_public.py tests/test_maps.py tests/test_layering.py && uv run ruff format --check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py app/modules/catalog/maps/service_public.py tests/test_maps.py tests/test_layering.py && uv run pytest tests/test_layering.py -m architecture -q</automated>
  </verify>
  <done>Ruff, format check, and existing architecture guards pass for the decomposed maps service state.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_maps.py -q
- cd backend && uv run pytest tests/test_layering.py -m architecture -q
- cd backend && uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py app/modules/catalog/maps/service_public.py tests/test_maps.py tests/test_layering.py
- cd backend && uv run ruff format --check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py app/modules/catalog/maps/service_public.py tests/test_maps.py tests/test_layering.py
</verification>

<success_criteria>
- MAPS-01 is satisfied by the facade export regression test.
- MAPS-02 is satisfied by implementation moving into focused modules with the facade left thin.
- MAPS-03, MAPS-04, and MAPS-05 are covered by focused behavior tests through the router/facade.
- MAPS-06 is satisfied by the added facade regression plus existing CRUD/layer/share/thumbnail/public viewer tests.
</success_criteria>

<output>
After completion, create `.planning/phases/236-maps-service-decomposition/236-05-SUMMARY.md`.
</output>
