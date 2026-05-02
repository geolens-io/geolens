# Phase 231: embedding-provider-extension-protocol - Research

**Researched:** 2026-05-02
**Domain:** Python Protocol extension seam / OpenAI embeddings provider dispatch refactor
**Confidence:** HIGH

## Summary

Phase 231 closes the last direct provider-SDK import in `backend/app/processing/` (`from openai import OpenAI` at `helpers.py:8`) by introducing an `EmbeddingProviderExtension` Protocol at `backend/app/platform/extensions/protocols.py`, ships a single `DefaultOpenAIEmbeddingProvider` registered under `"openai_compatible"`, and renames the Phase-226 architecture guard to cover both `processing/ai/` and `processing/embeddings/`. The locked decisions in 231-CONTEXT.md (D-01..D-33) specify every structural choice; this research closes the 9 gaps the orchestrator flagged — most importantly the test-mock surface inventory, the exact rename mechanics in `test_layering.py`, the `EmbeddingUnavailableError` blast radius, the AsyncOpenAI migration safety check, the architecture-guard sequencing, and the Validation Architecture section that the planner needs to sample requirements per Nyquist.

**Primary finding:** `EmbeddingUnavailableError` has **four external consumers** that import it from `app.processing.embeddings.service` — moving it (D-22 default option (b)) requires updating all four import sites OR adding a re-export shim. Affected files: `modules/settings/router.py:332`, `modules/catalog/search/service.py:47`, `tests/test_embedding_service.py:8`, `tests/test_embedding_pipeline.py:257`. CONTEXT.md mentions this risk in §code_context but does not enumerate the four sites; the planner needs the exhaustive list to size the diff. Recommendation: keep `EmbeddingUnavailableError` in `service.py` (D-22 fallback option) — the diff is ~5 lines smaller, the four consumers stay untouched, and the Protocol contract still owns its exception by importing from `service.py` inside the `defaults.py` provider class (deferred-import discipline already used elsewhere). The provider class lives in `defaults.py`, so the import edge is `defaults.py → service.py` inside a method body — no module-level coupling, no runtime cycle.

**Primary recommendation:** Mirror Phase 226's commit decomposition exactly — 3 atomic commits, architecture-guard rename last. Use `AsyncOpenAI` as Phase 226 does (verified safe — same SDK version `>=2.0.0,<3`, same shape; no embeddings-specific gotcha). Keep `EmbeddingUnavailableError` in `service.py` to minimize diff. Migrate the 5 tests in `test_embedding_service.py` to patch `service.get_embedding_provider` (D-27 option (a)) — `test_embedding_pipeline.py` and `test_hybrid_search.py` are unaffected because they mock at the higher service-function boundary.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All D-01 through D-33 from 231-CONTEXT.md are locked. Key ones the planner must copy into plans:
- **D-01**: Single batch method `embed()` on the Protocol (batch shape from day one)
- **D-02**: `embed()` signature — keyword-only kwargs `texts: list[str]`, `model: str`, `dimensions: int | None = None`, `base_url: str | None = None`, `timeout: float | None = None` → returns `list[list[float]]`
- **D-03**: NO `stream()` method (embeddings are batch-only, no streaming concept)
- **D-04**: `resolve_runtime_config(db)` Protocol method returning `{"base_url": ..., "default_model": ..., "default_dims": ...}`
- **D-05**: `@runtime_checkable` on the Protocol
- **D-06**: ONE community default class — `DefaultOpenAIEmbeddingProvider` (not two like Phase 226; Anthropic has no embeddings API)
- **D-07**: Registered under name key `"openai_compatible"` — same name as the AI provider's OpenAI-compatible default but in a distinct registry slot (no collision)
- **D-08**: Class name `DefaultOpenAIEmbeddingProvider` (drops "Extension" suffix per Phase 226 D-18 discipline)
- **D-09**: Registry slot `_extensions["embedding_providers"]` is `dict[str, EmbeddingProviderExtension]` (dict-shape mirroring Phase 226 D-04)
- **D-10**: `get_embedding_provider(name)` accessor in `__init__.py` mirrors `get_ai_provider` body verbatim (per-key `setdefault`, single default seeded)
- **D-11**: `ValueError("Unknown embedding provider: {name}")` on unknown name
- **D-12**: NO new `EMBEDDING_PROVIDER` PersistentConfig (caller hardcodes `"openai_compatible"`)
- **D-13**: Rename `test_no_module_level_provider_sdk_imports_in_processing_ai` → `test_no_module_level_provider_sdk_imports_in_processing` (single test)
- **D-14**: Pathspec broadens from `backend/app/processing/ai/` to `backend/app/processing/`; regex unchanged (already covers `anthropic|openai`)
- **D-15**: Negative-control verification — temporarily reintroduce `from openai import OpenAI` in `helpers.py`, confirm renamed test fails
- **D-16**: Update `test_layering.py` module docstring to credit Phase 231 alongside 212/213/214/222/223/224/225/226
- **D-17**: Reuse existing `@pytest.mark.architecture` marker
- **D-18**: NEW `tests/test_embedding_provider_extension.py` — entry-points dispatch test (overlay registers, accessor returns it, `embed()` succeeds)
- **D-19**: Default-provider smoke test in same file — `get_embedding_provider("openai_compatible")` returns `DefaultOpenAIEmbeddingProvider`
- **D-20**: Unknown-provider test — `get_embedding_provider("nonexistent")` raises `ValueError`
- **D-21**: Two call sites migrate — `service.py:31-110` (`generate_embedding`) and `service.py:113-172` (`probe_embedding_dimensions`)
- **D-22**: Retry/backoff loop moves from `service.py:72-110` INTO `DefaultOpenAIEmbeddingProvider.embed()`
- **D-23**: `helpers.py:8` (`from openai import OpenAI`) REMOVED per SC#3
- **D-24**: `resolve_embedding_base_url` (helpers.py:90-97) folds into provider's `resolve_runtime_config()`
- **D-25**: `build_openai_client` (helpers.py:100-109) body moves into provider class as class-level `_clients` cache; switches sync `OpenAI` → `AsyncOpenAI` and removes `asyncio.to_thread` wrapping
- **D-26**: `_cached_openai_clients` module-level cache → `DefaultOpenAIEmbeddingProvider._clients` class-level cache
- **D-27**: 5 tests in `test_embedding_service.py` migrate from patching `service.build_openai_client` → patching `service.get_embedding_provider` returning a mock provider
- **D-28**: `test_embedding_pipeline.py` and `test_hybrid_search.py` UNAFFECTED (they mock at the service-function boundary, not SDK boundary)
- **D-29**: Sequencing constraint — architecture-guard test rename MUST land in the same commit as (or after) the import removal
- **D-30**: Existing embeddings tests stay green per SC#5
- **D-31**: NO frontend involvement; NO OpenAPI change
- **D-32**: NO Alembic migration
- **D-33**: Phase 229 verifies grade movement to Seam Quality A−

### Claude's Discretion
- Commit decomposition (3 suggested; planner may split/collapse)
- Module docstring wording for `EmbeddingProviderExtension` (mirror Phase 226 `AIProviderExtension` docstring shape)
- Whether `EmbeddingUnavailableError` moves to `protocols.py` / new `extensions/exceptions.py` or stays in `service.py`
- Whether `dimensions` is on Protocol surface or only on default (default: at Protocol per D-02)
- Whether `httpx.Timeout` config is at Protocol level or inside provider (default: inside provider)
- Whether to expose `embed_one(text)` convenience method (default: NO)
- Order of tests in `test_embedding_provider_extension.py`
- Whether to use `AsyncOpenAI` per D-25 (default: YES)

