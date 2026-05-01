# Phase 226: ai-provider-extension-protocol - Pattern Map

**Mapped:** 2026-05-01
**Files analyzed:** 9 files (1 new, 8 modified)
**Analogs found:** 9 / 9

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `protocols.py` (modify) | protocol-definition | N/A | `protocols.py:43-83` (`AuditSink`, `BillingExtension`) | exact |
| `defaults.py` (modify) | service / provider-impl | request-response | `defaults.py:46-96` (`DefaultAuditSink`, `DefaultBillingExtension`) + `defaults.py:98-391` (`DefaultProcessingPort` — deferred-import discipline) | exact |
| `__init__.py` (modify) | accessor / registry | request-response | `__init__.py:197-218` (`get_processing_port()`) | exact (adapt to dict-keyed) |
| `llm_loop.py` (modify) | orchestration utility | request-response | `llm_loop.py:82-163` (`run_tool_loop` — the function being deleted/shrunk) | self-analog |
| `service.py` (modify) | service / caller | request-response | `service.py:660-715, 741-806` (`generate_map_from_prompt`, `stream_generate_map`) | self-analog |
| `chat_service.py` (modify) | service / caller | request-response | `chat_service.py:944-957` (`chat_edit_map`) | self-analog |
| `sql_generator.py` (modify) | service / caller | request-response | `sql_generator.py:351-379` (`generate_sql` dispatch block) | self-analog |
| `tools.py` (modify) | utility / constants | N/A | `tools.py:313-323` (`CHAT_TOOLS_OPENAI` derivation) | self-analog |
| `test_layering.py` (modify) | architecture-guard test | N/A | `test_layering.py:423-491` (`test_no_log_action_calls_outside_audit_service`) | exact |
| `test_ai_provider_extension.py` (new) | unit/integration test | request-response | `test_extensions.py:1-90` (entire file — autouse fixture + dispatch tests) | exact |

---

## Pattern Assignments

### `protocols.py` — add `AIProviderExtension` Protocol

**Analog:** `protocols.py:43-83` (`AuditSink`, `BillingExtension`)

**Existing Protocol block pattern** (`protocols.py:43-83`):
```python
# protocols.py:11 — already present; no change needed
from __future__ import annotations

# protocols.py:18-19 — TYPE_CHECKING forward-ref pattern for cross-layer types
if TYPE_CHECKING:
    from app.modules.audit.events import AuditEvent

# protocols.py:43-59 — AuditSink Protocol template (mirror for AIProviderExtension docstring)
@runtime_checkable
class AuditSink(Protocol):
    """Write-side hook for audit event emission (Phase 222 D-01).
    ...
    Enterprise overlays subscribe by appending instances to
    ``_extensions["audit_sinks"]`` in their ``register_extensions(registry)``
    callback via ``setdefault + append`` (D-09 — overwriting the slot makes
    DefaultAuditSink disappear and breaks AUDIT-05).
    """
    async def emit(self, session: AsyncSession, event: "AuditEvent") -> None: ...
```

**New Protocol to add** (D-01..D-03, D-07, D-09):
```python
# Add TYPE_CHECKING block for ToolLoopResult — mirrors AuditEvent pattern at line 18-19
if TYPE_CHECKING:
    from app.processing.ai.llm_loop import (
        ActionCollector,
        ToolExecutor,
        ToolLoopResult,
    )

@runtime_checkable
class AIProviderExtension(Protocol):
    """LLM provider dispatch table entry (Phase 226 D-01 / AIEXT-01).

    Replaces hardcoded ``if/elif provider == "anthropic"/"openai_compatible"``
    dispatch in ``processing/ai/``. Registered via ``geolens.extensions``
    entry-point group under ``_extensions["ai_providers"]`` dict-key
    (D-04 — dict-shape, not list-shape like AuditSink).

    Community providers: ``DefaultAnthropicProvider`` ("anthropic"),
    ``DefaultOpenAICompatibleProvider`` ("openai_compatible"). Overlays add
    new names (e.g., "bedrock") without modifying core files (SC#5).
    """

    async def complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        tools: list[dict],
        tool_executor: "ToolExecutor",
        action_collector: "ActionCollector | None" = None,
        history: "list[dict] | None" = None,
        max_rounds: int = ...,
        max_tokens: int = 4096,
        base_url: "str | None" = None,
        temperature: float = 0.5,
    ) -> "ToolLoopResult": ...

    async def stream(self, **kwargs) -> "ToolLoopResult": ...

    async def resolve_runtime_config(self, db) -> dict[str, object]: ...
```

