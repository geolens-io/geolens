# Phase 231: embedding-provider-extension-protocol - Pattern Map

**Mapped:** 2026-05-02
**Files analyzed:** 8 (1 new, 7 modified)
**Analogs found:** 8 / 8 (every change has a Phase 226 sibling reference)

Phase 231 has **unusually high pattern fidelity**: Phase 226 (AIProviderExtension) shipped 2026-05-01 and the embeddings-side seam is its near-identical sibling. The only material divergences are (a) one default class instead of two, (b) no `stream()` Protocol method, (c) `dimensions` on the Protocol surface (no equivalent on the AI provider). Every other shape is byte-for-byte mirrored.

---

## File Classification

| File | Role | Data Flow | Closest Analog | Match Quality |
|------|------|-----------|----------------|---------------|
| `backend/app/platform/extensions/protocols.py` (modify) | protocol-definition | N/A | `protocols.py:91-152` (`AIProviderExtension`) | exact |
| `backend/app/platform/extensions/defaults.py` (modify, append) | service / provider-impl | request-response | `defaults.py:608-818` (`DefaultOpenAICompatibleProvider`) | exact |
| `backend/app/platform/extensions/__init__.py` (modify) | accessor / registry | request-response | `__init__.py:224-255` (`get_ai_provider`) | exact (adapt to single default) |
| `backend/app/processing/embeddings/helpers.py` (modify, deletions only) | service / SDK boundary | request-response | N/A — pure deletion | none needed |
| `backend/app/processing/embeddings/service.py` (modify) | service / caller | request-response | self-analog: today's `generate_embedding` + Phase 226 caller-migration shape | self-analog |
| `backend/tests/test_layering.py` (modify) | architecture-guard test | N/A | `test_layering.py:777-829` (the test being renamed) | self-analog |
| `backend/tests/test_embedding_service.py` (modify) | unit/service test | request-response | `test_ai_provider_extension.py:1-176` (registry-mock pattern) + self (existing test bodies) | exact |
| `backend/tests/test_embedding_provider_extension.py` (NEW) | unit/integration test | request-response | `test_ai_provider_extension.py:1-176` (verbatim shape) | exact |

---

## Pattern Assignments

### `protocols.py` — add `EmbeddingProviderExtension`

**Analog:** `backend/app/platform/extensions/protocols.py:91-152` (`AIProviderExtension`)

**Module-level pattern (already in place — no change):**
```python
# protocols.py:11
from __future__ import annotations

# protocols.py:13
from typing import TYPE_CHECKING, Protocol, runtime_checkable

# protocols.py:16 — AsyncSession is the one runtime SQLAlchemy import
from sqlalchemy.ext.asyncio import AsyncSession

# protocols.py:18-24 — TYPE_CHECKING block for cross-layer types
if TYPE_CHECKING:
    from app.modules.audit.events import AuditEvent
    from app.processing.ai.llm_loop import (
        ActionCollector,
        ToolExecutor,
        ToolLoopResult,
    )
```

**Protocol class shape — copy from `protocols.py:91-152` (`AIProviderExtension`):**
```python
@runtime_checkable
class AIProviderExtension(Protocol):
    """LLM provider dispatch table entry (Phase 226 D-01 / AIEXT-01).

    Replaces hardcoded ``if/elif provider == "anthropic"/"openai_compatible"``
    dispatch in ``processing/ai/`` with name-keyed extension lookup. Registered
    via the ``geolens.extensions`` entry-point group; the registry slot is
    ``_extensions["ai_providers"]`` — a ``dict[str, AIProviderExtension]``
    (D-04, dict-shape NOT list-shape because dispatch fans out by name at
    request time).
    ...
    Forward-referenced types (``ToolLoopResult``, ``ToolExecutor``,
    ``ActionCollector``) live in ``app.processing.ai.llm_loop``; the
    ``TYPE_CHECKING`` import keeps the typing-only edge from becoming a
    runtime edge (mirrors the ``AuditEvent`` pattern at line 18-19).
    """

    async def complete(self, *, model: str, ...) -> "ToolLoopResult": ...
    async def stream(self, *, model: str, ...) -> "ToolLoopResult": ...
    async def resolve_runtime_config(self, db: AsyncSession) -> dict[str, object]: ...
```

**New Protocol to append (after line 152) — D-01..D-05 from CONTEXT.md:**
```python
@runtime_checkable
class EmbeddingProviderExtension(Protocol):
    """Embedding provider dispatch table entry (Phase 231 D-01 / EMBPROV-01).

    Sibling of AIProviderExtension (Phase 226). Replaces the direct
    ``from openai import OpenAI`` at processing/embeddings/helpers.py:8 with
    name-keyed extension lookup. Registry slot
    ``_extensions["embedding_providers"]`` is a
    ``dict[str, EmbeddingProviderExtension]`` (D-09, dict-shape mirroring
    Phase 226 D-04).

    Community default: DefaultOpenAIEmbeddingProvider (key:
    ``"openai_compatible"``). Single class — Anthropic does not ship an
    embeddings API (cf. EmbeddingUnavailableError message at
    service.py:48-53); the AI provider has two community defaults,
    embeddings has one.

    Overlays add new providers without modifying any core file (SC#5)::

        def register_extensions(registry: dict) -> None:
            providers = registry.setdefault("embedding_providers", {})
            providers["bedrock"] = BedrockEmbeddingProvider()

    NO ``stream()`` method (D-03): embeddings are batch-only; streaming a
    vector makes no sense (the API returns the whole vector at once).
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

**Differences from analog:**
- One method (`embed`) + `resolve_runtime_config`, vs. three (`complete`, `stream`, `resolve_runtime_config`) on `AIProviderExtension`. Per D-03, no `stream()`.
- `embed` uses `dimensions: int | None`, `base_url: str | None`, `timeout: float | None` kwargs — no `tools`/`tool_executor`/`temperature` (embeddings are pure transform).
- No `TYPE_CHECKING` additions needed — `embed` returns plain `list[list[float]]`, no forward-referenced types from processing/. The existing `if TYPE_CHECKING:` block at lines 18-24 stays unchanged.

**Touch points:** Append after `AIProviderExtension` (after line 152). No existing lines modified.

---

### `defaults.py` — add `DefaultOpenAIEmbeddingProvider`

**Analog:** `backend/app/platform/extensions/defaults.py:608-818` (`DefaultOpenAICompatibleProvider`) — closest match by SDK (both use `openai>=2.0.0,<3` `AsyncOpenAI`) and by class-level `_clients` cache shape

**Class-level cache pattern (`defaults.py:625, 684-692` — copy verbatim, adapt for embeddings):**
```python
# defaults.py:625
_clients: dict = {}  # class-level cache: base_url -> AsyncOpenAI

