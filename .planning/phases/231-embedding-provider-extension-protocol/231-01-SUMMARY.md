---
phase: 231-embedding-provider-extension-protocol
plan: 01
status: complete
subsystem: extensions
tags: [protocol, extension, embedding, additive, openai, asyncopenai, registry]

# Dependency graph
requires:
  - phase: 226-ai-provider-extension-protocol
    provides: AIProviderExtension Protocol + DefaultOpenAICompatibleProvider class-level _clients cache pattern + get_ai_provider(name) accessor template + test_ai_provider_extension.py shape
provides:
  - EmbeddingProviderExtension Protocol with @runtime_checkable, async embed() + resolve_runtime_config() signatures
  - DefaultOpenAIEmbeddingProvider class with AsyncOpenAI client cache and 2-attempt retry/backoff loop
  - get_embedding_provider(name) accessor with dict-keyed registry and ValueError-on-unknown
  - test_embedding_provider_extension.py with default smoke + entry-points dispatch + ValueError tests
affects: [231-02 (helpers.py + service.py migration), 231-03 (architecture-guard rename), 229 (post-impl audit, Seam Quality grade)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - dict-keyed Protocol dispatch (mirrors Phase 226 ai_providers slot)
    - class-level _clients dict cache keyed by base_url (mirrors DefaultOpenAICompatibleProvider._clients)
    - deferred-import discipline inside provider method bodies (Phase 214 / 222 / 225 / 226 lineage)
    - autouse _clean_registry fixture replicated inline per test file (RESEARCH.md Pitfall 2)

key-files:
  created:
    - backend/tests/test_embedding_provider_extension.py
  modified:
    - backend/app/platform/extensions/protocols.py
    - backend/app/platform/extensions/defaults.py
    - backend/app/platform/extensions/__init__.py

key-decisions:
  - "Pure additive scaffold — no production caller touched (D-29 sequencing); helpers.py:8 'from openai import OpenAI' STILL PRESENT (Plan 02 deletes it); architecture-guard test STILL named _in_processing_ai with embeddings carve-out (Plan 03 renames)."
  - "AsyncOpenAI replaces sync OpenAI + asyncio.to_thread (D-25); eliminates to_thread overhead and matches Phase 226 chat-completions provider."
  - "Class-level _clients dict cache keyed by base_url (D-26) mirrors DefaultOpenAICompatibleProvider._clients verbatim (defaults.py:625)."
  - "EmbeddingProviderExtension has NO stream() method (D-03) — embeddings are batch-only; streaming a vector makes no sense."
  - "EmbeddingUnavailableError stays in service.py (RESEARCH.md primary finding); 4 external consumers preserved; provider imports via deferred-import inside embed() body."
  - "resolve_runtime_config returns three keys: base_url, default_model, default_dims (D-04) — extra default_dims supports probe_embedding_dimensions discovery flow."
  - "Single community default DefaultOpenAIEmbeddingProvider (D-06); Anthropic does not ship an embeddings API."

patterns-established:
  - "EmbeddingProviderExtension Protocol: @runtime_checkable, async embed(*, texts, model, dimensions, base_url, timeout) -> list[list[float]] + async resolve_runtime_config(db) -> dict"
  - "DefaultOpenAIEmbeddingProvider: deferred imports inside embed()/resolve_runtime_config(); class-level _clients dict cache; conditional dimensions kwarg per RESEARCH.md Pitfall 3 (the SDK rejects dimensions=None)"
  - "get_embedding_provider(name) accessor: per-key setdefault seeding (single 'openai_compatible' default), ValueError('Unknown embedding provider: {name}') for unknown names"
  - "Test file shape: autouse _clean_registry fixture replicated inline (no inter-test-file imports), 3 tests covering default smoke + ValueError + entry-points overlay dispatch"

requirements-completed:
  - EMBPROV-01
  - EMBPROV-02
  - EMBPROV-05

# Metrics
duration: ~5min
completed: 2026-05-02
---

# Phase 231 Plan 01: Embedding Provider Extension Scaffold Summary

**EmbeddingProviderExtension Protocol + DefaultOpenAIEmbeddingProvider + get_embedding_provider(name) accessor + 3 dispatch tests; pure additive scaffold using AsyncOpenAI with class-level keyed-client cache.**

## Performance

- **Duration:** ~5 min (active edit time)
- **Started:** 2026-05-02T19:01:00Z (approximately, just before commit `644a6df6`)
- **Completed:** 2026-05-02T19:05:30Z (just after commit `f3d65753`)
- **Tasks:** 4
- **Files modified:** 3 (protocols.py, defaults.py, __init__.py)
- **Files created:** 1 (test_embedding_provider_extension.py)
- **LOC delta:** +353 / -1 across 4 files

## Accomplishments

- Added `EmbeddingProviderExtension` Protocol — `@runtime_checkable`, async `embed()` with keyword-only kwargs (`texts`, `model`, `dimensions`, `base_url`, `timeout`), async `resolve_runtime_config()` returning `dict[str, object]`. NO `stream()` method (D-03).
- Added `DefaultOpenAIEmbeddingProvider` — community-edition default. `embed()` uses `AsyncOpenAI` (no `asyncio.to_thread`); class-level `_clients: dict = {}` cache keyed by `base_url`; absorbs the 2-attempt retry/backoff loop from `service.py:70-110` verbatim (jitter 0.0-0.3 random factor on 2.0s base, broad `except Exception`, `asyncio.wait_for` per call). All imports deferred inside method bodies (`from openai import AsyncOpenAI`, `httpx`, `app.core.config`, `app.processing.embeddings.service` for `EmbeddingUnavailableError`).
- Added `get_embedding_provider(name)` accessor — dict-keyed at `_extensions["embedding_providers"]`, per-key `setdefault` seeding `"openai_compatible"` once, `ValueError("Unknown embedding provider: {name}")` on unknown names. Order-safe vs overlay registration timing.
- Added `test_embedding_provider_extension.py` — 3 tests (default smoke per D-19, ValueError per D-20, entry-points overlay dispatch per D-18), autouse `_clean_registry` fixture replicated inline. All 3 pass when run inside the API test container (host environment lacks pgvector PG extension; pre-existing infrastructure constraint).

## Task Commits

1. **Task 1: Add `EmbeddingProviderExtension` Protocol** — `644a6df6` (feat)
2. **Task 2: Add `DefaultOpenAIEmbeddingProvider`** — `19e77168` (feat)
3. **Task 3: Add `get_embedding_provider(name)` accessor** — `94549233` (feat)
4. **Task 4: Add `test_embedding_provider_extension.py`** — `f3d65753` (test)

**Plan metadata:** committed alongside the SUMMARY/STATE/ROADMAP update commit (post-summary creation).

## Files Created/Modified

- `backend/app/platform/extensions/protocols.py` (+46 LOC) — Append `EmbeddingProviderExtension` Protocol after `AIProviderExtension`. NO TYPE_CHECKING additions (return type is plain `list[list[float]]`).
- `backend/app/platform/extensions/defaults.py` (+130 LOC) — Append `DefaultOpenAIEmbeddingProvider` after `DefaultOpenAICompatibleProvider`. Class-level `_clients: dict = {}` cache. Method-body deferred imports.
- `backend/app/platform/extensions/__init__.py` (+33 / -1 LOC) — Add `DefaultOpenAIEmbeddingProvider` import; merge `EmbeddingProviderExtension` into the existing `TYPE_CHECKING` import tuple alongside `AIProviderExtension`; append `get_embedding_provider(name)` accessor after `get_ai_provider`.
- `backend/tests/test_embedding_provider_extension.py` (+145 LOC, NEW) — 3 tests + autouse `_clean_registry` fixture.

## Decisions Made

None additional — followed `231-01-PLAN.md` as specified. All decisions were already locked in `231-CONTEXT.md` (D-01 through D-33) and respected verbatim:
- Pure additive: no caller touched, no `helpers.py` modified, no `service.py` modified.
- `EmbeddingUnavailableError` stays in `service.py` (RESEARCH.md primary finding; 4 external consumers preserved).
- Conditional `dimensions` kwarg construction (Pitfall 3); `EMBEDDING_BASE_URL → OPENAI_BASE_URL → "https://api.openai.com/v1"` fallback chain preserved byte-for-byte (Pitfall 6); `httpx.Timeout(60.0, connect=10.0)` preserved (matches today's `helpers.py:106`).
- TYPE_CHECKING block merged into a single tuple import (`AIProviderExtension`, `EmbeddingProviderExtension`) for one-line economy; ruff approved.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

**1. Local pytest run blocked by missing pgvector PostgreSQL extension on host.**
- **Found during:** Task 4 verification.
- **Issue:** `cd backend && uv run pytest tests/test_embedding_provider_extension.py` fails at the session-scoped `_test_db_lifecycle` fixture because the host's PG container is `postgis/postgis:17-3.5` which lacks the `vector` extension. Same failure already exists for `tests/test_ai_provider_extension.py` (Phase 226 sibling) when run from the host — pre-existing infrastructure constraint, not related to Plan 01 changes.
- **Resolution:** Verified the new tests pass by running them inside the `geolens-api-1` container (which has the proper test DB infrastructure):
  ```
  $ docker exec geolens-api-1 sh -c "cd /app && uv run pytest tests/test_embedding_provider_extension.py -x -q"
  3 passed in 1.21s
  ```
- **Existing-test green-light:** Same container run for `test_embedding_service.py + test_ai_provider_extension.py + test_extensions.py` → 24 passed (no regression).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `helpers.py:8` (`from openai import OpenAI`), `_cached_openai_clients`, `resolve_embedding_base_url`, `build_openai_client` are all STILL PRESENT (deletion happens in Plan 02).
- Architecture guard `test_no_module_level_provider_sdk_imports_in_processing_ai` STILL named with the `_in_processing_ai` suffix and STILL has the embeddings carve-out paragraph (rename happens in Plan 03).
- Spot-check confirmation:
  ```
  $ git grep -E "^(from|import) openai" backend/app/processing/embeddings/
  backend/app/processing/embeddings/helpers.py:from openai import OpenAI
  ```
- The new accessor `get_embedding_provider("openai_compatible")` is unwired from production code — Plan 02 migrates `generate_embedding` and `probe_embedding_dimensions` to consume it.
- Wave 2 (Plan 02) can begin immediately; no blockers.

## Self-Check: PASSED

- [x] `backend/app/platform/extensions/protocols.py` — file exists; `class EmbeddingProviderExtension(Protocol)` declared; `@runtime_checkable` count went from 6 to 7. ✓ ruff clean.
- [x] `backend/app/platform/extensions/defaults.py` — file exists; `class DefaultOpenAIEmbeddingProvider` declared with `_clients: dict = {}`; `isinstance(DefaultOpenAIEmbeddingProvider(), EmbeddingProviderExtension)` returns True; module-level imports unchanged (only `from __future__ import annotations`). ✓ ruff clean.
- [x] `backend/app/platform/extensions/__init__.py` — file exists; `def get_embedding_provider` declared; `DefaultOpenAIEmbeddingProvider` imported; `EmbeddingProviderExtension` forward-referenced via TYPE_CHECKING; `ValueError("Unknown embedding provider: ...")` correctly raised on unknown names. ✓ ruff clean.
- [x] `backend/tests/test_embedding_provider_extension.py` — file exists; 3 tests declared (`test_default_embedding_provider_registered`, `test_unknown_embedding_provider_raises_value_error`, `test_overlay_embedding_provider_is_dispatched`); autouse `_clean_registry` fixture present; 3 tests pass in container (`docker exec geolens-api-1 ... pytest`). ✓ ruff clean.
- [x] All 4 commits exist in `git log`: `644a6df6`, `19e77168`, `94549233`, `f3d65753`.
- [x] Existing test suite green: `test_embedding_service.py` (5 tests) + `test_ai_provider_extension.py` (3 tests) + `test_extensions.py` (16 tests) = 24 passed in container, baseline preserved.
- [x] `helpers.py:8` (`from openai import OpenAI`) STILL PRESENT — Plan 01 does NOT touch it (Plan 02 will).
- [x] Architecture guard NOT renamed — Plan 03 owns that change.

---
*Phase: 231-embedding-provider-extension-protocol*
*Completed: 2026-05-02*