**Touch points:** append after `BillingExtension` (line 83). Add `ToolLoopResult`/`ToolExecutor`/`ActionCollector` to the `if TYPE_CHECKING:` block (after line 19 — or create a second `if TYPE_CHECKING:` block). No other lines touched.

---

### `defaults.py` — add `DefaultAnthropicProvider` + `DefaultOpenAICompatibleProvider`

**Analog:** `defaults.py:46-96` (deferred-import discipline from `DefaultAuditSink` and `DefaultBillingExtension`); `defaults.py:98-150` (`DefaultProcessingPort` larger-class pattern)

**Deferred-import pattern** (`defaults.py:62-76`):
```python
# defaults.py:62-76 — canonical deferred import inside method body
async def emit(self, session, event) -> None:
    # Deferred import: log_action lives in app.modules.audit.service.
    # extensions/ is platform-level and should not pull modules-level
    # imports at module load (Phase 214 deferred-import discipline).
    from app.modules.audit.service import log_action

    await log_action(...)
```

**Module-level imports to add** at top of `defaults.py` (after `from __future__ import annotations`):
```python
# NO top-level SDK imports — follow deferred-import discipline.
# anthropic / openai imports go INSIDE complete() method bodies.
```

**`DefaultAnthropicProvider` shape** (body is `_loop_anthropic` moved verbatim from `llm_loop.py:179-277`):
```python
class DefaultAnthropicProvider:
    """Community-edition default: Anthropic native tool-calling loop (Phase 226 D-17).

    complete() body moved from llm_loop._loop_anthropic (lines 179-277).
    Deferred imports: anthropic SDK, get_anthropic_client, add_tool_cache_control,
    build_history_messages all loaded inside complete() body (Phase 214 discipline).

    Client cache: class-level _client = None (RESEARCH.md §Client Cache Lifetime).
    """

    _client = None  # class-level: survives test registry resets

    async def complete(self, *, model, system_prompt, user_message, tools,
                       tool_executor, action_collector=None, history=None,
                       max_rounds=..., max_tokens=4096, base_url=None,
                       temperature=0.5):
        # Deferred imports (Phase 214 discipline)
        from app.core.config import reveal, settings
        from app.processing.ai.llm_loop import (
            ToolLoopResult, ToolLoopExhaustedError,
            add_tool_cache_control, build_history_messages,
        )
        # anthropic SDK
        import anthropic
        # ... body is _loop_anthropic verbatim (llm_loop.py:192-277)

    async def stream(self, **kwargs):
        raise NotImplementedError(
            "DefaultAnthropicProvider.stream() not implemented in community edition; "
            "use complete()"
        )

    async def resolve_runtime_config(self, db) -> dict[str, object]:
        from app.core.persistent_config import LLM_MODEL
        model = await LLM_MODEL.get(db)
        return {"base_url": None, "default_model": model}
```