# defaults.py:684-692 — lazy keyed-client cache
effective_base_url = (
    base_url or settings.openai_base_url or "https://api.openai.com/v1"
)

if effective_base_url not in DefaultOpenAICompatibleProvider._clients:
    DefaultOpenAICompatibleProvider._clients[effective_base_url] = AsyncOpenAI(
        api_key=reveal(settings.openai_api_key),
        base_url=effective_base_url,
        timeout=_LLM_TIMEOUT,
        max_retries=2,
    )
client = DefaultOpenAICompatibleProvider._clients[effective_base_url]
```

**Deferred-import discipline (`defaults.py:642-657` — copy verbatim):**
```python
async def complete(...):
    # Deferred imports (Phase 214 discipline)
    import json

    import structlog
    from openai import AsyncOpenAI

    from app.core.config import reveal, settings
    from app.processing.ai.constants import MAX_TOOL_ROUNDS
    from app.processing.ai.llm_loop import (
        ToolLoopExhaustedError,
        ToolLoopResult,
        _LLM_TIMEOUT,
        build_history_messages,
    )
    ...
```

**`resolve_runtime_config` analog (`defaults.py:813-818`):**
```python
async def resolve_runtime_config(self, db) -> dict[str, object]:
    from app.core.persistent_config import LLM_MODEL, OPENAI_BASE_URL

    model = await LLM_MODEL.get(db)
    base_url = await OPENAI_BASE_URL.get(db) or "https://api.openai.com/v1"
    return {"base_url": base_url, "default_model": model}
