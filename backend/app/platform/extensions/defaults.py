"""Community-edition default implementations of extension protocols."""

from __future__ import annotations


class DefaultBrandingExtension:
    """Default branding: shows community badge."""

    def get_branding_defaults(self) -> dict[str, object]:
        return {"show_badge": True}


class DefaultAuditExtension:
    """Default audit: no additional export formats."""

    def get_export_formats(self) -> list[str]:
        return []


class DefaultAuthExtension:
    """Default auth: no additional auth methods."""

    def get_auth_methods(self) -> list[str]:
        return []


class DefaultIdentityExtension:
    """Default identity: no alternate backend registered (Phase 214 D-14).

    Returning None from ``resolve_identity_from_token`` signals the auth
    dep chain (``get_optional_user`` / ``get_current_user``, retyped in
    Plan 02) to fall through to the existing JWT decode + DB lookup path.
    Community edition behavior is exactly today's behavior — one async
    method call returning None per request.

    The async signature is intentional (Pitfall 8). Enterprise auth
    overlays may perform DB lookups; the dep wire-in does
    ``await ext.resolve_identity_from_token(token, request, db)``, so
    all implementations — community and enterprise — MUST be async.
    """

    async def resolve_identity_from_token(self, token, request, db):  # type: ignore[no-untyped-def]
        return None


class DefaultAuditSink:
    """Community-edition default: writes one audit_logs row via log_action().

    log_action() is preserved as an internal helper (Phase 222 D-04 / AUDIT-02
    option a). Application code does NOT call log_action() directly post-Phase-222;
    only this sink does.

    Does NOT swallow exceptions internally (D-07) — only the audit_emit() facade
    swallows. Internal swallowing would silently lose session.flush() constraint
    failures that today's tests expect to surface.

    The async signature is intentional: enterprise overlays may perform non-blocking
    I/O (S3 PutObject, SIEM HTTP POST). All sinks — community and enterprise — are
    awaited by ``audit_emit()``.
    """

    async def emit(self, session, event) -> None:  # type: ignore[no-untyped-def]
        # Deferred import: log_action lives in app.modules.audit.service.
        # extensions/ is platform-level and should not pull modules-level
        # imports at module load (Phase 214 deferred-import discipline).
        from app.modules.audit.service import log_action

        await log_action(
            session,
            user_id=event.user_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details=event.details,
            ip_address=event.ip_address,
        )


class DefaultBillingExtension:
    """Community-edition default — no-op startup hook (Phase 223 D-07 / BILLING-01).

    Mirrors ``DefaultIdentityExtension``: an async no-op that lets the dispatch
    loop iterate over a non-empty ``[DefaultBillingExtension()]`` list when no
    overlay is registered. Empty-list-as-default would also work but breaks
    symmetry with the four existing single-slot Protocols (each has a
    ``Default*`` class).

    The async signature is intentional (D-08): enterprise overlays may perform
    non-blocking I/O (HTTP calls to billing APIs, async DB writes for audit).
    All extensions — community and enterprise — are awaited by the lifespan
    dispatch loop (Plan 02).
    """

    async def on_startup(self, app) -> None:  # type: ignore[no-untyped-def]
        return