**`DefaultOpenAICompatibleProvider` shape** (body is `_loop_openai` moved verbatim from `llm_loop.py:280-404`):
```python
class DefaultOpenAICompatibleProvider:
    """Community-edition default: OpenAI-compatible tool-calling loop (Phase 226 D-17).

    complete() body moved from llm_loop._loop_openai (lines 280-404).
    Tool format conversion: Anthropic-shape input → OpenAI function format
    inline (D-08 canonical Anthropic shape).
    """

    _clients: dict = {}  # class-level dict keyed by base_url

    async def complete(self, *, model, system_prompt, user_message, tools, ...):
        # Tool format conversion (D-08): Anthropic-shape → OpenAI function format
        tools_openai = [
            {"type": "function", "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }}
            for t in tools
        ]
        # ... body is _loop_openai verbatim (llm_loop.py:294-404)

    async def resolve_runtime_config(self, db) -> dict[str, object]:
        from app.core.persistent_config import LLM_MODEL, OPENAI_BASE_URL
        model = await LLM_MODEL.get(db)
        base_url = await OPENAI_BASE_URL.get(db) or "https://api.openai.com/v1"
        return {"base_url": base_url, "default_model": model}
```

**Touch points in `defaults.py`:** append both classes at end of file (after line 391 — end of `DefaultProcessingPort`). No existing lines modified.

**Tool conversion pattern** (`tools.py:313-323` — already-working derivation):
```python
# tools.py:313-323 — the conversion list comprehension the OpenAI provider replicates:
CHAT_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],  # JSON Schema shared verbatim
        },
    }
    for tool in CHAT_TOOLS_ANTHROPIC
]
```

---

### `__init__.py` — add `get_ai_provider(name)` accessor

**Analog:** `__init__.py:197-218` (`get_processing_port()`) — adapt from single-slot to dict-keyed

**Existing single-slot pattern** (`__init__.py:197-218`):
```python
def get_processing_port() -> "ProcessingPort":
    """..."""
    ext = _extensions.get("processing_port")
    if ext is None:
        return DefaultProcessingPort()
    return ext  # type: ignore[return-value]
```

**New dict-keyed accessor** (D-04, D-05, D-06):
```python
def get_ai_provider(name: str) -> "AIProviderExtension":
    """Return the named AIProviderExtension or raise ValueError (Phase 226 D-04/D-05).

    Registry slot ``_extensions["ai_providers"]`` is a ``dict[str, AIProviderExtension]``.
    Per-key setdefault seeds community defaults without overwriting overlay registrations.
    Overlays register via ``registry.setdefault("ai_providers", {})["bedrock"] = BedrockProvider()``.
    """
    providers = _extensions.setdefault("ai_providers", {})
    providers.setdefault("anthropic", DefaultAnthropicProvider())
    providers.setdefault("openai_compatible", DefaultOpenAICompatibleProvider())
    if name not in providers:
        raise ValueError(f"Unknown LLM provider: {name}")
    return providers[name]  # type: ignore[return-value]
```

**Touch points in `__init__.py`:**
- Import block (lines 15-23): add `DefaultAnthropicProvider`, `DefaultOpenAICompatibleProvider`
- `if TYPE_CHECKING:` block (lines 32-34): add `from app.platform.extensions.protocols import AIProviderExtension`
- Append `get_ai_provider` after `get_processing_port` (after line 218)

---

### `llm_loop.py` — shrink/delete dispatch bodies, migrate `resolve_provider`

**Lines being removed/replaced:**
- `run_tool_loop` body: lines 117-149 (the `if provider == "anthropic"` / `elif` dispatch + else-raise) — shrinks to `get_ai_provider(provider).complete(...)` one-liner OR entire function deleted and 3 callers updated
- `_loop_anthropic`: lines 179-277 — body moves to `DefaultAnthropicProvider.complete()`; function deleted
- `_loop_openai`: lines 280-404 — body moves to `DefaultOpenAICompatibleProvider.complete()`; function deleted
- `resolve_provider` lines 160-161 (`if provider == "openai_compatible"`: base_url branch) — replaced by `provider_ext.resolve_runtime_config(db)` call per D-10

**`resolve_provider` before** (`llm_loop.py:152-162`):
```python
async def resolve_provider(db) -> tuple[str, str, str | None]:
    provider = await LLM_PROVIDER.get(db)
    model = await LLM_MODEL.get(db)
    base_url = None
    if provider == "openai_compatible":           # <-- dispatch site #2, SC#3 target
        base_url = await OPENAI_BASE_URL.get(db) or "https://api.openai.com/v1"
    return provider, model, base_url
```