```

**New class to append (after line 818) — composes today's `helpers.py:100-109` + `service.py:72-110` + `helpers.py:90-97`:**
```python
class DefaultOpenAIEmbeddingProvider:
    """Community-edition default: OpenAI-compatible embeddings (Phase 231 D-08).

    embed() body absorbs:
      - helpers.py:100-109 build_openai_client() — AsyncOpenAI client + httpx.Timeout
      - helpers.py:90-97 resolve_embedding_base_url() — folded into resolve_runtime_config()
      - service.py:72-110 retry/backoff loop (D-22, max_attempts=2, backoff=2.0+jitter)

    Class-level _clients dict cache keyed by base_url mirrors
    DefaultOpenAICompatibleProvider._clients (defaults.py:625) verbatim. Lifetime is
    process-scoped (provider instance is registered as a singleton in
    _extensions["embedding_providers"]["openai_compatible"]).

    AsyncOpenAI replaces today's sync OpenAI + asyncio.to_thread (D-25). The
    eliminated to_thread overhead matches Phase 226's DefaultOpenAICompatibleProvider
    which already uses AsyncOpenAI for the chat-completions path.

    Deferred imports (Phase 214 / Phase 222 / Phase 225 / Phase 226 discipline):
    all SDK and modules-level imports happen INSIDE embed() / resolve_runtime_config(),
    never at defaults.py module load.
    """

    _clients: dict = {}  # class-level cache: base_url -> AsyncOpenAI

    async def embed(
        self,
        *,
        texts: list[str],
        model: str,
        dimensions: int | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> list[list[float]]:
        # Deferred imports (Phase 214 discipline)
        import asyncio
        import random

        import httpx
        import structlog
        from openai import AsyncOpenAI

        from app.core.config import reveal, settings
        from app.processing.embeddings.service import EmbeddingUnavailableError
        # ^^ keeps EmbeddingUnavailableError in service.py per RESEARCH.md primary
        # finding (4 external consumers); deferred-import edge is method-body only,
        # no module-level coupling.

        log = structlog.stdlib.get_logger(__name__)

        if not settings.openai_api_key:
            raise EmbeddingUnavailableError(
                "Embedding generation requires an OpenAI-compatible API key."
            )

        effective_base_url = (
            base_url or settings.openai_base_url or "https://api.openai.com/v1"
        )

        # Lazy class-level keyed-client cache (mirrors defaults.py:684-692)
        if effective_base_url not in DefaultOpenAIEmbeddingProvider._clients:
            DefaultOpenAIEmbeddingProvider._clients[effective_base_url] = AsyncOpenAI(
                api_key=reveal(settings.openai_api_key),
                base_url=effective_base_url,
                timeout=httpx.Timeout(60.0, connect=10.0),
                max_retries=2,
            )
        client = DefaultOpenAIEmbeddingProvider._clients[effective_base_url]

        # Retry loop moved from service.py:72-110 (D-22) — max 2 attempts,
        # 2.0s backoff with up to 30% jitter, asyncio.wait_for per call.
        max_attempts = 2
        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                kwargs: dict[str, object] = {"model": model, "input": texts}
                if dimensions is not None:
                    kwargs["dimensions"] = dimensions
                response = await asyncio.wait_for(
                    client.embeddings.create(**kwargs),
                    timeout=timeout or 130.0,
                )
                return [item.embedding for item in response.data]
            except Exception as exc:  # broad: network/API/timeout
                last_exc = exc
                if attempt < max_attempts:
                    log.debug(
                        "Embedding API call failed, retrying",
                        attempt=attempt, backoff=backoff, error=str(exc), model=model,
                    )
                    await asyncio.sleep(backoff * (1 + random.random() * 0.3))
                else:
                    log.error(
                        "Embedding API call failed after retries",
                        error=str(exc), model=model, attempts=max_attempts, exc_info=True,
                    )
        raise EmbeddingUnavailableError(f"Embedding API call failed: {last_exc}") from last_exc

    async def resolve_runtime_config(self, db) -> dict[str, object]:
        from app.core.persistent_config import (
            EMBEDDING_BASE_URL,
            EMBEDDING_DIMS,
            EMBEDDING_MODEL,
            OPENAI_BASE_URL,
        )

        # Fallback chain mirrors helpers.py:90-97 byte-for-byte (D-04):
        # EMBEDDING_BASE_URL -> OPENAI_BASE_URL -> hardcoded default
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

**Differences from analog (`DefaultOpenAICompatibleProvider`):**
- No tool-format conversion (embeddings have no tools).
- No tool-loop / `max_rounds` / `for round_num in range(...)` loop — single API call, with retry/backoff wrapping it.
- `httpx.Timeout(60.0, connect=10.0)` is hardcoded inline (matches today's `helpers.py:106`); the AI provider uses `_LLM_TIMEOUT` from `llm_loop.py`. Per CONTEXT.md "Claude's Discretion", keep `httpx.Timeout` INSIDE the provider class.
- `resolve_runtime_config` returns three keys (`base_url`, `default_model`, `default_dims`) — the AI version returns two. Extra `default_dims` key supports `probe_embedding_dimensions` discovery flow (D-04).
- No `stream()` method (D-03).
- Imports `EmbeddingUnavailableError` from `service.py` (deferred). RESEARCH.md primary finding: 4 external consumers import this exception; keeping it in `service.py` minimizes diff, and the deferred-import edge is method-body only (no module-level cycle).

**Touch points:** Append after line 818 (end of `DefaultOpenAICompatibleProvider`). No existing lines modified.

---

### `__init__.py` — add `get_embedding_provider(name)` accessor

**Analog:** `backend/app/platform/extensions/__init__.py:224-255` (`get_ai_provider`) — copy verbatim, adapt to one default

**Existing accessor (`__init__.py:224-255`):**
```python
def get_ai_provider(name: str) -> "AIProviderExtension":
    """Return the named AIProviderExtension or raise ValueError (Phase 226 D-04/D-05).
    ...
    Per-key ``setdefault`` seeds the two community defaults without overwriting
    overlay registrations (D-05). If an overlay registered
    ``providers["anthropic"] = TierAwareAnthropicProvider()`` BEFORE the first
    ``get_ai_provider()`` call (during ``load_extensions()``), the seeding step
    skips that key and the overlay wins.
    ...
    """
    providers = _extensions.setdefault("ai_providers", {})
    providers.setdefault("anthropic", DefaultAnthropicProvider())
    providers.setdefault("openai_compatible", DefaultOpenAICompatibleProvider())
    if name not in providers:
        raise ValueError(f"Unknown LLM provider: {name}")
    return providers[name]  # type: ignore[return-value]
```

**Existing import block to extend (`__init__.py:15-25`, `__init__.py:34-37`):**
```python
# __init__.py:15-25 — extend defaults import
from app.platform.extensions.defaults import (
    DefaultAnthropicProvider,
    DefaultAuditExtension,
    DefaultAuditSink,
    DefaultAuthExtension,
    DefaultBillingExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,
    DefaultOpenAICompatibleProvider,
    DefaultProcessingPort,
    # ADD: DefaultOpenAIEmbeddingProvider,  # NEW (Phase 231)
)

# __init__.py:34-37 — extend TYPE_CHECKING block
if TYPE_CHECKING:
    from app.core.identity import IdentityExtension
    from app.core.processing_port import ProcessingPort
    from app.platform.extensions.protocols import AIProviderExtension
    # ADD: from app.platform.extensions.protocols import EmbeddingProviderExtension  # NEW (Phase 231)
```

**New accessor to append (after line 255) — D-09..D-11:**
```python
def get_embedding_provider(name: str) -> "EmbeddingProviderExtension":
    """Return the named EmbeddingProviderExtension or raise ValueError (Phase 231 D-09/D-10).

    Registry slot ``_extensions["embedding_providers"]`` is a
    ``dict[str, EmbeddingProviderExtension]`` — same dict-shape as
    ``ai_providers`` (Phase 226 D-04). Distinct registry from ``ai_providers``;
    the same name (``"openai_compatible"``) coexists in both because dispatch
    tables are name-scoped per extension type (D-07).

    Per-key ``setdefault`` seeds the single community default without overwriting
    overlay registrations (D-05 mirroring). If an overlay registered
    ``providers["openai_compatible"] = TierAwareEmbeddingProvider()`` BEFORE the
    first ``get_embedding_provider()`` call, the seeding step skips that key and
    the overlay wins. If an overlay registers a NEW name
    ``providers["bedrock"] = BedrockEmbeddingProvider()``, both default and
    overlay coexist. Order-safe regardless of overlay registration timing.

    Raises ``ValueError("Unknown embedding provider: {name}")`` for unknown
    names (D-11 — symmetry with get_ai_provider's "Unknown LLM provider").
    """
    providers = _extensions.setdefault("embedding_providers", {})
    providers.setdefault("openai_compatible", DefaultOpenAIEmbeddingProvider())
    if name not in providers:
        raise ValueError(f"Unknown embedding provider: {name}")
    return providers[name]  # type: ignore[return-value]
```

**Differences from analog:**
- One `setdefault` (`"openai_compatible"`) vs. two (`"anthropic"`, `"openai_compatible"`).
- Different registry key (`"embedding_providers"` vs. `"ai_providers"`).
- Different error message text (`"Unknown embedding provider"` vs. `"Unknown LLM provider"`).
- Identical structural shape: per-key setdefault, ValueError-on-miss, type:ignore comment.

**Touch points:**
- Lines 15-25: add `DefaultOpenAIEmbeddingProvider` to the defaults import block.
- Lines 34-37: add `EmbeddingProviderExtension` to the `TYPE_CHECKING` block.
- Append `get_embedding_provider` after `get_ai_provider` (after line 255).

---

### `helpers.py` — pure deletion (no analog needed)

**Lines being deleted:**
- Line 6: `import httpx` (only used by `build_openai_client` lines 100-109; remove with helper)
- Line 8: `from openai import OpenAI` — SC#3 BINDING
- Line 12: `from app.core.config import reveal, settings` (only used by `build_openai_client`; verify no other consumers in helpers.py — `set_hnsw_recall`, `has_embeddings`, `get_nearest_record_ids`, `defer_embedding` don't reference `settings` or `reveal`)
- Line 14: `from app.core.persistent_config import EMBEDDING_BASE_URL, OPENAI_BASE_URL` (only used by `resolve_embedding_base_url`)
- Line 19: `_cached_openai_clients: dict[str, OpenAI] = {}` — module-level singleton; moves to `DefaultOpenAIEmbeddingProvider._clients`
- Lines 90-97: `resolve_embedding_base_url` — folded into `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()`
- Lines 100-109: `build_openai_client` — body moves to `DefaultOpenAIEmbeddingProvider.embed()` (cache check) and class-level `_clients`

**Lines preserved (DB helpers — provider-agnostic):**
- Lines 1, 3-5, 9-10, 15-16: docstring + remaining imports (`time`, `uuid`, `structlog`, `sqlalchemy`, `RecordEmbedding`)
- Lines 21-23: `_has_embeddings_cache` short-lived cache for `has_embeddings`
- Lines 26-33: `set_hnsw_recall`
- Lines 36-51: `has_embeddings`
- Lines 54-87: `get_nearest_record_ids`
- Lines 112-119: `defer_embedding`

**Negative-control verification (D-15):** After deletion, run `git grep -nE '^(from|import) (anthropic|openai)( |$)' backend/app/processing/embeddings/` — must return zero hits. Then temporarily reintroduce `from openai import OpenAI` at the top of helpers.py, run the renamed `test_no_module_level_provider_sdk_imports_in_processing` test, confirm it fails with the offending line surfaced. Revert.

**Touch points:** Lines 6, 8, 12, 14, 19, 90-97, 100-109. The `import structlog` (line 7) stays — `defer_embedding` uses `logger`. Verify the final imports list against the preserved functions.

---

### `service.py` — migrate `generate_embedding` and `probe_embedding_dimensions`

**Self-analog:** today's `service.py:31-110` (`generate_embedding`) and `:113-172` (`probe_embedding_dimensions`)

**Caller migration shape — Phase 226 sibling pattern.** The call-site migration in Phase 226 (`service.py:660-680`, `chat_service.py:944-956`) replaced `run_tool_loop(...)` with `provider_ext.complete(...)`. Phase 231 replaces `client.embeddings.create(...)` (via `asyncio.to_thread`) with `provider_ext.embed(...)`.

**`generate_embedding` migration — D-21, D-22:**

Today's body (`service.py:55-87`):
```python
model = await EMBEDDING_MODEL.get(session)
dims = await EMBEDDING_DIMS.get(session)
base_url = await resolve_embedding_base_url(session)

# Truncate very long input
if len(text) > _MAX_INPUT_CHARS:
    text = text[:_MAX_INPUT_CHARS]

logger.info("Generating embedding", model=model, dimensions=dims, text_length=len(text))

client = build_openai_client(base_url)

max_attempts = 2
backoff = 2.0
last_exc: Exception | None = None

for attempt in range(1, max_attempts + 1):
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.embeddings.create,
                model=model, input=text, dimensions=dims,
            ),
            timeout=130.0,
        )
        return response.data[0].embedding
    except Exception as exc:
        last_exc = exc
        if attempt < max_attempts:
            await asyncio.sleep(backoff * (1 + random.random() * 0.3))
        else:
            logger.error("Embedding API call failed after retries", exc_info=True)
```

After migration:
```python
from app.platform.extensions import get_embedding_provider

provider_ext = get_embedding_provider("openai_compatible")  # D-12 hardcoded
runtime_config = await provider_ext.resolve_runtime_config(session)

model = await EMBEDDING_MODEL.get(session) or runtime_config.get("default_model")
dims = await EMBEDDING_DIMS.get(session) or runtime_config.get("default_dims")
base_url = runtime_config.get("base_url")

# Truncate very long input — STAYS in service.py (not provider responsibility)
if len(text) > _MAX_INPUT_CHARS:
    text = text[:_MAX_INPUT_CHARS]

logger.info("Generating embedding", model=model, dimensions=dims, text_length=len(text))

# Retry/backoff loop (lines 72-110) MOVES INTO provider; caller is now thin.
vectors = await provider_ext.embed(
    texts=[text],
    model=model,
    dimensions=dims,
    base_url=base_url,
    timeout=130.0,
)
return vectors[0]
```

**`probe_embedding_dimensions` migration — D-21:**

Today's distinguishing detail at `service.py:138-145`: sends NO `dimensions` kwarg to discover the model's natural vector size. After migration, pass `dimensions=None`:
```python
vectors = await provider_ext.embed(
    texts=["dimension probe"],
    model=model,
    dimensions=None,            # D-02: None means "discover natural dim size"
    base_url=base_url,
    timeout=30.0,
)
embedding = vectors[0]
if not embedding:
    raise EmbeddingUnavailableError(
        f"Embedding probe for model '{model}' returned empty vector."
    )
return len(embedding)
```

**Imports to remove from `service.py`:**
- Line 4: `import asyncio` — only used by `asyncio.wait_for(asyncio.to_thread(...))`; check if still needed for any remaining code path. (Probably remove.)
- Line 5: `import random` — only used by retry-jitter at line 98; remove.
- Lines 14-17: `from app.processing.embeddings.helpers import build_openai_client, resolve_embedding_base_url` — both helpers being deleted; replace with `from app.platform.extensions import get_embedding_provider`.

**`EmbeddingUnavailableError` location — RESEARCH.md primary finding:** stay in `service.py:27-28` (D-22 fallback option). 4 external consumers import it from this path:
- `backend/app/modules/settings/router.py:332`
- `backend/app/modules/catalog/search/service.py:47`
- `backend/tests/test_embedding_service.py:8`
- `backend/tests/test_embedding_pipeline.py:257`

Provider class imports it via deferred import inside `embed()` body (no runtime cycle).

**Pre-flight `if not settings.openai_api_key` check (`service.py:47-53`):** Recommend keep in `service.py` (defense-in-depth). The provider's `embed()` also checks (line 663-664 in `DefaultOpenAICompatibleProvider` does the same). Test `test_generate_embedding_raises_when_no_openai_key` only patches `service.settings`; keeping the service-side check preserves that test verbatim. (See test-mock migration table below.)

---

### `test_layering.py` — rename + expand architecture guard

**Self-analog:** `test_layering.py:777-829` (the test being modified)

**Function rename (line 778) — D-13:**
```python
# Today:
def test_no_module_level_provider_sdk_imports_in_processing_ai() -> None:
# After:
def test_no_module_level_provider_sdk_imports_in_processing() -> None:
```

**Docstring header (lines 779-781) — UPDATE to reference Phase 231:**
```python
# Today:
    """oc-audit 2026-05-02 §5: backend/app/processing/ai/ must not have
    module-level imports of provider SDKs (anthropic, openai).
# After:
    """oc-audit 2026-05-02 §5 + Phase 231: backend/app/processing/ must not have
    module-level imports of provider SDKs (anthropic, openai).
```

**Carve-out paragraph (lines 789-792) — DELETE per D-13:**
```python
# DELETE these 4 lines:
    Carve-out: ``processing/embeddings/helpers.py`` is excluded — the
    embeddings client is not yet covered by ``AIProviderExtension``; an
    ``EmbeddingProviderExtension`` Protocol is the planned follow-up.
    Once that ships, this exclusion can be removed.
```

**Negative-control paragraph (lines 794-797) — UPDATE to reference embeddings per D-15:**
```python
# Today:
    Negative-control: temporarily reintroduce
    ``from anthropic import AsyncAnthropic`` at the top of
    ``backend/app/processing/ai/llm_loop.py``, run this test, confirm it
    fails with the offending line surfaced. Revert.
# After (Phase 231 D-15 — the post-Phase-226 negative control):
    Negative-control (Phase 231 D-15): temporarily reintroduce
    ``from openai import OpenAI`` at the top of
    ``backend/app/processing/embeddings/helpers.py``, run this test,
    confirm it fails with the offending line surfaced. Revert.
```

**Pathspec broaden (line 810) — D-14:**
```python
# Today:
            "backend/app/processing/ai/",
# After:
            "backend/app/processing/",
```

**Failure message (line 820) — broaden the path text:**
```python
# Today:
            "Module-level provider-SDK import found in backend/app/processing/ai/. "
# After:
            "Module-level provider-SDK import found in backend/app/processing/. "
```

**Regex (line 808): UNCHANGED** — `r"^(from|import) (anthropic|openai)( |$)"` already covers both SDKs.

**Module docstring (line 1) — D-16:**
```python
# Today:
"""Layering rules across Phases 212, 213, 214, 222, 223, 224, 225, and 226.
# After:
"""Layering rules across Phases 212, 213, 214, 222, 223, 224, 225, 226, and 231.
```

**Add Phase-231 bullet to body (after the Phase 226 entry at lines 14-20):**
```python
- Phase 231 EMBPROV-04 — the Phase-226 architecture guard
  test_no_module_level_provider_sdk_imports_in_processing_ai is RENAMED
  to test_no_module_level_provider_sdk_imports_in_processing, pathspec
  broadened from backend/app/processing/ai/ to backend/app/processing/,
  and the embeddings carve-out paragraph removed from the docstring.
```

**Sequencing constraint (D-29):** This rename MUST land in the same commit as (or after) the `helpers.py:8` import removal. If pathspec is widened first, the existing import trips the test and CI fails.

---

### `test_embedding_service.py` — migrate 5 mocks per D-27

**Analogs:**
- `test_ai_provider_extension.py:1-176` (registry-mock pattern, AsyncMock for provider methods)
- Self-analog: existing test bodies — only the patch surface changes; assertions move from `mock_client_instance.embeddings.create` to `mock_provider.embed`.

**Migration template — D-27 option (a):**

Today's pattern (lines 25-37, 5x repeated):
```python
with (
    patch(
        "app.processing.embeddings.service.build_openai_client",
        return_value=mock_client_instance,
    ),
    patch("app.processing.embeddings.service.settings") as mock_settings,
    patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
    patch("app.processing.embeddings.service.EMBEDDING_DIMS") as mock_dims,
    patch(
        "app.processing.embeddings.service.resolve_embedding_base_url",
        new_callable=AsyncMock,
        return_value="",
    ),
):
    mock_settings.openai_api_key = "test-key"
    mock_model.get = AsyncMock(return_value="text-embedding-3-small")
    mock_dims.get = AsyncMock(return_value=1536)
    result = await generate_embedding("test text", mock_session)

# Assertion shape:
mock_client_instance.embeddings.create.assert_called_once_with(
    model="custom-model", input="test text", dimensions=768,
)
```

Post-migration pattern:
```python
mock_provider = MagicMock()
mock_provider.embed = AsyncMock(return_value=[fake_vector])
mock_provider.resolve_runtime_config = AsyncMock(return_value={
    "base_url": "",
    "default_model": "text-embedding-3-small",
    "default_dims": 1536,
})

with (
    patch(
        "app.processing.embeddings.service.get_embedding_provider",
        return_value=mock_provider,
    ),
    patch("app.processing.embeddings.service.settings") as mock_settings,
    patch("app.processing.embeddings.service.EMBEDDING_MODEL") as mock_model,
    patch("app.processing.embeddings.service.EMBEDDING_DIMS") as mock_dims,
):
    mock_settings.openai_api_key = "test-key"
    mock_model.get = AsyncMock(return_value="text-embedding-3-small")
    mock_dims.get = AsyncMock(return_value=1536)
    result = await generate_embedding("test text", mock_session)

# Assertion shape (provider boundary, not SDK boundary):
mock_provider.embed.assert_called_once_with(
    texts=["custom text"],
    model="custom-model",
    dimensions=768,
    base_url="",
    timeout=130.0,
)
```

**Per-test mapping — D-27 inventory:**

| Test (line) | Today's patches | Post-migration patches |
|---|---|---|
| `test_generate_embedding_returns_float_vector` (13-47) | `service.build_openai_client`, `service.resolve_embedding_base_url`, `service.settings`, `service.EMBEDDING_MODEL`, `service.EMBEDDING_DIMS` | `service.get_embedding_provider` (returns mock provider with `embed`/`resolve_runtime_config` AsyncMock), `service.settings`, `service.EMBEDDING_MODEL`, `service.EMBEDDING_DIMS` |
| `test_generate_embedding_raises_when_no_openai_key` (50-63) | `service.settings` only | UNCHANGED — keeps `if not settings.openai_api_key` check in `service.py` (defense-in-depth). Test passes verbatim. |
| `test_generate_embedding_uses_persistent_config` (65-101) | Same 5 as #1 | Same migration as #1. Assertion `mock_client_instance.embeddings.create.assert_called_once_with(model=..., input=..., dimensions=...)` migrates to `mock_provider.embed.assert_called_once_with(texts=[...], model=..., dimensions=..., base_url=..., timeout=130.0)` |
| `test_generate_embedding_truncates_long_input` (104-142) | Same 5 as #1 | Same migration. Truncation assertion (line 141) checks `mock_provider.embed.call_args.kwargs["texts"][0]` instead of `mock_client_instance.embeddings.create.call_args.kwargs["input"]` |
| `test_generate_embedding_dimension_mismatch` (145-187) | Same 5 as #1 | Same migration. Assertion at line 187 (`call_kwargs.get("dimensions") == 1536`) migrates to `mock_provider.embed.call_args.kwargs["dimensions"] == 1536` |

**Note on mock return shape:** `provider_ext.embed` returns `list[list[float]]`. The mock must return `[fake_vector]` (list-of-list), not `fake_vector` (flat list). Service code unwraps `vectors[0]`, returning a flat `list[float]` to the caller. Today's mock returns a flat vector via `mock_response.data[0].embedding`; the mock-return shape changes from `MagicMock(data=[MagicMock(embedding=fake_vector)])` to `[fake_vector]`.

---

### `test_embedding_provider_extension.py` (NEW)

**Analog:** `backend/tests/test_ai_provider_extension.py:1-176` — copy verbatim, adapt for embeddings

**Reset + autouse fixture pattern — copy `test_ai_provider_extension.py:19-45` verbatim:**
```python
def _reset_registry():
    """Reset extension registry state between tests (RESEARCH.md Pitfall 6).

    Mirrors test_extensions.py:10-15 verbatim. Replicated inline rather than
    imported to avoid inter-test-file import coupling.
    """
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate registry from environment-discovered entry points.

    The enterprise overlay is editable-installable in the backend test venv;
    that install adds ``geolens.extensions`` entry points which would
    otherwise pollute the registry whenever a test calls ``load_extensions()``.
    Patch ``entry_points`` to default-empty so each test starts from a
    known-empty discovery surface and can opt in to its own mock entry
    points via ``with patch(...)`` (Phase 226 RESEARCH.md Pitfall 6).
    """
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()
```

**Default smoke test — copy `test_ai_provider_extension.py:48-77` shape, adapt to one default — D-19:**
```python
def test_default_embedding_provider_registered():
    """D-19 / EMBPROV-02 smoke: get_embedding_provider returns DefaultOpenAIEmbeddingProvider."""
    from app.platform.extensions import get_embedding_provider
    from app.platform.extensions.defaults import DefaultOpenAIEmbeddingProvider

    provider = get_embedding_provider("openai_compatible")
    assert isinstance(provider, DefaultOpenAIEmbeddingProvider)

    # Verify Protocol satisfaction (runtime_checkable per D-05)
    from app.platform.extensions.protocols import EmbeddingProviderExtension
    assert isinstance(provider, EmbeddingProviderExtension)

    # Singleton stability — two calls return SAME instance (registry singleton)
    assert get_embedding_provider("openai_compatible") is provider
```

**Unknown-provider test — copy `test_ai_provider_extension.py:80-94` verbatim, adapt message — D-20:**
```python
def test_unknown_embedding_provider_raises_value_error():
    """D-20 / D-11: unknown name raises ValueError with exact message."""
    from app.platform.extensions import get_embedding_provider

    with pytest.raises(ValueError, match=r"^Unknown embedding provider: bedrock$"):
        get_embedding_provider("bedrock")

    with pytest.raises(ValueError, match=r"^Unknown embedding provider: $"):
        get_embedding_provider("")
```

**Entry-points dispatch test — copy `test_ai_provider_extension.py:97-175` shape verbatim, adapt for `embed` — D-18, SC#5 BINDING:**
```python
@pytest.mark.asyncio
async def test_overlay_embedding_provider_is_dispatched():
    """D-18 / SC#5 / EMBPROV-05 binding: overlay registered via
    importlib.metadata entry_points is dispatched correctly without
    modifying any core file.

    Exercises the FULL chain: entry_points() discovery ->
    register_extensions(registry) callback -> get_embedding_provider(name)
    accessor -> provider.embed(...) async dispatch -> returned vectors.
    """
    from app.platform.extensions import get_embedding_provider, load_extensions

    captured_kwargs: dict = {}

    class TestEmbeddingProvider:
        async def embed(self, *, texts, model, dimensions=None, base_url=None, timeout=None):
            captured_kwargs.update({
                "texts": texts, "model": model, "dimensions": dimensions,
                "base_url": base_url, "timeout": timeout,
            })
            return [[0.1] * (dimensions or 1536) for _ in texts]

        async def resolve_runtime_config(self, db):
            return {
                "base_url": None,
                "default_model": "test-emb-model",
                "default_dims": 1536,
            }

    def register(registry: dict) -> None:
        providers = registry.setdefault("embedding_providers", {})
        providers["test_embedding_provider"] = TestEmbeddingProvider()

    mock_ep = MagicMock()
    mock_ep.name = "geolens.embedding-providers.test"
    mock_ep.load.return_value = register

    with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
        load_extensions()
        provider_ext = get_embedding_provider("test_embedding_provider")
        vectors = await provider_ext.embed(
            texts=["hello"], model="test-emb-model", dimensions=1536,
        )
        assert len(vectors) == 1
        assert len(vectors[0]) == 1536
        assert captured_kwargs["model"] == "test-emb-model"
        assert captured_kwargs["dimensions"] == 1536

    # Verify community default still resolves correctly even though we
    # added an overlay (registry coexistence — D-05 setdefault discipline).
    from app.platform.extensions.defaults import DefaultOpenAIEmbeddingProvider
    with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
        load_extensions()
        assert isinstance(
            get_embedding_provider("openai_compatible"),
            DefaultOpenAIEmbeddingProvider,
        )
```

**Module docstring (line 1):**
```python
"""Tests for EmbeddingProviderExtension Protocol, registry seeding, and entry-points dispatch.

Phase 231 D-18 (entry-points overlay test) + D-19 (default smoke test) +
D-20 (ValueError on unknown provider name).

Maps to EMBPROV-01 (Protocol exists), EMBPROV-02 (default registered via accessor),
EMBPROV-05 (overlay-registered providers dispatch correctly via importlib.metadata
entry_points). The architecture-guard test in test_layering.py covers EMBPROV-03
and EMBPROV-04.
"""
```

**Differences from analog (`test_ai_provider_extension.py`):**
- Single default class to verify, not two (D-06 / D-19).
- `embed()` dispatch instead of `complete()`, no `tools`/`tool_executor` kwargs.
- Sentinel return is `[[0.1] * 1536]` (list-of-list) not `ToolLoopResult(text=...)`.
- Error message regex `"Unknown embedding provider"` not `"Unknown LLM provider"`.

---

## Shared Patterns

### Deferred-Import Discipline
**Source:** `defaults.py:62-76` (`DefaultAuditSink.emit`), `defaults.py:642-657` (`DefaultOpenAICompatibleProvider.complete`)
**Apply to:** `DefaultOpenAIEmbeddingProvider.embed()` and `DefaultOpenAIEmbeddingProvider.resolve_runtime_config()`

All imports of `openai`, `httpx`, `app.core.config`, `app.core.persistent_config`, and `app.processing.embeddings.service` (for `EmbeddingUnavailableError`) go INSIDE method bodies, not at `defaults.py` module level. Preserves `platform/extensions/` no-modules-at-import-time discipline (Phase 214).

### `@runtime_checkable` on Every Protocol
**Source:** `protocols.py:27, 34, 41, 48, 67, 91` (`BrandingExtension`, `AuditExtension`, `AuthExtension`, `AuditSink`, `BillingExtension`, `AIProviderExtension`)
**Apply to:** `EmbeddingProviderExtension` (D-05). Negligible cost; enables `isinstance(provider_ext, EmbeddingProviderExtension)` for future overlay debugging. Existing pattern across all 6 Protocols.

### Per-Key `setdefault` for Default Seeding
**Source:** `__init__.py:250-252` (`get_ai_provider`)
**Apply to:** `get_embedding_provider` — single `setdefault("openai_compatible", DefaultOpenAIEmbeddingProvider())` instead of two. Order-safe regardless of overlay registration timing (D-10 / Phase 226 D-05).

### Class-Level `_clients` Dict Cache (keyed by `base_url`)
**Source:** `defaults.py:625, 684-692` (`DefaultOpenAICompatibleProvider._clients`)
**Apply to:** `DefaultOpenAIEmbeddingProvider._clients` (D-26). Same `dict[str, AsyncOpenAI]` shape, same lazy-create-on-first-use, same lifetime (process-scoped via singleton provider instance).

### Registry Reset in Tests (autouse fixture)
**Source:** `test_extensions.py:10-34` (`_reset_registry` + `_clean_registry`); replicated verbatim at `test_ai_provider_extension.py:19-45`
**Apply to:** `test_embedding_provider_extension.py` — replicate the fixture inline (do NOT import from `test_extensions.py` or `test_ai_provider_extension.py`; replicate to avoid inter-test-file import coupling, per Phase 226 RESEARCH.md Pitfall 6).

### Architecture-Guard Helpers (`_has_git_metadata`, `_has_pathspec_magic`, `subprocess.run` with `git grep`)
**Source:** `test_layering.py` (top-of-file helpers, used by all `@pytest.mark.architecture` tests including the one being renamed)
**Apply to:** Renamed `test_no_module_level_provider_sdk_imports_in_processing` — these helpers are reused unchanged. No new helpers needed.

### `@pytest.mark.architecture` Marker
**Source:** `backend/pyproject.toml` (already registered; used at `test_layering.py:777`)
**Apply to:** Renamed test stays under the same marker. No new marker needed (D-17).

### Entry-Points Mock Pattern
**Source:** `test_extensions.py:32, 49-65` and `test_ai_provider_extension.py:140-156` — `with patch("app.platform.extensions.entry_points", return_value=[mock_ep]): load_extensions()`
**Apply to:** `test_embedding_provider_extension.py::test_overlay_embedding_provider_is_dispatched` (D-18). Mock entry_point's `.load.return_value` is a callable taking the registry dict; the callable does `registry.setdefault("embedding_providers", {})["test_name"] = TestEmbeddingProvider()`.

### Migration Sequencing — Architecture-Guard Rename Last (D-29)
**Source:** Phase 226 D-11 + Phase 231 D-29
**Apply to:** Commit ordering. The rename of `test_no_module_level_provider_sdk_imports_in_processing_ai` (which widens its pathspec) MUST land in the same commit as (or after) the `helpers.py:8` `from openai import OpenAI` removal. If the pathspec widens first, the existing import trips the renamed test and CI fails. Default plan order: (1) introduce Protocol + default + accessor (additive only); (2) migrate callers + remove helpers.py provider artifacts; (3) rename test + add new entry-points test.

---

## No Analog Found

No files require pure-research patterns. Every change has a concrete codebase analog (Phase 226 sibling shipped 2026-05-01).

| Concern | Why no analog needed |
|---------|----------------------|
| `helpers.py` deletions | Pure removal — the deleted code's destination (the `DefaultOpenAIEmbeddingProvider` class) gets its analog from `DefaultOpenAICompatibleProvider` |
| `EmbeddingUnavailableError` location | RESEARCH.md primary finding settled this: stay in `service.py` (D-22 fallback), 4 external consumers preserved, deferred-import edge from provider class is method-body only |
| `dimensions: int | None` Protocol kwarg | New surface, but trivially extensible — no analog needed; `AIProviderExtension.complete` has analogous optional kwargs (`max_rounds`, `base_url`, `temperature`) |

---

## Line-Number Reference (Read-First Block Inputs)

| File | Lines | Change Type |
|------|-------|-------------|
| `protocols.py` | append after 152 | Add `EmbeddingProviderExtension` Protocol |
| `defaults.py` | append after 818 | Add `DefaultOpenAIEmbeddingProvider` class |
| `__init__.py` | 15-25, 34-37, append after 255 | Extend imports + TYPE_CHECKING + add `get_embedding_provider` accessor |
| `helpers.py` | 6, 8, 12, 14, 19, 90-97, 100-109 | DELETE (httpx import, openai import, settings import, persistent_config imports, module cache, `resolve_embedding_base_url`, `build_openai_client`) |
| `service.py` | 4-5, 14-17, 31-110, 113-172 | Migrate imports + `generate_embedding` body + `probe_embedding_dimensions` body |
| `test_layering.py` | 1, 14-20 (add bullet), 778, 779-781, 789-792 (DELETE), 794-797, 810, 820 | Module docstring + function rename + docstring updates + carve-out delete + pathspec broaden + failure-message broaden |
| `test_embedding_service.py` | 13-47, 65-101, 104-142, 145-187 | Migrate 4 of 5 tests from `service.build_openai_client`/`resolve_embedding_base_url` to `service.get_embedding_provider`. (Test at lines 50-63 unchanged.) |
| `test_embedding_provider_extension.py` | NEW (~140 lines) | Module docstring + `_reset_registry` + autouse `_clean_registry` fixture + 3 tests (default smoke, unknown ValueError, entry-points dispatch) |

---

## Metadata

**Analog search scope:** `backend/app/platform/extensions/`, `backend/app/processing/embeddings/`, `backend/tests/`
**Files read:** `protocols.py` (full, 153 lines), `__init__.py` (full, 256 lines), `defaults.py` (lines 1-100, 600-818), `helpers.py` (full, 120 lines), `service.py` (full, 357 lines), `test_layering.py` (lines 1-50, 770-829), `test_ai_provider_extension.py` (full, 175 lines), `test_extensions.py` (lines 1-70), `test_embedding_service.py` (full, 187 lines)
**Pattern extraction date:** 2026-05-02
