---
phase: 231-embedding-provider-extension-protocol
status: passed
verified_at: 2026-05-03T14:40:47Z
requirements:
  EMBPROV-01: passed
  EMBPROV-02: passed
  EMBPROV-03: passed
  EMBPROV-04: passed
  EMBPROV-05: passed
---

# Summary

Phase 231 is verified as passed. The codebase now has an `EmbeddingProviderExtension` Protocol, a `DefaultOpenAIEmbeddingProvider`, and a dict-shaped `get_embedding_provider(name)` registry accessor. Embedding generation and dimension probing route through the extension registry, while `backend/app/processing/embeddings/helpers.py` is provider-SDK-free.

The expanded architecture guard exists as `test_no_module_level_provider_sdk_imports_in_processing`, covers `backend/app/processing/`, and no longer carries the embeddings carve-out. Focused unit, architecture, grep, and lint checks passed. The only failed check was an unmodified local host DB provisioning path missing the PostgreSQL `vector` extension; the same registry tests passed when run with the DB intentionally unreachable to avoid provisioning.

# Requirement Verification

## EMBPROV-01: passed

`backend/app/platform/extensions/protocols.py` defines `@runtime_checkable class EmbeddingProviderExtension(Protocol)` with async `embed(...) -> list[list[float]]` and `resolve_runtime_config(...) -> dict[str, object]`.

Evidence:
- `rg -n "class EmbeddingProviderExtension" backend/app/platform/extensions/protocols.py`
- `backend/tests/test_embedding_provider_extension.py::test_default_embedding_provider_registered` asserts runtime Protocol satisfaction.

## EMBPROV-02: passed

`backend/app/platform/extensions/defaults.py` defines `DefaultOpenAIEmbeddingProvider`. `backend/app/platform/extensions/__init__.py` imports it and `get_embedding_provider(name)` seeds `_extensions["embedding_providers"]["openai_compatible"]` with `DefaultOpenAIEmbeddingProvider()` via per-key `setdefault`.

Evidence:
- `rg -n "class DefaultOpenAIEmbeddingProvider|def get_embedding_provider|providers.setdefault" backend/app/platform/extensions`
- `POSTGRES_PORT=1 uv run pytest tests/test_embedding_provider_extension.py -q` passed `3 passed`.

## EMBPROV-03: passed

`backend/app/processing/embeddings/helpers.py` no longer imports `OpenAI`, `openai`, or `httpx`, and no longer contains `_cached_openai_clients`, `build_openai_client`, or `resolve_embedding_base_url`. `generate_embedding` and `probe_embedding_dimensions` in `backend/app/processing/embeddings/service.py` call `get_embedding_provider("openai_compatible")`, resolve runtime config, and dispatch through `provider_ext.embed(...)`.

Evidence:
- `git grep -n -E "^(from|import) openai" -- backend/app/processing/embeddings/` returned zero hits.
- `rg -n "build_openai_client|resolve_embedding_base_url|_cached_openai_clients" backend/app/processing/embeddings backend/tests/test_embedding*` returned no active embedding helper symbols.
- `rg -n "get_embedding_provider\\(" backend/app/processing/embeddings/service.py` shows both service callers using the registry.

## EMBPROV-04: passed

`backend/tests/test_layering.py` contains `test_no_module_level_provider_sdk_imports_in_processing`, not the old `_in_processing_ai` test. The test scans `backend/app/processing/` for module-level Anthropic/OpenAI SDK imports, and the docstring no longer contains the old embeddings carve-out. The old test name is not collected.

Evidence:
- `POSTGRES_PORT=1 uv run pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing -q` passed.
- `POSTGRES_PORT=1 uv run pytest tests/test_layering.py -m architecture -q` passed `12 passed`.
- `uv run pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing_ai -q` returned not collected, confirming the rename.
- `git grep -n -E "^(from|import) (anthropic|openai)( |$)" -- backend/app/processing/` returned zero hits.

## EMBPROV-05: passed

Existing embedding service tests pass with provider-boundary mocks, preserving behavior at the service surface. The overlay dispatch test registers a test embedding provider through mocked `importlib.metadata.entry_points`, calls `load_extensions()`, resolves it via `get_embedding_provider("test_embedding_provider")`, and dispatches to `embed(...)` without modifying core files.

Evidence:
- `uv run pytest tests/test_embedding_service.py -q` passed `5 passed`.
- `POSTGRES_PORT=1 uv run pytest tests/test_embedding_provider_extension.py -q` passed `3 passed`.