class DefaultProcessingPort:
    """Community-edition default: delegates every call to app.modules.catalog.*
    via deferred imports (Phase 225 D-09 / D-11 / PROCESS-01).

    Each method does a deferred import into app.modules.catalog.* inside the
    function body, keeping platform/extensions/ free of module-load-time
    modules.* edges (Phase 214 deferred-import discipline). Behavior is
    identical to the pre-Phase-225 baseline — the Port is the seam, not a
    re-implementation.

    create_dataset, get_dataset etc. delegate via the
    app.modules.catalog.datasets.domain.service FACADE (never the sub-modules
    directly — Phase 224 DECOUPLE-04).
    """

    # -------------------------------------------------------------------------
    # Read-side methods (D-06)
    # -------------------------------------------------------------------------

    async def get_dataset(self, session, dataset_id):  # type: ignore[no-untyped-def]
        # Explicit joinedload(Dataset.record) on the Port surface so callers can
        # rely on `dataset.record.<attr>` access in async contexts without
        # depending on the facade's implicit loading semantics. The facade today
        # also eager-loads, but pinning the contract here protects callers (e.g.
        # processing/export/router.py:95 reads dataset.record.title) from any
        # future facade-internal change that drops the joinedload.
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.modules.catalog.datasets.domain.models import Dataset

        stmt = (
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
        result = await session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_record(self, session, record_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.modules.catalog.datasets.domain.models import Record

        stmt = (
            select(Record)
            .where(Record.id == record_id)
            .options(joinedload(Record.keywords))
        )
        result = await session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def search_datasets(self, session, user, user_roles, filters):  # type: ignore[no-untyped-def]
        from app.modules.catalog.search.service import search_datasets

        return await search_datasets(session, user, user_roles, filters)

    def apply_visibility_filter(
        self, stmt, user, user_roles, record_cls, grant_cls=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import apply_visibility_filter

        return apply_visibility_filter(stmt, user, user_roles, record_cls, grant_cls)

    async def check_dataset_access(
        self, session, dataset, dataset_id, user, *, user_roles=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import check_dataset_access

        return await check_dataset_access(
            session, dataset, dataset_id, user, user_roles=user_roles
        )

    async def get_user_roles(self, session, user):  # type: ignore[no-untyped-def]
        from app.modules.catalog.authorization import get_user_roles

        return await get_user_roles(session, user)

    async def get_column_stats(
        self, session, table_name, column_name, *, class_count=5, allowed_tables=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import get_column_stats

        return await get_column_stats(
            session,
            table_name,
            column_name,
            class_count=class_count,
            allowed_tables=allowed_tables,
        )

    async def get_distinct_values(
        self, session, table_name, column_name, limit=100, *, allowed_tables=None
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.column_stats import get_distinct_values

        return await get_distinct_values(
            session,
            table_name,
            column_name,
            limit=limit,
            allowed_tables=allowed_tables,
        )

    def extract_bbox(self, dataset):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.utils import extract_bbox

        return extract_bbox(dataset)

    # -------------------------------------------------------------------------
    # OQ-3 InstrumentedAttribute encapsulators
    # -------------------------------------------------------------------------

    async def get_records_without_embeddings(self, session, *, force=False):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.modules.catalog.datasets.domain.models import Record
        from app.processing.embeddings.models import RecordEmbedding

        stmt = (
            select(Record)
            .outerjoin(RecordEmbedding, Record.id == RecordEmbedding.record_id)
            .options(joinedload(Record.keywords))
            .order_by(Record.created_at)
        )
        if not force:
            stmt = stmt.where(RecordEmbedding.id.is_(None))
        result = await session.execute(stmt)
        return list(result.unique().scalars().all())

    async def get_datasets_meta_by_ids(self, session, ids):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from app.modules.catalog.datasets.domain.models import Dataset

        stmt = select(Dataset.id, Dataset.table_name, Dataset.geometry_type).where(
            Dataset.id.in_(ids)
        )
        result = await session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def get_catalog_vocabulary(self, session):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from app.modules.catalog.datasets.domain.models import RecordKeyword

        stmt = select(RecordKeyword.keyword).distinct()
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_keywords_for_records(self, session, record_ids):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from app.modules.catalog.datasets.domain.models import RecordKeyword

        if not record_ids:
            return []

        stmt = (
            select(RecordKeyword.keyword)
            .where(RecordKeyword.record_id.in_(record_ids))
            .distinct()
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_record_keyword_count(self, session, record_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import func, select

        from app.modules.catalog.datasets.domain.models import RecordKeyword

        stmt = select(func.count()).where(RecordKeyword.record_id == record_id)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_attribute_metadata(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from app.modules.catalog.datasets.domain.models import AttributeMetadata

        stmt = select(AttributeMetadata).where(
            AttributeMetadata.dataset_id == dataset_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_dataset_version(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select

        from app.modules.catalog.collections.models import DatasetVersion

        stmt = (
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version_number.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # -------------------------------------------------------------------------
    # Write-side methods (D-07)
    # -------------------------------------------------------------------------

    async def create_dataset(
        self,
        session,
        table_name,
        title,
        created_by,
        *,
        summary=None,
        visibility="private",
        ingestion=None,
    ):  # type: ignore[no-untyped-def]
        # Delegates via facade — never service_create.py directly (DECOUPLE-04).
        from app.modules.catalog.datasets.domain.service import create_dataset

        return await create_dataset(
            session,
            table_name=table_name,
            title=title,
            created_by=created_by,
            summary=summary,
            visibility=visibility,
            ingestion=ingestion,
        )

    async def create_map(self, session, name, description, created_by, notes=None):  # type: ignore[no-untyped-def]
        from app.modules.catalog.maps.service import create_map

        return await create_map(session, name, description, created_by, notes)

    async def update_map(self, session, map_id, **kwargs):  # type: ignore[no-untyped-def]
        from app.modules.catalog.maps.service import update_map

        return await update_map(session, map_id, **kwargs)

    def create_ingestion_result(self, **kwargs):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.schemas import IngestionResult

        return IngestionResult(**kwargs)

    # -------------------------------------------------------------------------
    # Source preview helper (D-08)
    # -------------------------------------------------------------------------

    def build_gdal_source(
        self,
        service_type,
        base_url,
        layer_name,
        layer_id=None,
        token=None,
        order_field=None,
        result_limit=None,
    ):  # type: ignore[no-untyped-def]
        from app.modules.catalog.sources.preview import build_gdal_source

        return build_gdal_source(
            service_type,
            base_url,
            layer_name,
            layer_id=layer_id,
            token=token,
            order_field=order_field,
            result_limit=result_limit,
        )

    # -------------------------------------------------------------------------
    # ORM class helpers (Plan 02 — returned by Port so processing/* callers
    # can pass the concrete class to apply_visibility_filter without importing
    # from app.modules.catalog.* at top-of-file; deferred-import discipline)
    # -------------------------------------------------------------------------

    def get_record_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import Record

        return Record

    def get_grant_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import DatasetGrant

        return DatasetGrant

    def get_dataset_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import Dataset

        return Dataset

    def get_dataset_version_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.collections.models import DatasetVersion

        return DatasetVersion

    def get_record_distribution_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import RecordDistribution

        return RecordDistribution

    def get_attribute_metadata_orm_class(self):  # type: ignore[no-untyped-def]
        from app.modules.catalog.datasets.domain.models import AttributeMetadata

        return AttributeMetadata

    # -------------------------------------------------------------------------
    # Dataset-with-attributes loader (Plan 02 — preserves joinedload semantics
    # that metadata_service._build_dataset_context requires; Pitfall 2)
    # -------------------------------------------------------------------------

    async def get_dataset_with_attributes(self, session, dataset_id):  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from app.modules.catalog.datasets.domain.models import Dataset, Record

        stmt = (
            select(Dataset)
            .options(
                joinedload(Dataset.record).joinedload(Record.keywords),
                joinedload(Dataset.attributes),
            )
            .where(Dataset.id == dataset_id)
        )
        result = await session.execute(stmt)
        return result.unique().scalar_one_or_none()


class DefaultAnthropicProvider:
    """Community-edition default: Anthropic native tool-calling loop (Phase 226 D-17).

    ``complete()`` body is ``_loop_anthropic`` from
    ``app.processing.ai.llm_loop`` (lines 179-277) moved verbatim — same
    request/response shape, same exit conditions, same token accounting.
    ``stream()`` raises NotImplementedError (D-03 — true LLM-token streaming
    is deferred; ``service.py:stream_generate_map`` is "semi-streaming"
    around ``complete()``, not real token streams).

    Class-level ``_client`` cache survives test registry resets (RESEARCH.md
    §Client Cache Lifetime) and is process-scoped in production (the
    accessor calls ``providers.setdefault(...)`` so the instance lives for
    the FastAPI process lifetime).

    Deferred imports (Phase 214 / Phase 222 / Phase 225 discipline): all
    SDK and modules-level imports happen INSIDE ``complete()``, never at
    defaults.py module load.
    """

    _client = None  # class-level cache (AsyncAnthropic | None)

    async def complete(  # type: ignore[no-untyped-def]
        self,
        *,
        model,
        system_prompt,
        user_message,
        tools,
        tool_executor,
        action_collector=None,
        history=None,
        max_rounds=None,
        max_tokens=4096,
        base_url=None,
        temperature=0.5,
    ):
        # Deferred imports (Phase 214 discipline)
        import json

        import structlog
        from anthropic import AsyncAnthropic

        from app.core.config import reveal, settings
        from app.processing.ai.constants import MAX_TOOL_ROUNDS
        from app.processing.ai.llm_loop import (
            ToolLoopExhaustedError,
            ToolLoopResult,
            _LLM_TIMEOUT,
            add_tool_cache_control,
            build_history_messages,
        )

        log = structlog.stdlib.get_logger(__name__)

        if max_rounds is None:
            max_rounds = MAX_TOOL_ROUNDS

        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")

        # Lazy class-level client cache
        if DefaultAnthropicProvider._client is None:
            DefaultAnthropicProvider._client = AsyncAnthropic(
                api_key=reveal(settings.anthropic_api_key),
                timeout=_LLM_TIMEOUT,
                max_retries=2,
            )
        client = DefaultAnthropicProvider._client

        messages = build_history_messages(history)
        messages.append({"role": "user", "content": user_message})

        # Enable prompt caching for system prompt and tools
        cached_system = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        cached_tools = add_tool_cache_control(tools)

        collected_actions: list[dict] = []
        total_input = 0
        total_output = 0

        for round_num in range(max_rounds):
            # Anthropic API rejects `tools=[]` with 400 BadRequestError
            # ("tools: must have at least 1 item"). Omit the kwarg entirely
            # for no-tools paths (sql_generator.generate_sql,
            # _retry_parse_map_spec). REVIEW.md CR-01.
            create_kwargs: dict[str, object] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": cached_system,
                "messages": messages,
            }
            if cached_tools:
                create_kwargs["tools"] = cached_tools
            response = await client.messages.create(**create_kwargs)

            # Track token usage
            if hasattr(response, "usage") and response.usage:
                total_input += response.usage.input_tokens
                total_output += response.usage.output_tokens

            log.info(
                "LLM round",
                provider="anthropic",
                round=round_num + 1,
                stop_reason=response.stop_reason,
                input_tokens=response.usage.input_tokens if response.usage else 0,
                output_tokens=response.usage.output_tokens if response.usage else 0,
            )

            if response.stop_reason == "end_turn":
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                return ToolLoopResult(
                    text=text,
                    actions=collected_actions,
                    input_tokens=total_input,
                    output_tokens=total_output,
                )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        log.info("Tool call", tool=block.name, input=block.input)

                        result = await tool_executor(block.name, block.input)

                        if action_collector:
                            action = action_collector(block.name, block.input, result)
                            if action:
                                collected_actions.append(action)

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result),
                            }
                        )

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — return whatever text we have
            text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return ToolLoopResult(
                text=text,
                actions=collected_actions,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        raise ToolLoopExhaustedError("Max tool rounds exceeded without final response")

    async def stream(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError(
            "DefaultAnthropicProvider.stream() not implemented in community "
            "edition; use complete() (Phase 226 D-03 — true LLM-token "
            "streaming is deferred to a follow-up phase)."
        )

    async def resolve_runtime_config(self, db) -> dict[str, object]:  # type: ignore[no-untyped-def]
        from app.core.persistent_config import LLM_MODEL

        model = await LLM_MODEL.get(db)
        return {"base_url": None, "default_model": model}


class DefaultOpenAICompatibleProvider:
    """Community-edition default: OpenAI-compatible tool-calling loop (Phase 226 D-17).

    ``complete()`` body is ``_loop_openai`` from
    ``app.processing.ai.llm_loop`` (lines 280-404) moved verbatim, with
    Anthropic→OpenAI tool format conversion applied INTERNALLY at the top
    of the method (D-08 — callers pass canonical Anthropic shape; the
    provider converts on the way in).

    Class-level ``_clients`` dict cache keyed by ``base_url`` matches
    today's module-level singleton at llm_loop.py:29.

    Deferred imports (Phase 214 / Phase 222 / Phase 225 discipline): all
    SDK and modules-level imports happen INSIDE ``complete()``, never at
    defaults.py module load.
    """

    _clients: dict = {}  # class-level cache: base_url -> AsyncOpenAI

    async def complete(  # type: ignore[no-untyped-def]
        self,
        *,
        model,
        system_prompt,
        user_message,
        tools,
        tool_executor,
        action_collector=None,
        history=None,
        max_rounds=None,
        max_tokens=4096,
        base_url=None,
        temperature=0.5,
    ):
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
        from app.processing.ai.tool_call_parser import parse_xml_tool_calls

        log = structlog.stdlib.get_logger(__name__)

        if max_rounds is None:
            max_rounds = MAX_TOOL_ROUNDS

        if not settings.openai_api_key:
            raise ValueError("OpenAI-compatible API key not configured")

        # D-08: Anthropic-shape tools -> OpenAI function-format tools.
        # Mirrors tools.py:313-323 algorithmic conversion.
        tools_openai = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

        effective_base_url = (
            base_url or settings.openai_base_url or "https://api.openai.com/v1"
        )

        # Lazy class-level keyed-client cache
        if effective_base_url not in DefaultOpenAICompatibleProvider._clients:
            DefaultOpenAICompatibleProvider._clients[effective_base_url] = AsyncOpenAI(
                api_key=reveal(settings.openai_api_key),
                base_url=effective_base_url,
                timeout=_LLM_TIMEOUT,
                max_retries=2,
            )
        client = DefaultOpenAICompatibleProvider._clients[effective_base_url]

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(build_history_messages(history))
        messages.append({"role": "user", "content": user_message})

        collected_actions: list[dict] = []
        total_input = 0
        total_output = 0

        for round_num in range(max_rounds):
            # OpenAI API rejects `tools=[]` similarly. Omit when empty so
            # no-tools paths (sql_generator.generate_sql, _retry_parse_map_spec)
            # work for OpenAI-compatible providers too. REVIEW.md CR-01.
            create_kwargs: dict[str, object] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
            }
            if tools_openai:
                create_kwargs["tools"] = tools_openai
            response = await client.chat.completions.create(**create_kwargs)

            choice = response.choices[0]

            # Track token usage
            if response.usage:
                total_input += response.usage.prompt_tokens
                total_output += response.usage.completion_tokens

            log.info(
                "LLM round",
                provider="openai",
                round=round_num + 1,
                finish_reason=choice.finish_reason,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
            )

            if choice.finish_reason == "stop":
                text = choice.message.content or ""
                parsed_calls, cleaned_text = parse_xml_tool_calls(text)

                if parsed_calls:
                    # Execute parsed XML tool calls
                    for fn_name, fn_args in parsed_calls:
                        log.info("Parsed XML tool call", tool=fn_name, input=fn_args)
                        result = await tool_executor(fn_name, fn_args)
                        if action_collector:
                            action = action_collector(fn_name, fn_args, result)
                            if action:
                                collected_actions.append(action)

                    return ToolLoopResult(
                        text=cleaned_text,
                        actions=collected_actions,
                        input_tokens=total_input,
                        output_tokens=total_output,
                    )

                return ToolLoopResult(
                    text=text,
                    actions=collected_actions,
                    input_tokens=total_input,
                    output_tokens=total_output,
                )

            if choice.finish_reason == "tool_calls":
                messages.append(choice.message)

                for tool_call in choice.message.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        try:
                            fn_args, _ = json.JSONDecoder().raw_decode(
                                tool_call.function.arguments
                            )
                        except (json.JSONDecodeError, ValueError):
                            log.warning(
                                "Unparseable tool arguments",
                                tool=fn_name,
                                args=tool_call.function.arguments,
                            )
                            continue
                    log.info("Tool call", tool=fn_name, input=fn_args)

                    result = await tool_executor(fn_name, fn_args)

                    if action_collector:
                        action = action_collector(fn_name, fn_args, result)
                        if action:
                            collected_actions.append(action)

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result),
                        }
                    )
                continue

            # Unexpected finish reason
            return ToolLoopResult(
                text=choice.message.content or "",
                actions=collected_actions,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        raise ToolLoopExhaustedError("Max tool rounds exceeded without final response")

    async def stream(self, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError(
            "DefaultOpenAICompatibleProvider.stream() not implemented in "
            "community edition; use complete() (Phase 226 D-03)."
        )

    async def resolve_runtime_config(self, db) -> dict[str, object]:  # type: ignore[no-untyped-def]
        from app.core.persistent_config import LLM_MODEL, OPENAI_BASE_URL

        model = await LLM_MODEL.get(db)
        base_url = await OPENAI_BASE_URL.get(db) or "https://api.openai.com/v1"
        return {"base_url": base_url, "default_model": model}