**`resolve_provider` after** (D-10, D-21):
```python
async def resolve_provider(db) -> tuple[str, str, dict[str, object]]:
    """Returns (provider_name, model, runtime_config). runtime_config["base_url"] replaces old base_url arg."""
    from app.platform.extensions import get_ai_provider
    name = await LLM_PROVIDER.get(db)
    provider_ext = get_ai_provider(name)
    runtime_config = await provider_ext.resolve_runtime_config(db)
    model = await LLM_MODEL.get(db) or runtime_config.get("default_model", "")
    return name, model, runtime_config
```

**Remaining in `llm_loop.py` after migration:** `ToolLoopResult` dataclass (lines 72-79), `ToolExecutor`/`ActionCollector` type aliases (lines 54-56), `ToolLoopExhaustedError` class (lines 59-61), `build_history_messages` (lines 165-176), `resolve_provider` (updated), and optionally `get_anthropic_client`/`get_openai_client` if kept as module shims for `streaming.py`/`sql_generator.py` import compatibility.

---

### `service.py` — migrate 3 `run_tool_loop` callers + `_retry_parse_map_spec`

**Dispatch site: `_retry_parse_map_spec`** (`service.py:383-413`, touching line 394):
```python
# BEFORE (service.py:394-411) — dispatch site #3:
if provider == "anthropic":
    client = get_anthropic_client()
    response = await client.messages.create(model=model, max_tokens=1024, ...)
    ...
else:
    base = base_url or ...
    client = get_openai_client(base)
    response = await client.chat.completions.create(...)
    ...

# AFTER (D-19, note: complete(tools=[], max_rounds=1) covers the no-tools case):
from app.platform.extensions import get_ai_provider
provider_ext = get_ai_provider(provider)
result = await provider_ext.complete(
    model=model,
    system_prompt="",
    user_message=extraction_prompt,
    tools=[],
    tool_executor=_noop_executor,   # max_rounds=1 exits before any tool call
    max_rounds=1,
    max_tokens=1024,
    base_url=runtime_config.get("base_url"),
)
retry_text = result.text
```

**Dispatch site: `generate_map_from_prompt`** (`service.py:660-684`, caller at line 668):
```python
# BEFORE (service.py:660, 668-680):
provider, model, base_url = await resolve_provider(session)
...
result = await run_tool_loop(
    provider=provider, model=model, ...,
    tools_anthropic=ANTHROPIC_TOOLS,
    tools_openai=OPENAI_TOOLS,
    ..., base_url=base_url,
)

# AFTER (D-19, D-20, D-21):
provider, model, runtime_config = await resolve_provider(session)
provider_ext = get_ai_provider(provider)
result = await provider_ext.complete(
    model=model, ...,
    tools=ANTHROPIC_TOOLS,    # single canonical format (D-08)
    ...,
    base_url=runtime_config.get("base_url"),
)
```

**Dispatch site: `stream_generate_map`** (`service.py:741, 768-781`):
Same migration as `generate_map_from_prompt` — `resolve_provider` unpack changes from `(provider, model, base_url)` to `(provider, model, runtime_config)`, `run_tool_loop(...)` → `provider_ext.complete(...)`, `tools_anthropic`/`tools_openai` → `tools=ANTHROPIC_TOOLS`.

---

### `chat_service.py` — migrate `chat_edit_map` caller

**Dispatch site** (`chat_service.py:934, 944-956`):
```python
# BEFORE (chat_service.py:934, 944-956):
provider, model, base_url = await resolve_provider(session)
...
result = await run_tool_loop(
    provider=provider, model=model, ...,
    tools_anthropic=CHAT_TOOLS_ANTHROPIC,
    tools_openai=CHAT_TOOLS_OPENAI,
    ..., base_url=base_url,
)

# AFTER (D-19, D-20, D-21):
provider, model, runtime_config = await resolve_provider(session)
provider_ext = get_ai_provider(provider)
result = await provider_ext.complete(
    model=model, ...,
    tools=CHAT_TOOLS_ANTHROPIC,    # canonical format (D-08)
    ...,
    base_url=runtime_config.get("base_url"),
)
```