# Commands Run

- `sed -n '1,260p' .planning/ROADMAP.md`
- `sed -n '1,260p' .planning/REQUIREMENTS.md`
- `sed -n '1,240p' .planning/phases/231-embedding-provider-extension-protocol/231-01-PLAN.md`
- `sed -n '1,240p' .planning/phases/231-embedding-provider-extension-protocol/231-02-PLAN.md`
- `sed -n '1,240p' .planning/phases/231-embedding-provider-extension-protocol/231-03-PLAN.md`
- `sed -n '1,220p' .planning/phases/231-embedding-provider-extension-protocol/231-01-SUMMARY.md`
- `sed -n '1,220p' .planning/phases/231-embedding-provider-extension-protocol/231-02-SUMMARY.md`
- `sed -n '1,220p' .planning/phases/231-embedding-provider-extension-protocol/231-03-SUMMARY.md`
- `git status --short`
- `sed -n '1,260p' backend/app/platform/extensions/protocols.py`
- `sed -n '560,820p' backend/app/platform/extensions/defaults.py`
- `sed -n '820,1040p' backend/app/platform/extensions/defaults.py`
- `sed -n '1,340p' backend/app/platform/extensions/__init__.py`
- `sed -n '1,240p' backend/app/processing/embeddings/service.py`
- `sed -n '1,180p' backend/app/processing/embeddings/helpers.py`
- `sed -n '1,220p' backend/tests/test_embedding_provider_extension.py`
- `sed -n '1,900p' backend/tests/test_layering.py`
- `sed -n '1,240p' backend/tests/test_embedding_service.py`
- `rg -n "class DefaultOpenAIEmbeddingProvider|def get_embedding_provider|class EmbeddingProviderExtension|from openai import OpenAI|import openai|from openai|import anthropic|test_no_module_level_provider_sdk_imports_in_processing|test_no_module_level_provider_sdk_imports_in_processing_ai|get_embedding_provider\\(" backend/app backend/tests`
- `rg -n "build_openai_client|resolve_embedding_base_url|_cached_openai_clients|OpenAI\\(|AsyncOpenAI|EMBEDDING_BASE_URL|OPENAI_BASE_URL|get_embedding_provider|EmbeddingProviderExtension|DefaultOpenAIEmbeddingProvider" backend/app/processing/embeddings backend/app/platform/extensions backend/tests/test_embedding*`
- `git grep -n -E "^(from|import) openai" -- backend/app/processing/embeddings/; true`
- `git grep -n -E "^(from|import) (anthropic|openai)( |$)" -- backend/app/processing/; true`
- `git grep -n -P "if\\s+.*provider\\s*==\\s*['\\\"](?:anthropic|openai_compatible)" -- backend/app/processing/ ':!backend/app/processing/ai/streaming.py' ':!backend/app/processing/ai/metadata_service.py'; true`
- `cd backend && uv run pytest tests/test_embedding_provider_extension.py -q` failed during local DB setup because host Postgres lacks `vector`.
- `cd backend && uv run pytest tests/test_embedding_service.py -q` passed `5 passed`.
- `cd backend && POSTGRES_PORT=1 uv run pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing -q` passed `1 passed`.
- `cd backend && uv run ruff check app/platform/extensions/protocols.py app/platform/extensions/defaults.py app/platform/extensions/__init__.py app/processing/embeddings/service.py app/processing/embeddings/helpers.py tests/test_embedding_provider_extension.py tests/test_embedding_service.py tests/test_layering.py` passed.
- `cd backend && POSTGRES_PORT=1 uv run pytest tests/test_embedding_provider_extension.py -q` passed `3 passed`.
- `cd backend && POSTGRES_PORT=1 uv run pytest tests/test_layering.py -m architecture -q` passed `12 passed`.
- `cd backend && uv run pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing_ai -q` returned not collected.

# Gaps

None.

# Human Verification

None required for Phase 231 goal achievement.

# Residual Risks

- Full backend suite was not run because the current host PostgreSQL service lacks the `vector` extension (`CREATE EXTENSION IF NOT EXISTS vector` fails). This is the known local DB provisioning issue noted by the phase summaries and is unrelated to the Phase 231 source changes.
- `.planning/REQUIREMENTS.md` has stale traceability rows marking several EMBPROV items as not started even though the requirement checklist and verified code show them complete. This does not affect Phase 231 implementation status.
- Existing unrelated dirty files were present before verification and were not modified.
