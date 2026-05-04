---
phase: 236-maps-service-decomposition
status: passed
verified_at: 2026-05-03T22:46:43Z
requirements:
  - MAPS-01
  - MAPS-02
  - MAPS-03
  - MAPS-04
  - MAPS-05
  - MAPS-06
---

# Phase 236 Verification

## Result

**Status:** passed

Phase 236 achieved its goal: `backend/app/modules/catalog/maps/service.py` is now a thin public facade, implementation lives in focused sibling modules, and map CRUD, layers, sharing, thumbnails, dataset maps, and public viewer behavior are covered by focused regression checks.

## Must-Haves

1. **Stable public facade imports:** Passed. `test_maps_service_facade_exports_public_api` asserts all existing public symbols are present as module attributes and in `service.__all__`.
2. **Focused implementation modules:** Passed. Implementation moved to:
   - `backend/app/modules/catalog/maps/service_shared.py`
   - `backend/app/modules/catalog/maps/service_crud.py`
   - `backend/app/modules/catalog/maps/service_layers.py`
   - `backend/app/modules/catalog/maps/service_public.py`
3. **Map CRUD/list/read/update/duplicate/delete behavior:** Passed. Full `backend/tests/test_maps.py` passed through existing router/facade call paths.
4. **Layer add/remove behavior:** Passed. Full map tests include layer round-trips, style defaults, layer type inference, legend defaults, and update sort order.
5. **Share/public/dataset-in-use/thumbnail behavior:** Passed. Full map tests include share tokens, shared map rendering, update share token, admin share token listing, visibility checks, thumbnails, and dataset maps.
6. **Architecture guard maintenance:** Passed. Existing concrete `User` ORM import guard now allowlists the decomposed maps modules that legitimately use `User.username` in SQLAlchemy joins/selects.

## Requirement Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| MAPS-01 | Passed | `service.py` facade plus `test_maps_service_facade_exports_public_api` |
| MAPS-02 | Passed | Focused `service_shared.py`, `service_crud.py`, `service_layers.py`, `service_public.py` modules |
| MAPS-03 | Passed | `tests/test_maps.py` CRUD/list/get/update/delete/duplicate coverage |
| MAPS-04 | Passed | `tests/test_maps.py` layer and layer round-trip coverage |
| MAPS-05 | Passed | `tests/test_maps.py` share/public/thumbnail/dataset-map coverage |
| MAPS-06 | Passed | Facade regression plus full focused maps regression suite |

## Verification Commands

- `POSTGRES_PORT=5434 uv run pytest tests/test_maps.py -q` — 107 passed
- `uv run pytest tests/test_layering.py -m architecture -q` — 15 passed
- `uv run ruff check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py app/modules/catalog/maps/service_public.py tests/test_maps.py tests/test_layering.py` — passed
- `uv run ruff format --check app/modules/catalog/maps/service.py app/modules/catalog/maps/service_shared.py app/modules/catalog/maps/service_crud.py app/modules/catalog/maps/service_layers.py app/modules/catalog/maps/service_public.py tests/test_maps.py tests/test_layering.py` — passed

## Issues

The first DB-backed focused pytest run targeted `localhost:5432` and failed before tests executed because `geolens_test` did not exist there. Docker Compose exposes the active GeoLens DB on `localhost:5434`; rerunning the same DB-backed verification with `POSTGRES_PORT=5434` passed.

## Human Verification

None required. Phase 236 is an internal service decomposition with automated regression coverage.

## Residual Risk

Low. This phase intentionally did not add private-module import or size-budget guards because Phase 238 owns boundary guard stabilization.