---

### `sql_generator.py` — migrate `generate_sql` dispatch (lines 351, 355)

**Dispatch sites** (`sql_generator.py:351-379`):
```python
# BEFORE:
if provider == "anthropic":
    ...sql = await _call_anthropic(prompt, question, model)
elif provider == "openai_compatible":
    base_url = await OPENAI_BASE_URL.get(db) or "..."
    sql = await _call_openai(prompt, question, model, base_url)
else:
    raise ValueError(...)

# AFTER (RESEARCH.md Recommendation §Open Question 3):
from app.platform.extensions import get_ai_provider
provider_ext = get_ai_provider(provider)
# sql_generator uses system_prompt + user_message, no tools, temp=0.0, LLM_MODEL_LIGHT
result = await provider_ext.complete(
    model=model,          # LLM_MODEL_LIGHT, resolved by caller already
    system_prompt=prompt,
    user_message=question,
    tools=[],
    tool_executor=_noop_executor,
    max_rounds=1,
    max_tokens=2048,
    temperature=0.0,
    base_url=runtime_config.get("base_url"),  # needs resolve_provider or direct OPENAI_BASE_URL read
)
sql = result.text
```

Note: `sql_generator.py` currently calls `LLM_PROVIDER.get(db)` and `LLM_MODEL_LIGHT.get(db)` directly (not via `resolve_provider`). Post-migration it can either: (a) continue resolving both independently + call `get_ai_provider(provider)` directly, or (b) use a new helper that returns `(provider_ext, model_light)`. Option (a) is simpler — keep the existing `LLM_PROVIDER.get(db)` + `LLM_MODEL_LIGHT.get(db)` calls, add `get_ai_provider(provider)` lookup, delete `_call_anthropic`/`_call_openai` helpers (lines 382-415+). Also needs `OPENAI_BASE_URL.get(db)` for `base_url` in the `complete()` call.

---

### `tools.py` — remove dead OpenAI-format constants

**Lines at risk** (`tools.py:313-323` and wherever `TOOLS_OPENAI` is defined):
After callers collapse to `tools=ANTHROPIC_TOOLS` / `tools=CHAT_TOOLS_ANTHROPIC`, grep `TOOLS_OPENAI` and `CHAT_TOOLS_OPENAI` across `backend/app/` — if no references remain, delete. The derivation pattern at lines 313-323 confirms they are purely mechanical conversions with no custom logic.

---

### `test_layering.py` — add `test_no_hardcoded_ai_provider_branches`

**Analog:** `test_layering.py:423-491` (`test_no_log_action_calls_outside_audit_service`) — copy verbatim, change 4 things

**Module docstring** (line 1): extend credits list to include `Phase 226`.

