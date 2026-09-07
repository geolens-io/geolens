"""Protocol interfaces for GeoLens extension points.

Uses only stdlib types where possible. AsyncSession is imported because
Protocol method signatures need the type and SQLAlchemy does not import
from ``app.modules.*``. ``AuditEvent`` is forward-referenced via
``TYPE_CHECKING`` to avoid loading the audit facade at Protocol import time.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.core.identity import Identity

    # Identity forward-reference quoting convention: use ``"Identity"`` for
    # required params and ``"Identity | None"`` for optional ones. Both are
    # quoted because the import only resolves under TYPE_CHECKING; a
    # runtime import would create a circular dependency with
    # app.core.identity. Keep this convention consistent across the file.
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
class AuthExtension(Protocol):
    """Extension point for additional auth methods."""

    def get_auth_methods(self) -> list[str]: ...


@runtime_checkable
class AuditSink(Protocol):
    """Write-side hook for audit event emission.

    A SIEM streamer does not change the bounded CSV and JSON export
    provided by Core.

    Enterprise overlays subscribe by appending instances to
    ``_extensions["audit_sinks"]`` in ``register_extensions(registry)`` via
    ``setdefault + append`` — overwriting the slot makes DefaultAuditSink
    disappear and breaks AUDIT-05.
    """

    async def emit(self, session: AsyncSession, event: "AuditEvent") -> None: ...


@runtime_checkable
class BillingExtension(Protocol):
    """Startup billing hook.

    Sibling to ``AuditSink``. Two orthogonal concerns: a marketplace
    metering hook doesn't subscribe to audit events; an audit sink doesn't
    fire on lifespan startup. Future overlays may implement BOTH on one
    class, but the contracts stay separate.

    Enterprise overlays subscribe by appending instances to
    ``_extensions["billing_extensions"]`` in ``register_extensions(registry)``
    via ``setdefault + append`` — overwriting the slot makes
    DefaultBillingExtension disappear and breaks the iteration shape.

    Core dispatch (api/main.py lifespan) wraps each call with
    ``asyncio.wait_for(timeout=10.0)`` plus per-extension try/except.
    Overlays do NOT need to defend against their own failures — the
    dispatch loop guarantees per-extension isolation.
    """

    async def on_startup(self, app: FastAPI) -> None: ...


@dataclass(frozen=True)
class ConnectorDefinition:
    """Public descriptor for a persistent connector implementation."""

    name: str
    display_name: str
    config_schema: dict[str, Any]
    supports_credentials: bool = False
    supports_scheduled_sync: bool = False


@dataclass(frozen=True)
class ConnectorCredentialRef:
    """Opaque reference to a stored connector credential.

    Carries no secret material. Enterprise connector overlays own the
    backing secret store and resolve the reference internally at sync time.
    """

    id: str
    connector_name: str
    display_name: str
    secret_ref: str


@dataclass(frozen=True)
class ConnectorResource:
    """Public metadata for one discoverable connector resource.

    Carries no credentials or provider client objects. ``id`` is an
    API-safe opaque handle (ASCII letters/digits plus ``._~-``), never a
    provider URL, signed locator, or credential. ``metadata`` is non-secret
    discovery metadata that core may return to an authorized caller.
    """

    id: str
    name: str
    kind: str
    metadata: dict[str, Any]


@runtime_checkable
class ConnectorExtension(Protocol):
    """Persistent connector registry seam.

    Community edition returns no connectors. Enterprise overlays can
    replace this singleton with stored-credential and scheduled-sync
    connectors without connector-specific branches in core ingest/catalog.
    """

    def list_connectors(self) -> list[ConnectorDefinition]: ...

    async def validate_config(
        self, connector_name: str, config: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def get_credential_ref(
        self,
        db: AsyncSession,
        connector_name: str,
        credential_id: str,
    ) -> ConnectorCredentialRef | None: ...

    async def discover_resources(
        self,
        db: AsyncSession,
        connector_name: str,
        credential_ref: ConnectorCredentialRef | None,
        config: dict[str, Any],
    ) -> list[ConnectorResource]: ...

    async def dispatch_ingest(
        self,
        db: AsyncSession,
        connector_name: str,
        credential_ref: ConnectorCredentialRef | None,
        resource_id: str,
        config: dict[str, Any],
        user_id: str,
    ) -> str:
        """Return an API-safe opaque job handle, never a provider URL."""
        ...


@dataclass(frozen=True)
class TableReadinessResult:
    """Result of preparing a backing table for a read request.

    ``hydrated`` means the caller may continue immediately. ``warming``
    means preparation continues asynchronously and the caller should
    return 202 with the opaque job identifier. Core doesn't know which
    storage tier or provider implements the preparation.
    """

    status: Literal["hydrated", "warming"]
    job_id: str | None = None


@runtime_checkable
class TileConcurrencyLimiter(Protocol):
    """Minimal async concurrency primitive used around a tile database read."""

    async def acquire(self) -> bool: ...

    def release(self) -> None: ...


@runtime_checkable
class DataServingExtension(Protocol):
    """Provider-neutral hooks for preparing and governing data reads.

    Community uses a no-op implementation. Hosted overlays may prepare data
    that is not immediately queryable, apply a per-tenant concurrency budget,
    and override cache policy without public core importing a private package.
    """

    async def prepare_table_for_read(
        self, *, table_name: str, tenant_id: str
    ) -> TableReadinessResult | None: ...

    def get_tile_concurrency_limiter(
        self, tenant_id: str
    ) -> TileConcurrencyLimiter | None: ...

    def get_tile_cache_control(self) -> str | None: ...


@runtime_checkable
class AIProviderExtension(Protocol):
    """LLM provider dispatch table entry.

    Replaces hardcoded ``if/elif provider == "anthropic"/"openai_compatible"``
    dispatch in ``processing/ai/`` with name-keyed extension lookup. The
    registry slot ``_extensions["ai_providers"]`` is a
    ``dict[str, AIProviderExtension]`` — dict-shape, not list-shape, because
    dispatch fans out by name at request time.

    Community defaults: ``DefaultAnthropicProvider`` (key: ``"anthropic"``),
    ``DefaultOpenAICompatibleProvider`` (key: ``"openai_compatible"``). Each
    is registered via per-key ``setdefault`` so overlay registrations win
    without overwriting un-overlaid defaults.

    Overlays add new providers (e.g., ``"bedrock"``) without modifying any
    core file::

        def register_extensions(registry: dict) -> None:
            providers = registry.setdefault("ai_providers", {})
            providers["bedrock"] = BedrockProvider()

    Forward-referenced types (``ToolLoopResult``, ``ToolExecutor``,
    ``ActionCollector``) live in ``app.processing.ai.llm_loop``; the
    ``TYPE_CHECKING`` import keeps the typing-only edge from becoming a
    runtime edge.
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

    def stream_chat_events(
        self,
        *,
        message: str,
        system_prompt: str,
        session: AsyncSession,
        user: "Identity",
        user_roles: set[str],
        layers: list[Any],
        model: str,
        base_url: str | None = None,
        history: list[dict] | None = None,
        port: Any,
        map_id: str | None = None,
        # The advertised tool set for this turn. None means the provider's
        # default chat tools; a restricted list (e.g. read-only) must be
        # honored. stream_chat_edit always passes it, so an explicit
        # signature must accept this kwarg.
        tools: list[dict] | None = None,
        # Surface-level table scope for query_data's sandbox allowlist: when
        # set, generated SQL may only touch these data.* tables (intersected
        # with the user's RBAC allowlist — narrows, never widens). None
        # keeps the user-wide allowlist. Same accept-kwarg requirement as
        # `tools` above.
        restrict_tables: frozenset[str] | None = None,
    ) -> AsyncIterator[dict[str, object]]: ...

    async def structured_complete(
        self,
        *,
        model: str,
        system_prompt: str,
        user_message: str,
        response_model: type[Any],
        base_url: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> tuple[Any, int, int]:
        """Return ``(parsed_response_model, input_tokens, output_tokens)``.

        Token counts feed per-user AI budget accounting (#402), so
        metadata-assist calls count toward the cap like map/chat do.
        """
        ...

    async def resolve_runtime_config(self, db: AsyncSession) -> dict[str, object]: ...


@runtime_checkable
class EmbeddingProviderExtension(Protocol):
    """Embedding provider dispatch table entry.

    Sibling of AIProviderExtension. Replaces the direct
    ``from openai import OpenAI`` in processing/embeddings/helpers.py with
    name-keyed extension lookup. Registry slot
    ``_extensions["embedding_providers"]`` is a
    ``dict[str, EmbeddingProviderExtension]``, dict-shape mirroring
    ``ai_providers``.

    Community default: ``DefaultOpenAIEmbeddingProvider`` (key:
    ``"openai_compatible"``). Single class — Anthropic doesn't ship an
    embeddings API, so unlike AIProviderExtension's two community
    defaults, embeddings has one.

    Overlays add new providers (e.g., ``"bedrock"``) without modifying any
    core file::

        def register_extensions(registry: dict) -> None:
            providers = registry.setdefault("embedding_providers", {})
            providers["bedrock"] = BedrockEmbeddingProvider()

    NO ``stream()`` method: embeddings are batch-only — the API returns the
    whole vector at once, unlike LLM completions which naturally
    token-stream.

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


@dataclass(frozen=True)
class RecordAudienceQuery:
    """The record a caller is asking about, at a STATED visibility.

    ``visibility`` and ``record_status`` are passed as values rather than
    read off the record, so a caller can ask the counterfactual — "who
    would be able to read this if it were private?" — a question neither
    ``filter_visible`` nor ``can_access_dataset`` can answer, since both
    take a concrete user and the answer is a set with no representative
    member.

    ``dataset_id`` / ``record_id`` / ``owner_id`` stay ``Any`` for the same
    reason ``WorkflowTransitionContext.dataset`` does — no catalog ORM
    imports at module load time. Both ids are carried because grants key
    the DATASET while visibility lives on the RECORD, so an overlay keying
    policy on either doesn't have to join.
    """

    dataset_id: Any
    record_id: Any
    owner_id: Any | None
    visibility: str
    record_status: str


@dataclass(frozen=True)
class RecordAudience:
    """Who can read a record: the signed-in half as SQL, the anonymous half as a flag.

    ``users`` is a SQLAlchemy boolean expression over the ``user_cls``
    handed to :meth:`PermissionExtension.record_audience` — a PREDICATE,
    not a result set. That lets a caller compare two audiences inside one
    statement, and lets an overlay widen with ``or_()`` rather than
    unioning queries.

    Anonymous visitors are rows in no table, so they can't appear in
    ``users`` and carry their own flag — the distinction that separates a
    public map's audience (includes them) from an internal map's (doesn't).
    """

    users: Any
    includes_anonymous: bool


@runtime_checkable
class PermissionExtension(Protocol):
    """Policy seam for permission checks and catalog visibility filtering.

    A singleton extension point for two governance chokepoints: capability
    checks in ``require_permission()`` and catalog visibility filtering in
    ``catalog/authorization.py``. Community mode uses
    ``DefaultPermissionExtension`` to preserve the current role matrix,
    admin overrides, and visibility rules. Enterprise overlays replace the
    singleton registry entry under ``"permission"`` to implement advanced
    RBAC, ABAC, or row-level filters without changing core.

    **Wrap-don't-replace (SLOT-02):** an overlay needing additive behavior
    MUST wrap the prior implementation retrieved via
    ``get_permission_extension()`` at construction time — never bare
    re-register the ``"permission"`` key (the slot-conflict guard rejects it).

    **The stored matrix does not bound ``check_permission``.**
    ``validate_permission_matrix`` refuses to persist some combinations
    (e.g. ``manage_tenants`` on any role), which reads like a statement
    about what a caller can hold. It isn't: the seam is the authority, and
    the matrix is only what the database will store. An overlay may deny a
    stored grant or add one out-of-band — that's how a fleet operator gets
    ``manage_tenants`` at all. "The matrix cannot store X, so no caller has
    X" is true of the table and false of the deployment (#1021).

    **The three methods are one policy (#1068, EXTENSION_API_VERSION 4).**
    ``filter_visible`` and ``can_access_dataset`` are a pair — the same
    rule asked of a list and of one row (#929/#930). ``record_audience`` is
    the third reading: the same rule asked about a whole audience, for a
    caller with no user to pass. An overlay that changes either of the
    first two and leaves this one on the community answer is reporting one
    policy and serving another; core can't see the disagreement, so it
    takes the conservative refusal instead.
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

    async def record_audience(
        self,
        query: RecordAudienceQuery,
        user_cls: Any,
        *,
        grant_cls: Any | None = None,
    ) -> RecordAudience:
        """Which principals can read the record described by ``query``.

        ``user_cls`` is the ORM class the returned predicate must be
        written against (core passes its ``User``); ``grant_cls`` is the
        dataset-grant class, absent when the caller has no grant table to
        offer — mirroring ``filter_visible``, where a missing ``grant_cls``
        makes a restricted record unreachable rather than ungated.

        Implementations must agree with ``filter_visible`` exactly: a user
        the predicate admits must be a user whose filtered query returns
        the record, at the visibility and status named in ``query``. Core
        proves that equivalence for the community default account by
        account and expects an overlay to hold itself to the same
        standard — an overlay whose reads reach further than the audience
        it reports strands somebody, invisibly, behind the shared-map guard.

        Async for the same reason ``can_access_dataset`` is: an overlay may
        resolve tenant/policy state before composing the predicate. The
        community default performs no I/O.
        """
        ...


@dataclass(frozen=True)
class WorkflowTransitionContext:
    """Context passed to publication workflow policy hooks.

    ``dataset`` stays ``Any`` so this platform-level contract doesn't
    import catalog ORM classes at module load time.
    """

    session: AsyncSession
    dataset: Any
    actor: "Identity | None"
    from_status: str
    to_status: str
    mode: str


@runtime_checkable
class WorkflowExtension(Protocol):
    """Policy seam for dataset publication workflow transitions.

    Community mode uses ``DefaultWorkflowExtension`` to preserve the
    existing draft -> ready -> internal -> published lifecycle. Enterprise
    overlays can replace the singleton ``"workflow"`` registry slot to add
    approval states, block transitions, or observe transitions without
    changing catalog routes.

    **Wrap-don't-replace (SLOT-02):** an overlay that needs to observe
    transitions while preserving existing behavior MUST wrap
    ``get_workflow_extension()`` at construction time — never bare
    re-register the ``"workflow"`` key.
    """

    def status_order(self) -> tuple[str, ...]: ...

    async def allowed_transitions(
        self, context: WorkflowTransitionContext
    ) -> set[str]: ...

    async def on_transition(self, context: WorkflowTransitionContext) -> None: ...


@dataclass(frozen=True)
class Notification:
    """Immutable notification payload passed to every registered NotificationSink.

    ``event_type`` identifies the event category (e.g. ``"signup"``,
    ``"ingest_done"``, ``"health_alert"``). ``subject`` and ``body`` are
    human-readable channel renderings (SMTP → email subject/body; webhook
    → JSON body text). ``data`` carries optional structured metadata for
    channel-specific rendering.
    """

    event_type: str
    subject: str
    body: str
    data: dict[str, object] | None = None


@runtime_checkable
class NotificationSink(Protocol):
    """Write-side hook for outbound notification delivery.

    Sibling to ``AuditSink``. Two orthogonal concerns: an audit SIEM
    streamer doesn't deliver outbound notifications; a notification
    channel doesn't subscribe to audit writes.

    Community edition ships a ``DefaultNotificationSink`` no-op — zero
    outbound send, zero side effects. Enterprise overlays register richer
    sinks (SMTP, webhook, Slack incoming-webhook) by appending to
    ``_extensions["notification_sinks"]`` in ``register_extensions(registry)``
    via ``setdefault + append``. DO NOT overwrite the slot — that removes
    DefaultNotificationSink from the iteration, violating the additive
    contract.

    The async signature lets enterprise overlays perform non-blocking I/O
    (SMTP STARTTLS, HTTP POST to a webhook URL); all sinks are awaited by
    ``notify()``.
    """

    async def deliver(self, notification: "Notification") -> None: ...


@runtime_checkable
class EntitlementPort(Protocol):
    """Per-tenant capability and limit enforcement seam.

    Orthogonal to ``require_enterprise()`` (binary edition gate) and to
    ``PermissionExtension`` (per-user RBAC). ``EntitlementPort`` is a
    per-TENANT tiering axis: it answers "does this tenant's plan include
    feature X?" and "has this tenant exceeded limit Y?".

    Community and Enterprise use ``DefaultEntitlementPort`` (grant-all,
    fail-OPEN). The cloud overlay registers a real implementation backed
    by the ``tenant_entitlements`` table (webhook-synced from Stripe).

    **Wrap-don't-replace (SLOT-02):** an overlay needing additive behavior
    MUST wrap the prior implementation retrieved via
    ``get_entitlement_port()`` at construction time — never bare
    re-register the ``"entitlement"`` key (the slot-conflict guard rejects it).

    Method contract:
    - ``has_feature(feature)`` — return True if the current tenant's plan
      includes the named feature; False to deny.
    - ``enforce_limit(dimension, n)`` — raise (any exception, typically
      ``HTTPException(429)`` or a domain ``LimitExceededError``) if ``n``
      exceeds the tenant's quota for ``dimension``; return ``None``
      otherwise (no raise = within limits).

    Both methods are async because cloud overlay implementations may hit
    the local ``tenant_entitlements`` table (async SQLAlchemy) or a
    short-TTL process cache backed by an async data source.
    """

    async def has_feature(self, feature: str) -> bool: ...

    async def enforce_limit(self, dimension: str, n: int) -> None: ...