### Deferred Ideas (OUT OF SCOPE)
- New embedding-provider implementations (Bedrock / Vertex / Azure / Cohere)
- `EMBEDDING_PROVIDER` PersistentConfig key
- Combining `AIProviderExtension.embed()` with the LLM Protocol
- Per-tenant provider instances (Cloud tier)
- Provider configuration UX (admin UI)
- Provider-side dimension validation
- True embedding streaming
- Pyright/mypy CI gate
- Tightening architecture-guard regex beyond `(anthropic|openai)`
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EMBPROV-01 | `EmbeddingProviderExtension` Protocol at `protocols.py` exposing `embed(texts, model)` | D-01..D-05 specify exact shape; `protocols.py:91-152` (Phase 226 `AIProviderExtension`) confirms template; `from __future__ import annotations` and `TYPE_CHECKING` discipline already in place at line 11/18 |
| EMBPROV-02 | `DefaultOpenAIEmbeddingProvider` resolves community provider; `get_embedding_provider(name)` accessor follows `get_ai_provider` dict-shape pattern | D-06..D-11; `__init__.py:224-255` (`get_ai_provider`) confirmed by direct read; `defaults.py:608-818` (`DefaultOpenAICompatibleProvider`) provides the class-level `_clients` cache template verbatim |
| EMBPROV-03 | `helpers.py:8` removed; embedding callers route through registry; `git grep -E "^(from\|import) openai" backend/app/processing/embeddings/` returns zero hits | D-21..D-26; the single hit verified today by `git grep` (only `helpers.py:8`); after migration, ZERO hits expected. Architecture guard (D-13) enforces |
| EMBPROV-04 | Architecture guard renamed/expanded to cover both `processing/ai/` and `processing/embeddings/`; embeddings carve-out removed from docstring | D-13..D-16; `test_layering.py:778-829` read; carve-out paragraph at lines 789-792 (4 lines) gets removed; pathspec `backend/app/processing/ai/` (line 810) → `backend/app/processing/`; regex unchanged (line 808 already covers `anthropic\|openai`) |
| EMBPROV-05 | Existing embeddings tests pass unchanged with default provider; entry-points overlay test dispatched correctly | D-18..D-20, D-27, D-30; mock-target migration mechanical (5 tests in `test_embedding_service.py`); `test_extensions.py` `patch("entry_points")` pattern reusable |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Protocol definition + accessor | `app/platform/extensions/` | — | Matches `AuditSink` / `BillingExtension` / `AIProviderExtension` precedent; audit explicitly places `EmbeddingProviderExtension` here |
| Default implementation | `app/platform/extensions/defaults.py` | — | Same file as `DefaultOpenAICompatibleProvider`; deferred-import discipline applies |
| Embedding generation logic | `DefaultOpenAIEmbeddingProvider.embed()` | — | Body absorbs `service.py:72-110` retry loop + `helpers.py:100-109` client construction; AsyncOpenAI native (no `asyncio.to_thread`) |
| Runtime-config resolution | `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()` | — | Replaces `helpers.py:90-97` `resolve_embedding_base_url`; returns `{base_url, default_model, default_dims}` dict (extensible for Bedrock/Vertex) |
| Caller orchestration | `app/processing/embeddings/service.py` (`generate_embedding`, `probe_embedding_dimensions`) | provider class | Service callers stay thin: read PersistentConfig, call `provider_ext.embed(...)`; no SDK-level details |
| Architecture invariant | `tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing` | `tests/test_embedding_provider_extension.py` | Architecture guard catches regressions; entry-points test exercises the seam end-to-end |
| Client cache | `DefaultOpenAIEmbeddingProvider._clients` class-level | — | Class-level dict mirrors Phase 226 `DefaultOpenAICompatibleProvider._clients` at `defaults.py:625` verbatim |

---

## Standard Stack

### Core (no new packages)

| Component | Current Location | Destination |
|-----------|-----------------|-------------|
| `openai.AsyncOpenAI` | (not currently used in embeddings) | Imported INSIDE `DefaultOpenAIEmbeddingProvider.embed()` body (deferred discipline) |
| `openai.OpenAI` (sync) | `helpers.py:8` | REMOVED (D-23) |
| `httpx.Timeout(60.0, connect=10.0)` | `helpers.py:106` | Move into `DefaultOpenAIEmbeddingProvider` SDK client construction |
| `importlib.metadata.entry_points` | `__init__.py:10` | Unchanged |
| `@runtime_checkable` / `Protocol` | `protocols.py:13` | Add `EmbeddingProviderExtension` |
| `EMBEDDING_BASE_URL`, `OPENAI_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMS` | `core/persistent_config.py:427-456` | Read INSIDE `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()` |

No new pip installs. [VERIFIED: `backend/pyproject.toml:24` declares `openai>=2.0.0,<3` — same line of code Phase 226 uses for `AsyncOpenAI`. No version bump needed.]

### AsyncOpenAI Embeddings — Verification