**New test** (append after line 491):
```python
@pytest.mark.architecture
def test_no_hardcoded_ai_provider_branches() -> None:
    """Phase 226 AIEXT-03/05: no ``if provider ==`` dispatch in processing/.

    SC#3 binding: grep -RE "if .*provider *== *['\"](anthropic|openai_compatible)"
    backend/app/processing/ai/ must return zero hits after migration.

    Excluded paths:
      - backend/tests/ — test fixtures may stub provider names
      - backend/app/platform/extensions/defaults.py — provider classes defined here;
        dict keys (e.g., "anthropic") appear as string literals, not if-branches
      - backend/app/processing/ai/streaming.py — true-streaming SSE path deferred
        per RESEARCH.md §Open Question 1; scope of future structured_complete() work
      - backend/app/processing/ai/metadata_service.py — structured-output API path
        deferred per RESEARCH.md §Open Question 2
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 226 AIEXT-03 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)",
            "--",
            "backend/app/processing/",
            ":!backend/tests/",
            ":!backend/app/platform/extensions/defaults.py",
            ":!backend/app/processing/ai/streaming.py",
            ":!backend/app/processing/ai/metadata_service.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 226 AIEXT-03 invariant violated: hardcoded AI provider dispatch "
            "found in processing/. Replace with get_ai_provider(name).complete(...). "
            f"Offending lines:\n{result.stdout}"
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

**Key differences from the analog (`test_no_log_action_calls_outside_audit_service`):**
1. Regex: `r"if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)"` (not `\bawait log_action\(`)
2. Pathspec scope: `backend/app/processing/` (not `backend/app/`)
3. Additional pathspec exclusions for `streaming.py` and `metadata_service.py` (RESEARCH.md deferred scope)
4. Fail message names `get_ai_provider(name).complete(...)` as the fix

---

### `test_ai_provider_extension.py` (NEW)

**Analog:** `test_extensions.py:1-90` — copy autouse fixture + mock-entry-point shape verbatim

**File structure:**
```python
"""Tests for AIProviderExtension Protocol, registry seeding, and entry-points dispatch.

Phase 226 D-15 (entry-points overlay test) + D-16 (smoke test) + D-06 (ValueError).
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest


def _reset_registry():
    """Reset extension registry state between tests."""
    import app.platform.extensions as ext_mod
    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate registry — mirrors test_extensions.py:18-34 exactly."""
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()


def test_default_providers_registered():
    """D-16: get_ai_provider returns the correct community-default class for each name."""
    from app.platform.extensions import get_ai_provider
    from app.platform.extensions.defaults import (
        DefaultAnthropicProvider,
        DefaultOpenAICompatibleProvider,
    )
    assert isinstance(get_ai_provider("anthropic"), DefaultAnthropicProvider)
    assert isinstance(get_ai_provider("openai_compatible"), DefaultOpenAICompatibleProvider)


def test_unknown_provider_raises_value_error():
    """D-06: unknown name raises ValueError with exact message."""
    from app.platform.extensions import get_ai_provider
    with pytest.raises(ValueError, match="Unknown LLM provider: bedrock"):
        get_ai_provider("bedrock")


@pytest.mark.asyncio
async def test_overlay_provider_is_dispatched():
    """D-15 / SC#5: overlay registered via entry_points is dispatched correctly."""
    from app.platform.extensions import get_ai_provider, load_extensions
    from app.processing.ai.llm_loop import ToolLoopResult

    class TestProvider:
        async def complete(self, **kwargs):
            return ToolLoopResult(text="from-test-provider", actions=[])
        async def stream(self, **kwargs):
            raise NotImplementedError
        async def resolve_runtime_config(self, db):
            return {"base_url": None, "default_model": "test-model-1"}

    def register(registry):
        providers = registry.setdefault("ai_providers", {})
        providers["test_provider"] = TestProvider()

    mock_ep = MagicMock()
    mock_ep.name = "geolens.ai-providers.test"
    mock_ep.load.return_value = register

    with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
        load_extensions()
        provider_ext = get_ai_provider("test_provider")
        result = await provider_ext.complete(
            model="test-model-1", system_prompt="", user_message="hi",
            tools=[], tool_executor=lambda n, i: {}, max_rounds=1,
        )
        assert result.text == "from-test-provider"


def test_registry_singleton_stable():
    """State management: two calls to get_ai_provider return the same instance."""
    from app.platform.extensions import get_ai_provider
    p1 = get_ai_provider("anthropic")
    p2 = get_ai_provider("anthropic")
    assert p1 is p2
```

---

## Shared Patterns

### Deferred-Import Discipline
**Source:** `defaults.py:62-76` (`DefaultAuditSink.emit`)
**Apply to:** Both `DefaultAnthropicProvider.complete()` and `DefaultOpenAICompatibleProvider.complete()`

All imports of `anthropic`, `openai`, `app.core.config`, and `app.processing.ai.llm_loop` go INSIDE the method body, not at `defaults.py` module level. This preserves the `platform/extensions/` → no-modules-at-import-time discipline.

### `_has_git_metadata()` / `_has_pathspec_magic()` Guards
**Source:** `test_layering.py` (lines ~380-410 — used by all existing arch tests)
**Apply to:** `test_no_hardcoded_ai_provider_branches` — copy the two skip-guard calls verbatim, identical to lines 453-459 of the `test_no_log_action_calls_outside_audit_service` pattern.

### Registry Reset in Tests
**Source:** `test_extensions.py:10-34` (`_reset_registry` + `_clean_registry` autouse fixture)
**Apply to:** `test_ai_provider_extension.py` — replicate entire autouse fixture (do NOT import from `test_extensions.py`; replicate inline to avoid inter-test-file import coupling).

### `resolve_provider` Tuple Unpack (all 4 callers — MUST ALL CHANGE)
**Source:** `llm_loop.py:152-162` (`resolve_provider` definition)
**Apply to:** `service.py:660`, `service.py:741`, `chat_service.py:934` — all three must change `provider, model, base_url = await resolve_provider(session)` to `provider, model, runtime_config = await resolve_provider(session)` and extract `runtime_config.get("base_url")` where `base_url` was used. RESEARCH.md Pitfall 3 flags missing any as a silent bug.

---

## No Analog Found (Structural Decisions Only)

| File / Concern | Reason |
|----------------|--------|
| `AIProviderExtension.complete()` dict-keyed dispatch | New shape (D-04); list-shape analogs exist but intentionally not used |
| `streaming.py:516,531` | Deferred — pathspec-excluded from architecture guard per RESEARCH.md Open Question 1 |
| `metadata_service.py:255,291` | Deferred — pathspec-excluded from architecture guard per RESEARCH.md Open Question 2 |
| `_noop_executor` for `complete(tools=[], max_rounds=1)` | Planner must define: `async def _noop_executor(name, args): return {}` — or simply pass `lambda n, i: {}` |

---

## Line-Number Reference (Dispatch Sites for `<read_first>` blocks)

| File | Lines | Change Type |
|------|-------|-------------|
| `llm_loop.py` | 82-163 | Delete `run_tool_loop`; update `resolve_provider` (152-162) |
| `llm_loop.py` | 179-277 | Move `_loop_anthropic` body → `DefaultAnthropicProvider.complete()` |
| `llm_loop.py` | 280-404 | Move `_loop_openai` body → `DefaultOpenAICompatibleProvider.complete()` |
| `service.py` | 383-413 | Migrate `_retry_parse_map_spec` (dispatch at line 394) |
| `service.py` | 660-715 | Migrate `generate_map_from_prompt` (run_tool_loop at 668) |
| `service.py` | 741-806 | Migrate `stream_generate_map` (run_tool_loop at ~769) |
| `chat_service.py` | 934-956 | Migrate `chat_edit_map` (run_tool_loop at 944) |
| `sql_generator.py` | 351-361 | Migrate `generate_sql` dispatch; delete `_call_anthropic`/`_call_openai` (382-415+) |
| `tools.py` | 313-323 | Delete `CHAT_TOOLS_OPENAI` if unreferenced after D-20; verify `TOOLS_OPENAI` too |
| `test_layering.py` | 1 (docstring) | Add Phase 226 credit |
| `test_layering.py` | append after 491 | New `test_no_hardcoded_ai_provider_branches` |

---

## Metadata

**Analog search scope:** `backend/app/platform/extensions/`, `backend/app/processing/ai/`, `backend/tests/`
**Files read:** `protocols.py`, `defaults.py` (lines 1-150), `__init__.py` (lines 1-219), `llm_loop.py` (lines 1-405), `service.py` (lines 380-415, 650-806), `chat_service.py` (lines 928-980), `sql_generator.py` (lines 330-415), `test_extensions.py` (lines 1-90), `test_layering.py` (lines 1-30, 418-491)
**Pattern extraction date:** 2026-05-01
