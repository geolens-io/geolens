---
phase: 231-embedding-provider-extension-protocol
plan: 02
status: complete
subsystem: extensions
tags: [migration, caller, deletion, openai-removal, refactor]

# Dependency graph
requires:
  - phase: 231-embedding-provider-extension-protocol
    plan: 01
    provides: EmbeddingProviderExtension Protocol + DefaultOpenAIEmbeddingProvider + get_embedding_provider(name) accessor + 3 dispatch tests
provides:
  - generate_embedding routed through get_embedding_provider("openai_compatible").embed(...)
  - probe_embedding_dimensions routed through get_embedding_provider with dimensions=None for natural-size discovery
  - helpers.py reduced to provider-agnostic SQL helpers only (set_hnsw_recall, has_embeddings, get_nearest_record_ids, defer_embedding)
  - test_embedding_service.py with provider-boundary mocks (4 migrated, 1 unchanged)
affects: [231-03 (architecture-guard rename + pathspec widening), 229 (post-impl audit, Seam Quality grade)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - service caller dispatches to extension registry via get_embedding_provider(name)
    - retry/backoff lives in provider class (single source of truth) — service callers thin
    - test mocks at provider boundary, not SDK boundary (D-27)

key-files:
  created: []
  modified:
    - backend/app/processing/embeddings/service.py
    - backend/app/processing/embeddings/helpers.py
    - backend/tests/test_embedding_service.py

key-decisions:
  - "SC#3 binding satisfied: `git grep -E '^(from|import) openai' backend/app/processing/embeddings/` returns zero hits."
  - "EmbeddingUnavailableError stays at service.py:22 (D-22 fallback) — 4 external consumers (settings/router.py, catalog/search/service.py, test_embedding_service.py, test_embedding_pipeline.py) preserved verbatim."
  - "Fail-fast API-key check at service.py:42-49 preserved (defense in depth per RESEARCH.md Open Question 2)."
  - "_MAX_INPUT_CHARS truncation stays in service.py — service-level concern about cost/payload size."
  - "Retry loop fully removed from service.py — only retry path is DefaultOpenAIEmbeddingProvider.embed() (max 2 attempts, 2.0s+jitter backoff)."
  - "probe_embedding_dimensions passes dimensions=None to discover natural model dim size (D-02 contract)."
  - "Architecture guard test still narrow at processing/ai/ — Plan 03 widens it; helpers.py deletion is the gate that makes the wider pathspec safe."

patterns-established:
  - "service.py caller migration template: get_embedding_provider(name) + resolve_runtime_config(session) + embed(...) — single trip, no retry management at caller"
  - "helpers.py deletion pattern: pure deletion (no replacement) — provider artifacts moved up to platform/extensions/defaults.py in Plan 01; deletion seals the migration"
  - "test mock migration template: SDK-boundary patches (build_openai_client, embeddings.create) → provider-boundary patches (get_embedding_provider, mock_provider.embed); D-27 helper for canonical key dict construction"

requirements-completed:
  - EMBPROV-03
  - EMBPROV-05

# Metrics
duration: ~5min
completed: 2026-05-02
---

# Phase 231 Plan 02: Caller Migration + helpers.py Cleanup Summary

**Migrated `generate_embedding` and `probe_embedding_dimensions` to dispatch via `get_embedding_provider("openai_compatible")` from Plan 01; deleted dead provider scaffolding from `helpers.py` (`from openai import OpenAI`, `import httpx`, `_cached_openai_clients`, `build_openai_client`, `resolve_embedding_base_url`); migrated 4 of 5 mock surfaces in `test_embedding_service.py` from SDK boundary to provider boundary. SC#3 binding (`git grep -E "^(from|import) openai" backend/app/processing/embeddings/` returns zero hits) satisfied.**

## Performance

- **Duration:** ~5 min (active edit time)
- **Started:** 2026-05-02T19:09:27Z
- **Completed:** 2026-05-02T19:14:11Z
- **Tasks:** 3
- **Files modified:** 3 (service.py, helpers.py, test_embedding_service.py)
- **Files created:** 0
- **LOC delta:** +109 / -203 = net -94 across 3 files (deletions far exceed additions)

## Accomplishments

- **service.py migration** — Both callers (`generate_embedding` + `probe_embedding_dimensions`) now dispatch via `provider_ext = get_embedding_provider("openai_compatible")`. Each caller calls `resolve_runtime_config(session)` once at the top to retrieve `base_url` / `default_model` / `default_dims`, then calls `provider_ext.embed(...)` with the resolved values. Service callers no longer manage retries — that responsibility moved to `DefaultOpenAIEmbeddingProvider.embed()` per D-22 (single source of truth). The `_MAX_INPUT_CHARS` truncation logic stays in service.py (service-level concern). The fail-fast API-key check stays at the top (defense-in-depth per RESEARCH.md Open Question 2). `EmbeddingUnavailableError` stays in service.py (D-22 fallback; 4 external consumers preserved). Removed top-level `import asyncio` and `import random` (only used by retry loop, now gone). Removed the `from app.processing.embeddings.helpers import (build_openai_client, resolve_embedding_base_url)` block. Added `from app.platform.extensions import get_embedding_provider`.
- **helpers.py cleanup** — Removed 6 imports/symbols + 2 functions: `import httpx`, `from openai import OpenAI`, `from app.core.config import reveal, settings`, `from app.core.persistent_config import EMBEDDING_BASE_URL, OPENAI_BASE_URL`, `_cached_openai_clients` module cache, `resolve_embedding_base_url` function, `build_openai_client` function. **SC#3 binding** satisfied: `git grep -E "^(from|import) openai" backend/app/processing/embeddings/` returns zero hits. File shrinks from 119 to 90 lines. Preserved `set_hnsw_recall`, `has_embeddings`, `get_nearest_record_ids`, `defer_embedding` byte-for-byte.
- **test_embedding_service.py migration** — 4 of 5 tests rewritten with provider-boundary mocks (`patch("app.processing.embeddings.service.get_embedding_provider")` returning a `MagicMock` whose `embed = AsyncMock(...)` and `resolve_runtime_config = AsyncMock(...)`); 5th test (`test_generate_embedding_raises_when_no_openai_key`) byte-for-byte unchanged because the API-key check stays in service.py. Mock dicts use canonical keys per RESEARCH.md Pitfall 5: `base_url`, `default_model`, `default_dims`. Added `_make_mock_provider` helper to centralize the dict construction. Assertions migrate from SDK shape (`mock_client.embeddings.create.assert_called_once_with(model=..., input=..., dimensions=...)`) to provider shape (`mock_provider.embed.assert_called_once_with(texts=[...], model=..., dimensions=..., base_url=..., timeout=...)`).

## Task Commits

1. **Task 1: Migrate test mocks from SDK boundary to provider boundary (D-27)** — `ab1cf7e4` (test)
2. **Task 2: Migrate service.py callers to dispatch via get_embedding_provider** — `da26a0ef` (refactor)
3. **Task 3: Delete obsolete provider scaffolding from helpers.py** — `a350a94d` (refactor)

## Files Created/Modified

- `backend/app/processing/embeddings/service.py` — net `+41 / -97` LOC. Removed retry/backoff loops from both `generate_embedding` and `probe_embedding_dimensions`; removed top-level `asyncio` + `random` imports + helpers.py import block; added `from app.platform.extensions import get_embedding_provider` import. Both functions now ~30 LOC each (down from ~80 LOC each).
- `backend/app/processing/embeddings/helpers.py` — net `+0 / -29` LOC. Pure deletion. File shrinks from 119 to 90 lines. Preserves all provider-agnostic helpers byte-for-byte.
- `backend/tests/test_embedding_service.py` — net `+68 / -77` LOC. 4 tests rewritten with provider-boundary mocks; 1 test (`test_generate_embedding_raises_when_no_openai_key`) byte-for-byte unchanged; added `_make_mock_provider` helper.

## Decisions Made

None additional — followed `231-02-PLAN.md` as specified. All decisions were already locked in `231-CONTEXT.md` (D-21 through D-28) and respected verbatim:
- Hardcoded `"openai_compatible"` in both callers (D-12) — no `EMBEDDING_PROVIDER` PersistentConfig added.
- `EmbeddingUnavailableError` stays at `service.py:22` — D-22 fallback recommendation per RESEARCH.md primary finding (4 external consumers' imports unchanged).
- Fail-fast API-key check preserved at `service.py:42-49` — defense in depth per RESEARCH.md Open Question 2.
- `_MAX_INPUT_CHARS` truncation stays in service.py (service-level concern).
- `_make_mock_provider` test helper used for code economy; could have been inlined per-test (plan flagged it OPTIONAL).

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

**1. Local pytest run blocked by missing pgvector PostgreSQL extension on host (pre-existing infrastructure constraint).**
- **Found during:** All 3 task verifications.
- **Issue:** `cd backend && uv run pytest tests/test_embedding_service.py` fails at the session-scoped `_test_db_lifecycle` fixture because the host's PG container is `postgis/postgis:17-3.5` which lacks the `vector` extension. Same failure noted in 231-01-SUMMARY.md.
- **Resolution:** Verified all tests pass by running them inside the `geolens-api-1` container (which has the proper test DB infrastructure):
  ```
  $ docker exec geolens-api-1 sh -c "cd /app && uv run pytest tests/test_embedding_service.py tests/test_embedding_pipeline.py tests/test_hybrid_search.py tests/test_embedding_provider_extension.py tests/test_extensions.py tests/test_ai_provider_extension.py -q"
  48 passed in 4.18s
  ```

**2. Architecture-guard test SKIPPED in container (no git metadata).**
- **Found during:** Task 3 verification.
- **Issue:** `test_no_module_level_provider_sdk_imports_in_processing_ai` SKIPs in the docker container because the container doesn't ship the `.git` directory (`SKIPPED [1] tests/test_layering.py:800: git metadata unavailable; arch test only runs on full clones`). On the host the test runs, but the host's pgvector limitation blocks the session fixture.
- **Resolution:** Manually reproduced the guard's logic on the host: `git grep -nE "^(from|import) (anthropic|openai)( |$)" -- backend/app/processing/ai/` returns zero hits — guard would be GREEN at its existing narrow pathspec. Plan 03 will widen the pathspec to `backend/app/processing/`; this plan's helpers.py deletion is the gate that makes the wider pathspec safe.

**3. Alembic check fails (pre-existing enterprise SAML chain regression).**
- **Found during:** Task 3 verification (D-32 gate).
- **Issue:** `uv run alembic check` reports new column adds for `idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id` on `catalog.oauth_providers`. This is a documented PRE-EXISTING regression from the 2026-05-02 Alembic squash (see global memory `feedback_alembic_squash_enterprise_chain.md` — the OSS baseline declares the union of OAuth columns but the enterprise overlay's chain adds the SAML-specific columns separately).
- **Resolution:** Plan 02 changes touch ZERO model definitions — the diff is in `service.py`, `helpers.py`, `tests/`. The Alembic regression is unrelated. Confirmed by inspecting the commit diff (`git diff --stat HEAD~3 HEAD -- backend/`): no model files touched.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **SC#3 binding** satisfied: `git grep -E "^(from|import) openai" backend/app/processing/embeddings/` returns zero hits.
- **service.py** routes through registry: both `generate_embedding` and `probe_embedding_dimensions` call `get_embedding_provider("openai_compatible")` once each.
- **helpers.py** is provider-agnostic: only `set_hnsw_recall`, `has_embeddings`, `get_nearest_record_ids`, `defer_embedding` remain.
- **EmbeddingUnavailableError** unchanged location at `service.py:22` — 4 external consumers (`settings/router.py`, `catalog/search/service.py`, `test_embedding_service.py`, `test_embedding_pipeline.py`) preserved.
- **Architecture-guard** STILL narrow at `processing/ai/` — Plan 03 will rename `test_no_module_level_provider_sdk_imports_in_processing_ai` → `test_no_module_level_provider_sdk_imports_in_processing` and widen pathspec to `backend/app/processing/`. This plan's helpers.py deletion is the gate that makes that widening safe.
- **Wave 3 (Plan 03)** can begin immediately; no blockers.

## Self-Check: PASSED

- [x] `backend/app/processing/embeddings/service.py` — `from app.platform.extensions import get_embedding_provider` imported; both `generate_embedding` and `probe_embedding_dimensions` call `get_embedding_provider("openai_compatible")`; `dimensions=None` passed in probe; `_MAX_INPUT_CHARS` truncation preserved; `EmbeddingUnavailableError` class still at line 22; rebuild_embedding_column + build_content_text + compute_content_hash + generate_and_store_embedding UNCHANGED; ruff clean.
- [x] `backend/app/processing/embeddings/helpers.py` — file exists at 90 lines (down from 119); `from openai import OpenAI` REMOVED; `import httpx` REMOVED; `from app.core.config` REMOVED; `from app.core.persistent_config` REMOVED; `_cached_openai_clients`, `build_openai_client`, `resolve_embedding_base_url` ALL REMOVED; `set_hnsw_recall`, `has_embeddings`, `get_nearest_record_ids`, `defer_embedding` PRESERVED; ruff clean.
- [x] `backend/tests/test_embedding_service.py` — 4 tests use `patch("app.processing.embeddings.service.get_embedding_provider")`; mock dicts use canonical keys `base_url`, `default_model`, `default_dims`; `test_generate_embedding_raises_when_no_openai_key` byte-for-byte unchanged; ruff clean.
- [x] **SC#3 binding:** `git grep -E "^(from|import) openai" backend/app/processing/embeddings/` returns zero hits (exit code 1, no output).
- [x] All 3 commits exist in `git log`: `ab1cf7e4`, `da26a0ef`, `a350a94d`.
- [x] Container test sweep: 48 passed across `test_embedding_service.py` (5) + `test_embedding_pipeline.py` + `test_hybrid_search.py` (21) + `test_embedding_provider_extension.py` (3) + `test_extensions.py` (16) + `test_ai_provider_extension.py` (3). No regressions.
- [x] EmbeddingUnavailableError consumers preserved: `git grep -n "EmbeddingUnavailableError" backend/` shows imports/raises in `service.py`, `defaults.py` (Plan 01), `catalog/search/service.py`, `settings/router.py`, `test_embedding_service.py`, `test_embedding_pipeline.py` — all 4 external consumers + Plan 01 defaults.py consumer + canonical service.py definition.
- [x] Architecture guard logic re-verified manually on host (`git grep -nE "^(from|import) (anthropic|openai)( |$)" -- backend/app/processing/ai/` returns zero hits) — narrow pathspec still GREEN. Plan 03 widens.

---
*Phase: 231-embedding-provider-extension-protocol*
*Completed: 2026-05-02*