`AsyncOpenAI` supports `client.embeddings.create(...)` — same surface as the sync `OpenAI` client today. [CITED: https://github.com/openai/openai-python — Context7 doc fetch confirms `client.embeddings.create(model=..., input=..., dimensions=...)` is the canonical method on both `OpenAI` and `AsyncOpenAI` classes; only the call site changes from sync `client.embeddings.create(...)` to `await client.embeddings.create(...)`.] No embeddings-specific gotcha. The pattern Phase 226's `DefaultOpenAICompatibleProvider` uses for `client.chat.completions.create` is the same shape.

**Migration shape (today → after):**
```python
# Today (helpers.py + service.py):
client = build_openai_client(base_url)  # returns sync openai.OpenAI
response = await asyncio.wait_for(
    asyncio.to_thread(client.embeddings.create, model=..., input=..., dimensions=...),
    timeout=130.0,
)
return response.data[0].embedding

# After (DefaultOpenAIEmbeddingProvider.embed):
client = self._get_or_create_client(base_url)  # returns AsyncOpenAI; cached on class
response = await asyncio.wait_for(
    client.embeddings.create(model=..., input=texts, dimensions=dimensions),
    timeout=timeout or 130.0,
)
return [item.embedding for item in response.data]
```

The `asyncio.to_thread` wrapping disappears (AsyncOpenAI is async-native); `asyncio.wait_for` remains for the per-call timeout. [VERIFIED: read Phase 226 `DefaultOpenAICompatibleProvider.complete()` body at `defaults.py:702-714` which uses `await client.chat.completions.create(**create_kwargs)` directly — same pattern.]

---

## Architecture Patterns

### Protocol Class Pattern (mirror `protocols.py:91-152` for `AIProviderExtension`)

```python
# Source: backend/app/platform/extensions/protocols.py:91-152 (read directly)
@runtime_checkable
class EmbeddingProviderExtension(Protocol):
    """Embedding provider dispatch table entry (Phase 231 D-01 / EMBPROV-01).

    Sibling of AIProviderExtension (Phase 226). Replaces the direct
    `from openai import OpenAI` at processing/embeddings/helpers.py:8 with
    name-keyed extension lookup. Registry slot _extensions["embedding_providers"]
    is a dict[str, EmbeddingProviderExtension] (D-09, dict-shape).

    Community default: DefaultOpenAIEmbeddingProvider (key: "openai_compatible").
    Single class — Anthropic does not ship an embeddings API; the AI provider
    has two community defaults, embeddings has one.

    Overlays add new providers without modifying any core file (SC#5)::

        def register_extensions(registry: dict) -> None:
            providers = registry.setdefault("embedding_providers", {})
            providers["bedrock"] = BedrockEmbeddingProvider()
    """

    async def embed(
        self,
        *,
        texts: list[str],
        model: str,
        dimensions: int | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> list[list[float]]: ...

    async def resolve_runtime_config(self, db: AsyncSession) -> dict[str, object]: ...
```

### Accessor Pattern (mirror `__init__.py:224-255` for `get_ai_provider`)

```python
# Source: backend/app/platform/extensions/__init__.py:224-255 (read directly)
def get_embedding_provider(name: str) -> "EmbeddingProviderExtension":
    """Return the named EmbeddingProviderExtension or raise ValueError (Phase 231 D-09/D-10)."""
    providers = _extensions.setdefault("embedding_providers", {})
    providers.setdefault("openai_compatible", DefaultOpenAIEmbeddingProvider())
    if name not in providers:
        raise ValueError(f"Unknown embedding provider: {name}")
    return providers[name]  # type: ignore[return-value]
```

### Default Provider Class Pattern (mirror `defaults.py:608-818` for `DefaultOpenAICompatibleProvider`)

```python
# Source: backend/app/platform/extensions/defaults.py:608-692 (read directly, adapted)
class DefaultOpenAIEmbeddingProvider:
    """Community-edition default: OpenAI-compatible embeddings (Phase 231 D-08)."""

    _clients: dict = {}  # class-level cache: base_url -> AsyncOpenAI

    async def embed(self, *, texts, model, dimensions=None, base_url=None, timeout=None):
        # Deferred imports (Phase 214 / Phase 226 discipline)
        import asyncio
        import random
        import structlog
        from openai import AsyncOpenAI
        from app.core.config import reveal, settings
        from app.processing.embeddings.service import EmbeddingUnavailableError  # see D-22

        log = structlog.stdlib.get_logger(__name__)

        if not settings.openai_api_key:
            raise EmbeddingUnavailableError(
                "Embedding generation requires an OpenAI-compatible API key."
            )

        effective_base_url = (
            base_url or settings.openai_base_url or "https://api.openai.com/v1"
        )

        # Lazy class-level keyed-client cache (mirrors defaults.py:685-692)
        if effective_base_url not in DefaultOpenAIEmbeddingProvider._clients:
            import httpx
            DefaultOpenAIEmbeddingProvider._clients[effective_base_url] = AsyncOpenAI(
                api_key=reveal(settings.openai_api_key),
                base_url=effective_base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
                max_retries=2,
            )
        client = DefaultOpenAIEmbeddingProvider._clients[effective_base_url]

        # Retry loop moved from service.py:72-110 (D-22)
        max_attempts = 2
        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                kwargs = {"model": model, "input": texts}
                if dimensions is not None:
                    kwargs["dimensions"] = dimensions
                response = await asyncio.wait_for(
                    client.embeddings.create(**kwargs),
                    timeout=timeout or 130.0,
                )
                return [item.embedding for item in response.data]
            except Exception as exc:
                last_exc = exc
                if attempt < max_attempts:
                    await asyncio.sleep(backoff * (1 + random.random() * 0.3))
                else:
                    log.error("Embedding API failed after retries", exc_info=True)
        raise EmbeddingUnavailableError(f"Embedding API call failed: {last_exc}") from last_exc

    async def resolve_runtime_config(self, db) -> dict[str, object]:
        from app.core.persistent_config import (
            EMBEDDING_BASE_URL, EMBEDDING_DIMS, EMBEDDING_MODEL, OPENAI_BASE_URL,
        )
        embedding_url = await EMBEDDING_BASE_URL.get(db)
        base_url = (
            embedding_url
            or await OPENAI_BASE_URL.get(db)
            or "https://api.openai.com/v1"
        )
        return {
            "base_url": base_url,
            "default_model": await EMBEDDING_MODEL.get(db),
            "default_dims": await EMBEDDING_DIMS.get(db),
        }
```

### Entry-Points Test Pattern (mirror `test_extensions.py:1-65` + `test_ai_provider_extension.py:1-100`)

```python
# Source: backend/tests/test_ai_provider_extension.py:1-100 (read directly)
def _reset_registry():
    import app.platform.extensions as ext_mod
    ext_mod._extensions.clear()
    ext_mod._loaded = False

@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()
```

This autouse fixture is **mandatory** in `test_embedding_provider_extension.py` — without it, the editable-installed enterprise overlay's entry points pollute the registry and `setdefault("openai_compatible", DefaultOpenAIEmbeddingProvider())` never runs because an overlay provider for that key may already be present.

---

## Architecture-Guard Rename Mechanics — EXACT EDITS

This section closes orchestrator gap #3 ("exact line numbers, exact docstring lines to remove, exact regex").

### File: `backend/tests/test_layering.py`

**Function rename (line 778):**
```python
# Today:
def test_no_module_level_provider_sdk_imports_in_processing_ai() -> None:
# After:
def test_no_module_level_provider_sdk_imports_in_processing() -> None:
```

**Docstring header (line 779-780):**
```python
# Today:
    """oc-audit 2026-05-02 §5: backend/app/processing/ai/ must not have
    module-level imports of provider SDKs (anthropic, openai).
# After:
    """oc-audit 2026-05-02 §5 + Phase 231: backend/app/processing/ must not have
    module-level imports of provider SDKs (anthropic, openai).
```

**Carve-out paragraph DELETED (lines 789-792, 4 lines):**
```python
# DELETE these 4 lines:
    Carve-out: ``processing/embeddings/helpers.py`` is excluded — the
    embeddings client is not yet covered by ``AIProviderExtension``; an
    ``EmbeddingProviderExtension`` Protocol is the planned follow-up.
    Once that ships, this exclusion can be removed.
```

**Negative-control paragraph (lines 794-797) — UPDATE to reference embeddings:**
```python
# Today (lines 794-797):
    Negative-control: temporarily reintroduce
    ``from anthropic import AsyncAnthropic`` at the top of
    ``backend/app/processing/ai/llm_loop.py``, run this test, confirm it
    fails with the offending line surfaced. Revert.
# After (replace `processing/ai/llm_loop.py` with `processing/embeddings/helpers.py`
#  per D-15 Phase 231 negative-control; keep both phases credited):
    Negative-control (Phase 231 D-15): temporarily reintroduce
    ``from openai import OpenAI`` at the top of
    ``backend/app/processing/embeddings/helpers.py``, run this test,
    confirm it fails with the offending line surfaced. Revert.
```

**Pathspec broaden (line 810, the `git grep` `--` argument):**
```python
# Today:
            "backend/app/processing/ai/",
# After:
            "backend/app/processing/",
```

**Failure message (lines 819-823) — broaden the path text:**
```python
# Today:
            "Module-level provider-SDK import found in backend/app/processing/ai/. "
# After:
            "Module-level provider-SDK import found in backend/app/processing/. "
```

**Regex (line 808): UNCHANGED — `r"^(from|import) (anthropic|openai)( |$)"` already covers both SDKs.** [VERIFIED: read line 808 directly.]

### File: `backend/tests/test_layering.py:1-38` (module docstring)

Update the credits to add Phase 231 alongside the existing list. Today (line 1):
```python
"""Layering rules across Phases 212, 213, 214, 222, 223, 224, 225, and 226.
```
After:
```python
"""Layering rules across Phases 212, 213, 214, 222, 223, 224, 225, 226, and 231.
```

And add a Phase-231 bullet to the body (after the Phase 226 entry at line 14-20):
```python
- Phase 231 EMBPROV-04 - the Phase-226 architecture guard
  test_no_module_level_provider_sdk_imports_in_processing_ai is RENAMED
  to test_no_module_level_provider_sdk_imports_in_processing, pathspec
  broadened from backend/app/processing/ai/ to backend/app/processing/,
  and the embeddings carve-out paragraph removed from the docstring.
```

---

## Test Mock Surface Inventory

This section closes orchestrator gap #4 ("inventory all embedding test mock targets").

### Tests that patch the SDK boundary — MUST MIGRATE per D-27

`backend/tests/test_embedding_service.py` (5 tests, all use `service.build_openai_client` and/or `service.resolve_embedding_base_url`):

| Test | Lines | Patches | Migration Target |
|------|-------|---------|------------------|
| `test_generate_embedding_returns_float_vector` | 13-47 | `service.build_openai_client`, `service.resolve_embedding_base_url`, `service.settings`, `service.EMBEDDING_MODEL`, `service.EMBEDDING_DIMS` | Replace first 2 with `service.get_embedding_provider` returning a mock provider whose `embed = AsyncMock(return_value=[fake_vector])` and `resolve_runtime_config = AsyncMock(return_value={...})` |
| `test_generate_embedding_raises_when_no_openai_key` | 50-63 | `service.settings` only (asserts `EmbeddingUnavailableError` raised before client construction) | NO migration needed if the API-key check stays in `service.py` (D-22 default). But if the check moves into provider, this test needs the provider mock to raise. **Recommendation:** keep the `if not settings.openai_api_key:` check in `service.generate_embedding` AS WELL — defense in depth, no behavior change |
| `test_generate_embedding_uses_persistent_config` | 65-101 | Same 5 patches as #1 | Same migration |
| `test_generate_embedding_truncates_long_input` | 105-143 | Same 5 patches as #1 | Same migration; assert that `mock_provider.embed` was called with `texts=[<truncated text>]` |
| `test_generate_embedding_dimension_mismatch` | 145-187 | Same 5 patches as #1 | Same migration; the dim-mismatch assertion moves from `mock_client.embeddings.create.assert_called_with(dimensions=...)` to `mock_provider.embed.assert_called_with(dimensions=...)` |

[VERIFIED: read `test_embedding_service.py:1-60` and grep'd lines 13-187 for all `patch(...)` invocations.]

### Tests that mock at the service-function boundary — UNAFFECTED per D-28

| Test File | Mock Target | Why Unaffected |
|-----------|-------------|----------------|
| `test_embedding_pipeline.py` | `app.processing.embeddings.service.generate_embedding` (line 190, 234, 273, 307) | `generate_embedding`'s signature `(text: str, session: AsyncSession) -> list[float]` is UNCHANGED. Tests stay green. |
| `test_embedding_pipeline.py` (line 257-279) | `EmbeddingUnavailableError` import + `mock_gen.side_effect = EmbeddingUnavailableError(...)` | Exception class location MAY move (D-22). If it stays in `service.py` (recommended), zero change. If it moves, update import. |
| `test_hybrid_search.py` | `app.modules.catalog.search.service.generate_embedding` (line 242, 368, 415) | Same — service-boundary mock; signature unchanged |
| `test_embedding_backfill.py` | `app.processing.embeddings.backfill.backfill_embeddings` (high-level) | Doesn't touch the SDK or service-level embedding functions directly |

[VERIFIED: grep'd `test_embedding_pipeline.py`, `test_hybrid_search.py`, `test_embedding_backfill.py` for `generate_embedding\|build_openai_client\|EmbeddingUnavailable`. All hits confirm service-boundary mocking.]

### Tests files with NO embedding-related mocks (informational)

`tests/test_semantic_search.py` does NOT exist — only the three above. [VERIFIED: `ls tests/test_semantic*` returned no matches.]

---

## EmbeddingUnavailableError Location — Detailed Recommendation

This section closes orchestrator gap #5 ("recommend by re-reading the import graph: which keeps the diff smallest?").

### Current location: `backend/app/processing/embeddings/service.py:27-28`

### External consumers (sites that import `EmbeddingUnavailableError` from `service.py`):

| File | Line | Usage |
|------|------|-------|
| `backend/app/modules/settings/router.py` | 332-338 | `from app.processing.embeddings.service import (EmbeddingUnavailableError, ...)` then `except EmbeddingUnavailableError as e: raise HTTPException(...)` |
| `backend/app/modules/catalog/search/service.py` | 47, 262 | `from app.processing.embeddings.service import (EmbeddingUnavailableError, ...)` then `except EmbeddingUnavailableError: ...` (graceful fallback to keyword-only search) |
| `backend/tests/test_embedding_service.py` | 8 | `from app.processing.embeddings.service import (EmbeddingUnavailableError, ...)` |
| `backend/tests/test_embedding_pipeline.py` | 257 | `from app.processing.embeddings.service import (..., EmbeddingUnavailableError, ...)` |

[VERIFIED: `grep -rn "EmbeddingUnavailableError" backend/` returned exactly these 4 external consumers + 7 self-references in `service.py`.]

### Three options & diff cost

| Option | Diff cost | Trade-off |
|--------|-----------|-----------|
| **(a) Keep in `service.py`** | 0 lines (4 external imports unchanged) | Provider class imports from `service.py` (deferred-import inside `embed()` body — no module-level edge). Slight asymmetry vs. Phase 226's `ToolLoopExhaustedError` which lives in `llm_loop.py` |
| **(b) Move to `protocols.py`** | 4+ external import edits, plus the class itself | Cleanest layering (Protocol owns its exception); but `protocols.py` is currently TYPE-only (no concrete classes). Adding an exception class breaks that discipline |
| **(c) New `extensions/exceptions.py`** | 4+ external import edits, plus new file | Clean home; new file overhead; planner has to decide whether to also move other exceptions there |

### Recommendation: Option (a) — keep `EmbeddingUnavailableError` in `service.py`

Reasons:
1. **Smallest diff** — zero changes to 4 consumers; reduces blast radius of the phase
2. **Symmetry argument is weak** — Phase 226's `ToolLoopExhaustedError` lives in `llm_loop.py` next to `ToolLoopResult` (a data class, not a Protocol contract); the parallel for embeddings is `service.py` next to `generate_embedding` (the public service function), NOT `protocols.py`
3. **Provider class can import from `service.py`** — the import is `from app.processing.embeddings.service import EmbeddingUnavailableError` INSIDE `DefaultOpenAIEmbeddingProvider.embed()` body (deferred-import discipline already used by Phase 226 `DefaultOpenAICompatibleProvider` for `ToolLoopExhaustedError` at `defaults.py:651`); no module-level coupling, no runtime cycle
4. **Architecture guard not affected** — `EmbeddingUnavailableError` is not a SDK import; the guard regex `^(from|import) (anthropic|openai)( |$)` doesn't match exception imports

**Counter-arg the planner may consider:** Option (a) creates a `defaults.py → service.py` import edge (deferred). Option (c) avoids this entirely. If the planner wants total layering purity, choose (c) and accept the 4-line diff to consumers. Both are acceptable; CONTEXT.md D-22 explicitly says "Planner picks final location; both work."

---

## Caller Migration — Exact Sequencing and Code

### `service.py:31-110` (`generate_embedding`) after migration

```python
async def generate_embedding(text: str, session: AsyncSession) -> list[float]:
    if not settings.openai_api_key:
        raise EmbeddingUnavailableError(
            "Embedding generation requires an OpenAI-compatible API key. ..."
        )

    provider_ext = get_embedding_provider("openai_compatible")
    runtime_config = await provider_ext.resolve_runtime_config(session)
    model = await EMBEDDING_MODEL.get(session) or runtime_config.get("default_model")
    dims = await EMBEDDING_DIMS.get(session) or runtime_config.get("default_dims")
    base_url = runtime_config.get("base_url")

    # Truncate very long input
    if len(text) > _MAX_INPUT_CHARS:
        text = text[:_MAX_INPUT_CHARS]

    logger.info("Generating embedding", model=model, dimensions=dims, text_length=len(text))

    vectors = await provider_ext.embed(
        texts=[text],
        model=model,
        dimensions=dims,
        base_url=base_url,
        timeout=130.0,
    )
    return vectors[0]
```

### `service.py:113-172` (`probe_embedding_dimensions`) after migration

```python
async def probe_embedding_dimensions(session: AsyncSession) -> int:
    if not settings.openai_api_key:
        raise EmbeddingUnavailableError(
            "Embedding generation requires an OpenAI-compatible API key."
        )

    provider_ext = get_embedding_provider("openai_compatible")
    runtime_config = await provider_ext.resolve_runtime_config(session)
    model = await EMBEDDING_MODEL.get(session) or runtime_config.get("default_model")
    base_url = runtime_config.get("base_url")

    vectors = await provider_ext.embed(
        texts=["dimension probe"],
        model=model,
        dimensions=None,  # Discover natural size
        base_url=base_url,
        timeout=30.0,
    )
    embedding = vectors[0] if vectors else []
    if not embedding:
        raise EmbeddingUnavailableError(
            f"Embedding probe for model '{model}' returned empty vector."
        )
    return len(embedding)
```

### `helpers.py` after migration

Removed lines: 6 (`import httpx`), 8 (`from openai import OpenAI`), 14 (`OPENAI_BASE_URL` import), 19 (`_cached_openai_clients`), 90-97 (`resolve_embedding_base_url`), 100-109 (`build_openai_client`).

Remaining: `time`, `uuid`, `structlog`, `sqlalchemy` imports + `set_hnsw_recall`, `has_embeddings`, `get_nearest_record_ids`, `defer_embedding`, `_has_embeddings_cache`, `_HAS_EMBEDDINGS_TTL`. The file shrinks from 119 lines to ~80 lines.

[VERIFIED: read `helpers.py` end-to-end. The remaining helpers are all provider-agnostic SQL/cache utilities.]

---

## Commit Sequence for SC#3 + SC#4 Compliance

This section closes orchestrator gap #7 ("document the precise commit sequence to satisfy SC#3 AND keep CI green at every commit").

The challenge: SC#3 requires zero `from openai` hits in `processing/embeddings/`. The architecture-guard rename (SC#4) is what enforces this — but if the rename lands BEFORE the import is removed, CI fails. Conversely, if the import is removed BEFORE the migration (without a substitute), `service.py` fails to import. The plan must thread this needle.

### Recommended atomic commit sequence (mirrors Phase 226 D-29)

| Commit | Files | Description | CI Status |
|--------|-------|-------------|-----------|
| **#1 — Additive** | `protocols.py` (add `EmbeddingProviderExtension`); `defaults.py` (add `DefaultOpenAIEmbeddingProvider`); `__init__.py` (add `get_embedding_provider` accessor + import the new class); `tests/test_embedding_provider_extension.py` (NEW — D-18, D-19, D-20) | Pure additive: new Protocol, new default class, new accessor, new test file. `helpers.py:8` import unchanged. No call sites touched. | GREEN — old + new code coexist; existing 5 `test_embedding_service.py` tests still pass against the old `build_openai_client` |
| **#2 — Migrate callers** | `service.py:31-110, 113-172` (rewrite both functions to use `get_embedding_provider`); `helpers.py` (remove `from openai import OpenAI`, `import httpx`, `_cached_openai_clients`, `resolve_embedding_base_url`, `build_openai_client`); `tests/test_embedding_service.py` (migrate 5 tests per D-27) | The migration commit. After this, `helpers.py:8` is removed; `git grep -E "^(from\|import) openai" backend/app/processing/embeddings/` returns zero. | GREEN — full backend test suite passes; SC#3 already TRUE but architecture guard doesn't enforce it yet |
| **#3 — Rename architecture guard** | `tests/test_layering.py:778-829` (rename function, broaden pathspec, remove carve-out paragraph, update negative-control paragraph); `tests/test_layering.py:1-38` (update module docstring) | Architecture-guard rename. Now `processing/embeddings/` is invariant-protected. | GREEN — guard now actively prevents reintroduction of `from openai`/`from anthropic` anywhere in `processing/` |

### Why this order works

- **Commit #1 is purely additive** — adding new symbols can't break existing code. The new test file uses the autouse fixture pattern from Phase 226, so registry isolation is automatic.
- **Commit #2 removes the offending import** — at this point `helpers.py:8` is gone. The architecture guard (still named `_in_processing_ai`) doesn't fire because its pathspec is still `processing/ai/`. SC#3 is satisfied; SC#4 is not yet enforced but doesn't fail either.
- **Commit #3 renames the guard** — now the broader pathspec activates. Since the offending import is already gone (commit #2), the guard finds zero hits and stays GREEN.

### Alternative: collapse #2 + #3 into one commit

If the planner wants commit-#3-style "rename the guard in the same commit that removes the import" (D-29's literal wording), commits #2 and #3 can be merged. The trade-off is a larger reviewable diff (~100+ lines vs. 2 smaller diffs of ~80 lines each). Phase 226 used 4 plan files — Phase 231 should be 2-3 plans depending on how the planner draws the line.

### What CANNOT be reordered

- **Commit #1 MUST come before #2** — otherwise `service.py` migration has no `get_embedding_provider` to call
- **Commit #3 MUST come at-or-after #2** — otherwise the guard fires on `helpers.py:8` and CI is red

[VERIFIED via D-29 reading + Phase 226 plan-file structure inspection.]

---

## HTTP Layer / Worker Process Consumers — Confirmed Unchanged

This section closes orchestrator gap #6 ("identify any HTTP-layer or worker-process consumers that would be affected").

| Consumer | Call site | Impact |
|----------|-----------|--------|
| **Procrastinate worker** (`processing/embeddings/tasks.py`) | Calls `generate_and_store_embedding` (which calls `generate_embedding` internally) | UNCHANGED — `generate_and_store_embedding`'s signature stays identical; the embedding-generation function is the same name + signature post-migration |
| **Search service** (`modules/catalog/search/service.py:48, 262`) | `from app.processing.embeddings.service import generate_embedding, EmbeddingUnavailableError`; `query_vector = await generate_embedding(query_text, session)` | UNCHANGED — `generate_embedding(text, session) -> list[float]` signature stays the same; `EmbeddingUnavailableError` location stays in `service.py` per recommendation |
| **Settings router** (`modules/settings/router.py:112, 114, 333, 337`) | `from app.processing.embeddings.service import probe_embedding_dimensions` | UNCHANGED — `probe_embedding_dimensions(db) -> int` signature stays the same |
| **Settings router** (line 332-338) | `from app.processing.embeddings.service import (EmbeddingUnavailableError, ...)` then `except EmbeddingUnavailableError as e: raise HTTPException(...)` | UNCHANGED if `EmbeddingUnavailableError` stays in `service.py` |
| **Backfill module** (`processing/embeddings/backfill.py:16`) | `from app.processing.embeddings.service import generate_and_store_embedding` | UNCHANGED — high-level orchestrator |
| **Admin router** (`modules/admin/router.py:592, 612, 650`) | `from app.processing.embeddings.helpers import has_embeddings`, `from app.processing.embeddings.backfill import backfill_embeddings` | UNCHANGED — `has_embeddings` is provider-agnostic and stays in `helpers.py` |
| **Datasets metadata service** (`modules/catalog/datasets/domain/service_relationships.py:74-108`) | `from app.processing.embeddings.helpers import set_hnsw_recall, get_nearest_record_ids` | UNCHANGED — both functions stay in `helpers.py` |
| **Ingest tasks** (`processing/ingest/tasks.py:32`, `tasks_common.py:21`, `tasks_reupload.py:223,415`, `tasks_vrt.py:12,306`, `tasks_raster.py:323`) | `from app.processing.embeddings.helpers import defer_embedding` | UNCHANGED — `defer_embedding` is provider-agnostic and stays in `helpers.py` |

[VERIFIED: `grep -rn "from app.processing.embeddings"` returned all consumers; all signatures remain stable post-migration.]

---

## AsyncOpenAI Migration Safety — Verification

This section closes orchestrator gap #2 ("verify the `AsyncOpenAI` migration is safe").

### Phase 226 precedent — already shipped

[VERIFIED: read `defaults.py:608-818` for `DefaultOpenAICompatibleProvider`.] Phase 226 already uses `AsyncOpenAI` for `client.chat.completions.create(...)` calls — same SDK package (`openai>=2.0.0,<3` per `pyproject.toml:24`), same auth pattern (`api_key=reveal(settings.openai_api_key)`), same client construction with `httpx.Timeout`, same class-level `_clients` cache keyed by `base_url`. The `chat.completions.create` and `embeddings.create` methods share identical sync/async surface — migrating `embeddings.create` follows the exact same pattern.

### Embeddings-specific verification

[CITED: https://github.com/openai/openai-python/blob/main/api.md] The OpenAI Python SDK v2.x exposes `client.embeddings.create(model, input, dimensions, encoding_format)` on both `OpenAI` (sync) and `AsyncOpenAI` (async) classes. Awaiting `client.embeddings.create(...)` on an `AsyncOpenAI` instance returns the same `CreateEmbeddingResponse` shape as the sync call. The `dimensions` parameter is supported only on `text-embedding-3-*` models — same constraint as today (no behavior change).

### What to verify in the test suite

- `mock_provider.embed = AsyncMock(return_value=[fake_vector])` — confirmed pattern in CONTEXT.md D-27
- `await mock_provider.embed(...)` is the call shape — D-27's migration template uses `AsyncMock` correctly
- No test currently asserts on the sync `client.embeddings.create.return_value` — they assert on `result = await generate_embedding(...)` which is the service-level return [VERIFIED: read `test_embedding_service.py:14-47` — assertions are on `result`, not on the SDK client mock]

**Conclusion:** Migration is safe. The `asyncio.to_thread` overhead disappears (removes one sync→async conversion per embed call); the sync `OpenAI` client class disappears entirely from the embeddings stack. No production behavior change observable to callers; throughput marginally improves (no thread-pool hop).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Entry-points test isolation | Real package install | `patch("app.platform.extensions.entry_points", return_value=[mock_ep])` per `test_extensions.py` and `test_ai_provider_extension.py` |
| Architecture regex enforcement | Shell script | `subprocess.run(["git", "grep", ...])` per `test_layering.py:802-816` (the existing function body is reused unchanged for the renamed test) |
| Registry cleanup in tests | Manual dict surgery | `_reset_registry()` helper from `test_ai_provider_extension.py:19-28` (replicate inline; do NOT cross-import) |
| Async OpenAI client wrapping | `asyncio.to_thread(sync_client.embeddings.create, ...)` | Direct `await async_client.embeddings.create(...)` — Phase 226 precedent |
| Per-base-URL client caching | New caching scheme | Class-level `_clients: dict = {}` keyed by `base_url` — verbatim copy of Phase 226 `DefaultOpenAICompatibleProvider._clients` at `defaults.py:625` |
| Retry/backoff with jitter | New retry library | Inline `for attempt in range(1, max_attempts + 1)` loop with `asyncio.sleep(backoff * (1 + random.random() * 0.3))` — same shape as Phase 226 `_loop_anthropic`/`_loop_openai` retry, and as today's `service.py:72-110` retry |
| Exception class for provider failure | New exception hierarchy | Reuse existing `EmbeddingUnavailableError` at `service.py:27-28`; do NOT create `EmbeddingProviderError` etc. |

---

## Common Pitfalls

### Pitfall 1: Architecture guard rename ordering breaks CI

**What goes wrong:** Planner widens the pathspec from `processing/ai/` to `processing/` BEFORE removing `from openai import OpenAI` from `helpers.py:8`. The renamed test fails immediately because the offending import is still present.
**Why it happens:** Naive plan ordering — "rename the test first, then migrate." Phase 226 D-29 explicitly warns about this; Phase 231 inherits the constraint.
**How to avoid:** Use the recommended commit sequence (commit #2 removes the import, commit #3 renames the guard). At every commit boundary, run `cd backend && uv run pytest tests/test_layering.py -k architecture` locally before pushing.
**Warning signs:** `test_no_module_level_provider_sdk_imports_in_processing` fails with `Module-level provider-SDK import found in backend/app/processing/. Offending lines: backend/app/processing/embeddings/helpers.py:8: from openai import OpenAI`.

### Pitfall 2: Registry pollution from editable enterprise overlay

**What goes wrong:** `tests/test_embedding_provider_extension.py` runs without an autouse fixture, and the editable-installed enterprise overlay's entry points pollute `_extensions["embedding_providers"]` before the test's own `patch("entry_points")` mock is set up. The test asserts on overlay-registered providers leaking from another test.
**Why it happens:** Phase 226 RESEARCH.md Pitfall 6 documents this exact failure mode for `test_ai_provider_extension.py`. Phase 231 has the identical risk.
**How to avoid:** Replicate the autouse `_clean_registry()` fixture from `test_ai_provider_extension.py:31-45` verbatim in the new `test_embedding_provider_extension.py`. The fixture clears the registry, patches `entry_points` to return `[]`, yields, and clears again.
**Warning signs:** Test passes locally but fails in CI when the enterprise overlay is editable-installed in the test venv (or vice versa).

### Pitfall 3: `dimensions=None` lost in kwargs

**What goes wrong:** `DefaultOpenAIEmbeddingProvider.embed()` passes `dimensions=None` to `client.embeddings.create(...)`. The OpenAI SDK rejects `dimensions=None` as an invalid argument — it expects either an int or the parameter to be omitted entirely.
**Why it happens:** Today's `probe_embedding_dimensions` calls `client.embeddings.create(model=model, input="dimension probe")` WITHOUT a `dimensions` kwarg (line 138-145). After migration, the provider must conditionally include the kwarg.
**How to avoid:** In `embed()`, build kwargs conditionally:
```python
kwargs = {"model": model, "input": texts}
if dimensions is not None:
    kwargs["dimensions"] = dimensions
response = await client.embeddings.create(**kwargs)
```
**Warning signs:** `test_generate_embedding_dimension_mismatch` or `probe_embedding_dimensions` integration test fails with OpenAI API error like `"Invalid value for 'dimensions': null"` or 400 BadRequest.

### Pitfall 4: `EmbeddingUnavailableError` import edge from `defaults.py`

**What goes wrong:** `DefaultOpenAIEmbeddingProvider.embed()` does `from app.processing.embeddings.service import EmbeddingUnavailableError` at module level. The deferred-import discipline is violated; `defaults.py` now has a hard import edge into `processing/embeddings/`.
**Why it happens:** Convenience — putting the import at the top of `defaults.py` is one less line per method.
**How to avoid:** Place the import INSIDE `embed()` body (deferred-import discipline, mirrors Phase 226 `DefaultOpenAICompatibleProvider.complete()` at `defaults.py:651` which defers `ToolLoopExhaustedError`). The architecture-guard test does NOT catch module-level non-SDK imports — but the deferred discipline keeps `defaults.py` import-graph-clean as a project convention.
**Warning signs:** Subtle — won't fail tests directly, but breaks the layering convention. Reviewer should flag.

### Pitfall 5: Mock provider's `resolve_runtime_config` returns wrong shape

**What goes wrong:** Migrated test sets `mock_provider.resolve_runtime_config = AsyncMock(return_value={"base_url": ..., "model": ..., "dims": ...})` (with `model`/`dims` keys). The service code reads `runtime_config["default_model"]` / `runtime_config["default_dims"]` per D-04 — KeyError or `None` propagates.
**Why it happens:** Easy to mis-key the mock dict; the canonical key names are `default_model`, `default_dims`, `base_url` per D-04 and `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()`.
**How to avoid:** Use the exact canonical keys in mock fixtures:
```python
mock_provider.resolve_runtime_config = AsyncMock(return_value={
    "base_url": None,
    "default_model": "text-embedding-3-small",
    "default_dims": 1536,
})
```
**Warning signs:** `test_generate_embedding_uses_persistent_config` fails with `model is None` or `dims is None` because the service falls back to runtime_config values that don't exist.

### Pitfall 6: `runtime_config["base_url"]` is `None` when only `OPENAI_BASE_URL` is set

**What goes wrong:** `resolve_runtime_config` returns `{"base_url": None}` when neither `EMBEDDING_BASE_URL` nor `OPENAI_BASE_URL` are set in the DB. The provider's `embed()` defaults to `settings.openai_base_url or "https://api.openai.com/v1"` — but if `EMBEDDING_BASE_URL` is set in DB but `OPENAI_BASE_URL` is also set, the `EMBEDDING_BASE_URL` should win per the existing `resolve_embedding_base_url` chain.
**Why it happens:** The fallback chain `EMBEDDING_BASE_URL → OPENAI_BASE_URL → "https://api.openai.com/v1"` (helpers.py:90-97) MUST be preserved exactly inside `resolve_runtime_config()`. Subtle to get wrong.
**How to avoid:** Test the fallback chain with a unit test: when `EMBEDDING_BASE_URL.get(db) == "http://ollama:11434/v1"` and `OPENAI_BASE_URL.get(db) == "https://api.openai.com/v1"`, `resolve_runtime_config(db)["base_url"]` MUST equal `"http://ollama:11434/v1"` (the embedding-specific override).
**Warning signs:** Deployments using Ollama or a local OpenAI-compatible proxy for embeddings break silently — `generate_embedding` calls `https://api.openai.com/v1` instead of the configured proxy.

### Pitfall 7: `_clients` cache leaks across tests

**What goes wrong:** `DefaultOpenAIEmbeddingProvider._clients` is class-level. Test #1 sets up an `AsyncOpenAI(base_url="http://test1")` and caches it. Test #2 expects a fresh client at the same `base_url` but gets the cached one (with stale mock state).
**Why it happens:** Class-level cache survives across test instances. Same risk Phase 226 had at `DefaultOpenAICompatibleProvider._clients`.
**How to avoid:** Either (a) clear the cache in the autouse fixture: `DefaultOpenAIEmbeddingProvider._clients.clear()`, or (b) tests mock at the `service.get_embedding_provider` boundary (D-27 option (a)) — never reach the cache. Option (b) is preferred and is what D-27 specifies.
**Warning signs:** `test_generate_embedding_uses_persistent_config` passes alone but fails when run in sequence with `test_generate_embedding_returns_float_vector`.

### Pitfall 8: Service-level retry double-counted

**What goes wrong:** Planner moves the retry loop into `DefaultOpenAIEmbeddingProvider.embed()` (D-22) but ALSO leaves a retry loop in `service.generate_embedding()`. Two layers of retry → up to 4 attempts on transient failure, plus the SDK's own `max_retries=2` → up to 8 attempts.
**Why it happens:** Migration mechanical error — easier to leave the existing service-level loop "just in case."
**How to avoid:** D-22 is explicit: retry moves INTO the provider, OUT of the service. After migration, `service.generate_embedding` is straight-line: API key check → `provider_ext.embed()` → return. No try/except for retry purposes.
**Warning signs:** Logs show 4-8 embedding API calls per failed request instead of 2. P99 latency on transient network errors balloons.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (uv run pytest) |
| Config file | `backend/pyproject.toml` |
| Test markers | `architecture` (line 74), `perf`, `requires_ogr2ogr`, `lifecycle` — all already registered |
| Quick run command | `cd backend && uv run pytest tests/test_embedding_provider_extension.py tests/test_embedding_service.py tests/test_layering.py -x -q` |
| Full suite command | `cd backend && uv run pytest --tb=short -q` |
| Coverage gate | `fail_under = 58.5` (`pyproject.toml:84`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EMBPROV-01 | Protocol class `EmbeddingProviderExtension` exists with `embed()` and `resolve_runtime_config()` methods, `@runtime_checkable` | unit | `pytest tests/test_embedding_provider_extension.py::test_default_embedding_provider_registered -x` (asserts `isinstance(provider, EmbeddingProviderExtension)`) | ❌ Wave 0 (D-18/D-19) |
| EMBPROV-02 | `get_embedding_provider("openai_compatible")` returns `DefaultOpenAIEmbeddingProvider`; dict-shape registry | unit | `pytest tests/test_embedding_provider_extension.py::test_default_embedding_provider_registered -x` | ❌ Wave 0 (D-19) |
| EMBPROV-02b | `get_embedding_provider("nonexistent")` raises `ValueError` | unit | `pytest tests/test_embedding_provider_extension.py::test_unknown_embedding_provider_raises_value_error -x` | ❌ Wave 0 (D-20) |
| EMBPROV-03 | `from openai` removed from `processing/embeddings/`; existing embedding tests stay green | architecture + integration | `git grep -E "^(from\|import) openai" backend/app/processing/embeddings/` returns empty; `pytest tests/test_embedding_service.py -x` | ❌ helpers.py edit + D-27 mock migration |
| EMBPROV-04 | Renamed architecture guard catches reintroduced SDK imports anywhere in `processing/` | architecture | `pytest tests/test_layering.py::test_no_module_level_provider_sdk_imports_in_processing -x` | ✅ exists as `_in_processing_ai` (line 778); rename per D-13 |
| EMBPROV-04b | Negative-control verification | architecture | Manual: temporarily insert `from openai import OpenAI` at top of `helpers.py`, run `pytest tests/test_layering.py -k architecture`, confirm fail, revert | manual per D-15 |
| EMBPROV-05a | Existing 5 `test_embedding_service.py` tests stay green with mock-provider-boundary patches | unit | `pytest tests/test_embedding_service.py -x` (5 tests pass) | ✅ exists; mock migration per D-27 |
| EMBPROV-05b | Test overlay registered via `entry_points` is dispatched correctly via `embed()` | integration | `pytest tests/test_embedding_provider_extension.py::test_overlay_embedding_provider_is_dispatched -x` | ❌ Wave 0 (D-18) |
| EMBPROV-05c | Service-boundary mock tests (`test_embedding_pipeline.py`, `test_hybrid_search.py`) stay green | integration | `pytest tests/test_embedding_pipeline.py tests/test_hybrid_search.py -x` | ✅ exists; UNAFFECTED per D-28 |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_embedding_provider_extension.py tests/test_embedding_service.py tests/test_layering.py -x -q` (~5-10s; covers all phase-owned tests)
- **Per wave merge:** `cd backend && uv run pytest tests/test_embedding_provider_extension.py tests/test_embedding_service.py tests/test_embedding_pipeline.py tests/test_hybrid_search.py tests/test_layering.py tests/test_extensions.py tests/test_ai_provider_extension.py -x -q` (~30s; covers all embeddings-adjacent and Protocol-system tests)
- **Phase gate:** Full suite green (`cd backend && uv run pytest --tb=short -q`) before `/gsd-verify-work`. Baseline per STATE.md is ~2050+/2050+; Phase 231 adds ≥3 new tests (D-18/D-19/D-20)

### Nyquist Dimensions

1. **Existence** — `isinstance(get_embedding_provider("openai_compatible"), EmbeddingProviderExtension)` returns `True` (D-19)
2. **Behavior** — `DefaultOpenAIEmbeddingProvider.embed(texts=[...], model=..., dimensions=...)` returns `list[list[float]]` with same vectors as today's `client.embeddings.create(...)` (existing 5 `test_embedding_service.py` tests cover this with mocked SDK)
3. **Boundary** — `embed(texts=["x"], model=..., dimensions=None)` works (covers `probe_embedding_dimensions` migration)
4. **Data flow** — `entry_points → load_extensions() → _extensions["embedding_providers"] → get_embedding_provider("test") → provider_ext.embed()` end-to-end (D-18 test)
5. **Integration** — full backend suite 2050+/2050+ baseline maintained (SC#5)
6. **State management** — registry singleton: `get_embedding_provider("openai_compatible")` twice returns same instance
7. **Error handling** — `get_embedding_provider("unknown")` raises `ValueError("Unknown embedding provider: unknown")` (D-20)
8. **Architecture invariants** — negative-control: temporarily insert `from openai import OpenAI` in `helpers.py`, confirm renamed guard test fails (D-15)

### Wave 0 Gaps

- [ ] `backend/tests/test_embedding_provider_extension.py` — covers EMBPROV-01, EMBPROV-02, EMBPROV-02b, EMBPROV-05b (D-18/D-19/D-20)
- [ ] `backend/tests/test_layering.py` rename — `test_no_module_level_provider_sdk_imports_in_processing_ai` → `_in_processing` per D-13/D-14/D-16 (covers EMBPROV-04)
- [ ] `backend/tests/test_embedding_service.py` mock migration — 5 tests update from `service.build_openai_client` patches to `service.get_embedding_provider` patches per D-27 (covers EMBPROV-05a)
- [ ] No new test framework / config files needed; `architecture` marker already registered

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | — |
| V3 Session Management | No | — |
| V4 Access Control | No | Extension loading is startup-time, not per-request auth; admin-only PersistentConfig writes already audited |
| V5 Input Validation | No | Embedding text is upstream-validated at ingest (record metadata fields); no new user input surface |
| V6 Cryptography | No | — |
| V11 Communications Security | Marginal | `base_url` defaults to `https://api.openai.com/v1`; overlay-supplied `base_url` MUST be admin-controlled (DB write via PersistentConfig) |

### Threat Model

| Threat | STRIDE | Standard Mitigation |
|--------|--------|---------------------|
| API key leakage via overlay logs | Information Disclosure | Keys read via `reveal(settings.openai_api_key)` (env-backed, `reveal()` wrapper at `core/config.py`); Phase 231 adds no new logging of key values; the existing `logger.info("Generating embedding", model=model, dimensions=dims, text_length=len(text))` does NOT log the key (verified by reading `service.py:63-68`) |
| SSRF via overlay-controlled `base_url` | Tampering | `base_url` comes from `EMBEDDING_BASE_URL` / `OPENAI_BASE_URL` PersistentConfig (admin DB write, not user-controlled); overlays setting their own `base_url` do so through `resolve_runtime_config()` — overlays must be admin-deployed signed packages (no plugin marketplace) |
| Untrusted overlay code | Elevation of Privilege | Supply chain control: overlays are installed packages (`pip install geolens-enterprise`) signed by the operator; community edition loads nothing (empty entry-points); same model as Phase 226 |
| Embedding text exposed in logs | Information Disclosure | Existing `service.py:64` logs `text_length=len(text)` (NOT the text content); Phase 231 preserves this discipline. The provider does NOT add additional logging — retry-loop log already shadows the text by logging only `model` and `error=str(exc)` |
| API timeout DoS | Denial of Service | `asyncio.wait_for(timeout=130.0)` for embed and `30.0` for probe — preserved post-migration. The provider's class-level `_clients` cache uses `httpx.Timeout(60.0, connect=10.0)` and `max_retries=2` SDK-level. No new DoS surface |

[VERIFIED: read `service.py:63-68` (logging), `helpers.py:100-109` (timeout config), `core/config.py` (reveal pattern is reused unchanged from Phase 226).]

---

## Open Questions (RESOLVED)

1. **`EmbeddingUnavailableError` final location**
   - What we know: 4 external consumers import from `service.py`; Phase 226 precedent (`ToolLoopExhaustedError` in `llm_loop.py`) supports keeping it at the service layer
   - What was unclear: Whether the planner prioritizes layering purity (move to `extensions/exceptions.py`) or diff minimization (keep in `service.py`)
   - **RESOLVED:** Keep in `service.py`. 4 fewer files touched; provider class imports it via deferred discipline. Implemented in Plan 02 (no `EmbeddingUnavailableError` move; `defaults.py` `DefaultOpenAIEmbeddingProvider.embed()` does deferred `from app.processing.embeddings.service import EmbeddingUnavailableError` inside the method body).

2. **API key check location: service vs. provider**
   - What we know: Today the check is at `service.py:47-53` and `:122-125` (before client construction). After migration, the provider class also has the same check (per the recommended `embed()` body). Two checks for the same condition.
   - What was unclear: Whether to remove the service-level check (provider becomes the single source of truth) or keep both (defense in depth)
   - **RESOLVED:** Keep both. The service-level check provides a clear, consistent error message before any registry/provider machinery is invoked; the provider-level check defends against future overlay providers that may not check (forward-defense). Both raise the same `EmbeddingUnavailableError`. Cost: 5 lines of duplicate code per call site. Implemented in Plan 02 (service.py preserves the check; Plan 01 adds the same check inside `DefaultOpenAIEmbeddingProvider.embed()`).

3. **Existing `test_generate_embedding_raises_when_no_openai_key` test target**
   - What we know: Test patches only `service.settings` and asserts `EmbeddingUnavailableError` raised
   - What was unclear: Whether the test still passes if the API-key check is removed from service-level (case 2 recommendation rejected)
   - **RESOLVED:** Test 2 (`test_generate_embedding_raises_when_no_openai_key`) stays byte-for-byte unchanged because resolution #2 keeps the service-level check. Plan 02 explicitly leaves this test untouched; only the other 4 tests in `test_embedding_service.py` migrate to provider-boundary mocks per D-27.

---

## Environment Availability

Step 2.6: SKIPPED — phase is purely code/config changes within the existing Python backend. No new external dependencies. All required packages (`openai>=2.0.0,<3`, `httpx`, `structlog`, `sqlalchemy`) already installed in backend venv per `backend/pyproject.toml`. No CLI tools, services, or external runtimes introduced. [VERIFIED: read `backend/pyproject.toml:23-24`.]

---

## Sources

### Primary (HIGH confidence)
- `backend/app/processing/embeddings/helpers.py` — read entire file (119 lines); all 4 migration targets verified (line 8 import, line 19 cache, line 90-97 base-url resolver, line 100-109 client builder)
- `backend/app/processing/embeddings/service.py` — read entire file (357 lines); both call sites verified (`generate_embedding` lines 31-110, `probe_embedding_dimensions` lines 113-172); `EmbeddingUnavailableError` at lines 27-28 confirmed
- `backend/app/platform/extensions/protocols.py` — read entire file (152 lines); Phase 226 `AIProviderExtension` template confirmed at lines 91-152; `from __future__ import annotations` at line 11; `TYPE_CHECKING` discipline at line 18-24
- `backend/app/platform/extensions/__init__.py` — read entire file (256 lines); `get_ai_provider` accessor template confirmed at lines 224-255 (per-key `setdefault`, `ValueError` on unknown)
- `backend/app/platform/extensions/defaults.py:608-818` — read; `DefaultOpenAICompatibleProvider` template (class-level `_clients` cache at line 625, `AsyncOpenAI` import deferred at line 646, `await client.chat.completions.create(...)` async-native pattern at line 714)
- `backend/tests/test_layering.py:778-829` — read; existing architecture guard verified — pathspec at line 810, regex at line 808, carve-out paragraph at lines 789-792
- `backend/tests/test_layering.py:1-38` — read; module docstring verified; Phase 226 credit at line 14-20
- `backend/tests/test_ai_provider_extension.py:1-100` — read; `_reset_registry()` + autouse `_clean_registry` fixture pattern verified
- `backend/tests/test_embedding_service.py:1-187` — read first 60 lines; grep'd line numbers for all `patch(...)` invocations; 5 tests confirmed all mock at `service.build_openai_client` boundary
- `backend/tests/test_embedding_pipeline.py` (grep'd lines 190-307) — service-boundary mocking confirmed (4 sites at `service.generate_embedding`)
- `backend/tests/test_hybrid_search.py` (grep'd lines 242, 368, 415) — service-boundary mocking confirmed at `search.service.generate_embedding`
- `backend/pyproject.toml:23-24, 70-76, 84` — `openai>=2.0.0,<3` declared; `architecture` marker registered; `fail_under = 58.5` coverage gate
- `backend/app/core/persistent_config.py:427-456` — `OPENAI_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMS`, `EMBEDDING_BASE_URL` keys verified
- `backend/app/modules/settings/router.py:112,114,267,331-338` — consumer signatures verified unchanged
- `backend/app/modules/catalog/search/service.py:44-48,261-262` — consumer signatures verified unchanged
- `231-CONTEXT.md` — read complete (all decisions D-01..D-33; all sections); orchestrator gaps mapped to specific decisions
- `226-RESEARCH.md` — read complete; format and Validation Architecture template mirrored
- `226-CONTEXT.md` — read first ~300 lines; Phase 226 D-01..D-28 cross-referenced for canonical patterns
- `.planning/REQUIREMENTS.md §EMBPROV-01..05` — read; SC binding wording confirmed
- `.planning/ROADMAP.md §Phase 231` — read; goal + 5 success criteria + dependency-free confirmed

### Secondary (MEDIUM confidence — verified across 2+ sources)
- OpenAI Python SDK v2.x `client.embeddings.create()` API surface [CITED: Context7 fetch from `/openai/openai-python` library docs] — `model`, `input` (str | list[str]), `dimensions` (int, only `text-embedding-3-*` models), `encoding_format` parameters confirmed; same surface on sync `OpenAI` and async `AsyncOpenAI`

### Tertiary (LOW confidence — assumed)
- `@runtime_checkable` Protocol behavior for async methods in Python 3.11+ [ASSUMED] — same caveat as Phase 226 RESEARCH.md A1; behavior has been stable since Python 3.8 and the existing `AIProviderExtension` `isinstance` check works in production, so this is low risk

---

## Project Constraints (from CLAUDE.md / global)

User's global CLAUDE.md (~/.claude/CLAUDE.md) directives that apply to this phase:

- **No AI/Bot mention in commit messages** — use clean conventional commits (the existing 226 commit messages are the template)
- **Prefer simple, readable code over clever abstractions** — the migration pattern is mechanical; avoid introducing new abstractions beyond the Protocol seam
- **Follow existing project conventions when editing files** — Phase 226's `defaults.py` / `protocols.py` / `__init__.py` patterns are the law for Phase 231

Project-level CLAUDE.md is **not present** in `/Users/ishiland/Code/geolens/`. No project-skills directory at `.claude/skills/` or `.agents/skills/`. The user's global MEMORY notes "FastAPI trailing slashes" and "OGC routes" — both irrelevant to Phase 231 (sub-route-layer changes).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `@runtime_checkable` with async methods performs attribute-existence check only (not async/signature check) in Python 3.11+ | Architecture Patterns | Low — same as Phase 226 A1; verified by existing `AIProviderExtension` runtime checks passing in production |
| A2 | The four `EmbeddingUnavailableError` external consumers are exhaustive | EmbeddingUnavailableError section | Low — `grep -rn "EmbeddingUnavailableError" backend/` returned exactly 4 import sites (settings router, search service, 2 tests). New uses since the grep would be caught by mypy (if enabled — it isn't) or at test time |
| A3 | `client.embeddings.create(input=[texts])` returns embeddings in the same order as input | Provider implementation | Very low — OpenAI API contract guarantees order via `data[i].index`; the recommended provider body uses `[item.embedding for item in response.data]` which preserves order naturally. Bedrock/Vertex overlays must honor the same contract |
| A4 | `httpx.Timeout(60.0, connect=10.0)` SDK-level config is preserved by `AsyncOpenAI` constructor | Standard Stack | Low — Phase 226 `DefaultOpenAICompatibleProvider` uses identical config (`timeout=_LLM_TIMEOUT, max_retries=2`) and ships in production |

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all imports and SDK versions verified by reading actual source + pyproject.toml
- Architecture: HIGH — all extension scaffold files read; Phase 226 `AIProviderExtension` patterns confirmed; mock-target inventory programmatically grep'd
- Test mock surface: HIGH — 5 tests in `test_embedding_service.py` and 4 service-boundary mocks in pipeline/hybrid tests directly read; line numbers cited
- `EmbeddingUnavailableError` consumers: HIGH — exhaustive grep returned exactly 4 external sites
- AsyncOpenAI safety: HIGH — Phase 226 precedent in production; OpenAI SDK Context7 docs confirm async surface; same SDK package version
- Architecture-guard rename mechanics: HIGH — exact line numbers (789-792 carve-out, 808 regex, 810 pathspec) verified by direct read
- Commit sequence: HIGH — Phase 226 D-29 + 231 D-29 explicit; verified against test_layering.py current state

**Research date:** 2026-05-02
**Valid until:** Indefinite (source files are stable; no external API versioning concern within `openai>=2.0.0,<3`)
