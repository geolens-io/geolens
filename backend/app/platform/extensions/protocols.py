"""Protocol interfaces for GeoLens extension points.

Uses only stdlib types where possible. AsyncSession (Phase 222 / Phase 214
precedent at ``app/core/identity.py:29``) is imported because Protocol method
signatures need the type and SQLAlchemy does not import from ``app.modules.*``.
``AuditEvent`` is forward-referenced via ``TYPE_CHECKING`` to avoid loading
the audit facade at Protocol import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.core.identity import Identity
    from app.platform.audit import AuditEvent
    from app.processing.ai.llm_loop import (
        ActionCollector,
        ToolExecutor,
        ToolLoopResult,
    )


@runtime_checkable
class BrandingExtension(Protocol):
    """Extension point for branding customization."""

    def get_branding_defaults(self) -> dict[str, object]: ...


@runtime_checkable
class AuditExtension(Protocol):
    """Extension point for audit export formats."""

    def get_export_formats(self) -> list[str]: ...


@runtime_checkable
class AuthExtension(Protocol):
    """Extension point for additional auth methods."""

    def get_auth_methods(self) -> list[str]: ...


@runtime_checkable
class AuditSink(Protocol):
    """Write-side hook for audit event emission (Phase 222 D-01).

    Sibling to ``AuditExtension`` (read-side export-format gating at
    ``audit/router.py``). Two orthogonal concerns: a SIEM streamer doesn't add
    export formats; a CSV exporter doesn't subscribe to writes. Future overlays
    may implement BOTH on one class (Phase 217 D-13 dual-Protocol pattern), but
    the contracts stay separate.

    Enterprise overlays subscribe by appending instances to
    ``_extensions["audit_sinks"]`` in their ``register_extensions(registry)``
    callback via ``setdefault + append`` (D-09 — overwriting the slot makes
    DefaultAuditSink disappear and breaks AUDIT-05).
    """

    async def emit(self, session: AsyncSession, event: "AuditEvent") -> None: ...


@runtime_checkable
class BillingExtension(Protocol):
    """Startup billing hook (Phase 223 D-06 / D-08 / D-09 / BILLING-01).

    Sibling to ``AuditSink`` (write-side audit emission, Phase 222). Two
    orthogonal concerns: a marketplace metering hook doesn't subscribe to
    audit events; an audit sink doesn't fire on lifespan startup. Future
    overlays may implement BOTH on one class (Phase 217 D-13 dual-Protocol
    pattern), but the contracts stay separate.

    Enterprise overlays subscribe by appending instances to
    ``_extensions["billing_extensions"]`` in their ``register_extensions(registry)``
    callback via ``setdefault + append`` (D-06 — overwriting the slot makes
    DefaultBillingExtension disappear and breaks the iteration shape).

    Core dispatch (api/main.py lifespan) wraps each call with
    ``asyncio.wait_for(timeout=10.0)`` + per-extension try/except (D-10).
    Overlays do NOT need to defend against their own failures — the dispatch
    loop guarantees per-extension isolation.
    """

    async def on_startup(self, app: FastAPI) -> None: ...


@runtime_checkable
class AIProviderExtension(Protocol):
    """LLM provider dispatch table entry (Phase 226 D-01 / AIEXT-01).

    Replaces hardcoded ``if/elif provider == "anthropic"/"openai_compatible"``
    dispatch in ``processing/ai/`` with name-keyed extension lookup. Registered
    via the ``geolens.extensions`` entry-point group; the registry slot is
    ``_extensions["ai_providers"]`` — a ``dict[str, AIProviderExtension]``
    (D-04, dict-shape NOT list-shape because dispatch fans out by name at
    request time).

    Community defaults: ``DefaultAnthropicProvider`` (key: ``"anthropic"``),
    ``DefaultOpenAICompatibleProvider`` (key: ``"openai_compatible"``). Each
    class is registered under its name via per-key ``setdefault`` (D-05) so
    overlay registrations win without overwriting un-overlaid defaults.

    Overlays add new providers (e.g., ``"bedrock"``, ``"vertex"``) without
    modifying any core file (SC#5)::

        def register_extensions(registry: dict) -> None:
            providers = registry.setdefault("ai_providers", {})
            providers["bedrock"] = BedrockProvider()

    Forward-referenced types (``ToolLoopResult``, ``ToolExecutor``,
    ``ActionCollector``) live in ``app.processing.ai.llm_loop``; the
    ``TYPE_CHECKING`` import keeps the typing-only edge from becoming a
    runtime edge (mirrors the ``AuditEvent`` pattern at line 18-19).
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

    async def stream(
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

    async def resolve_runtime_config(self, db: AsyncSession) -> dict[str, object]: ...


@runtime_checkable
class EmbeddingProviderExtension(Protocol):
    """Embedding provider dispatch table entry (Phase 231 D-01 / EMBPROV-01).

    Sibling of AIProviderExtension (Phase 226). Replaces the direct
    ``from openai import OpenAI`` at processing/embeddings/helpers.py:8 with
    name-keyed extension lookup. Registry slot
    ``_extensions["embedding_providers"]`` is a
    ``dict[str, EmbeddingProviderExtension]`` (D-09, dict-shape mirroring
    Phase 226 D-04).

    Community default: ``DefaultOpenAIEmbeddingProvider`` (key:
    ``"openai_compatible"``). Single class — Anthropic does not ship an
    embeddings API (cf. EmbeddingUnavailableError message at
    service.py:48-53); the AI provider has two community defaults,
    embeddings has one (D-06).

    Overlays add new providers (e.g., ``"bedrock"``, ``"vertex"``) without
    modifying any core file (SC#5)::

        def register_extensions(registry: dict) -> None:
            providers = registry.setdefault("embedding_providers", {})
            providers["bedrock"] = BedrockEmbeddingProvider()

    NO ``stream()`` method (D-03): embeddings are batch-only; streaming a
    vector makes no sense (the API returns the whole vector at once,
    unlike LLM completions which naturally token-stream).

    ``resolve_runtime_config(db)`` returns a dict with three keys:
    ``base_url``, ``default_model``, ``default_dims`` — extensible for
    Bedrock/Vertex overlays which add region/project/credential keys.
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


@runtime_checkable
class PermissionExtension(Protocol):
    """Policy seam for permission checks and catalog visibility filtering.

    Phase 232 / PERM-01 introduces a singleton extension point for two known
    governance chokepoints: capability checks in ``require_permission()`` and
    catalog visibility filtering in ``catalog/authorization.py``. Community
    mode uses ``DefaultPermissionExtension`` to preserve the current role
    matrix, admin overrides, and visibility rules. Enterprise overlays replace
    the singleton registry entry under ``"permission"`` to implement advanced
    RBAC, ABAC, or row-level filters without changing core.
    """

    async def check_permission(
        self,
        db: AsyncSession,
        user: "Identity",
        capability: str,
        *,
        user_roles: set[str],
        permission_matrix: dict[str, dict[str, bool]] | None = None,
        resource: object | None = None,
    ) -> bool: ...

    def filter_visible(
        self,
        stmt: Any,
        user: "Identity | None",
        user_roles: set[str],
        record_cls: Any,
        grant_cls: Any | None = None,
    ) -> Any: ...

    async def can_access_dataset(
        self,
        db: AsyncSession,
        dataset: Any,
        dataset_id: Any,
        user: "Identity | None",
        *,
        user_roles: set[str],
    ) -> bool: ...
