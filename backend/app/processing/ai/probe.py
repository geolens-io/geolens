"""Live AI provider probe (fix #627).

The admin ai-status endpoint reports whether a provider key is CONFIGURED;
this module answers whether it WORKS. A key rotated or expired upstream
otherwise fails invisibly — on 2026-07-21 the public demo's chat and
embeddings 401'd for a full day while every status surface showed green,
because nothing ever exercised the key.

Opt-in only: each probe issues a real (if minimal) provider API call, so it
must never run implicitly or on a dashboard poll — the router gates it
behind an explicit ``?probe=true``.
"""

import structlog

from app.core.config import settings
from app.processing.ai.schemas import AIProbeCheck, AIProbeReport

logger = structlog.stdlib.get_logger(__name__)

# The cached SDK clients carry long chat timeouts; a probe must never hang
# the admin endpoint that long, so every probe request gets its own cap.
_PROBE_TIMEOUT_SECONDS = 15.0

_STATUS_REASONS = {
    401: "authentication failed",
    403: "authentication failed",
    404: "model or endpoint not found",
    429: "rate limited by provider",
}


def _sanitized_failure(exc: Exception) -> tuple[int | None, str]:
    """Map a provider exception to ``(status_code, short reason)``.

    The response must never carry exception text: provider error bodies can
    include request URLs, deployment names, or key fragments. The full detail
    is logged server-side instead (operators own the logs already).
    """
    cause: BaseException | None = exc
    while cause is not None:
        status = getattr(cause, "status_code", None)
        if isinstance(status, int):
            return status, _STATUS_REASONS.get(
                status, f"provider returned HTTP {status}"
            )
        cause = cause.__cause__
    if isinstance(exc, TimeoutError):
        return None, "timed out"
    return None, f"request failed ({type(exc).__name__})"


async def _probe_chat(db) -> AIProbeCheck:  # type: ignore[no-untyped-def]
    """One-token completion against the SELECTED chat provider.

    Mirrors the real chat path's provider/model/base-URL resolution
    (resolve_provider) and its cached SDK clients, so ``ok`` here means the
    actual chat route would authenticate.
    """
    # Deferred imports — same discipline as llm_loop's own SDK handling.
    from app.processing.ai.llm_loop import (
        get_anthropic_client,
        get_openai_client,
        resolve_provider,
    )

    provider, model, runtime_config = await resolve_provider(db)
    keys = {
        "anthropic": settings.anthropic_api_key,
        "openai_compatible": settings.openai_api_key,
    }
    if not keys.get(provider):
        return AIProbeCheck(configured=False)

    try:
        if provider == "anthropic":
            client = get_anthropic_client()
            await client.messages.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        else:
            client = get_openai_client(runtime_config.get("base_url"))
            await client.chat.completions.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
                timeout=_PROBE_TIMEOUT_SECONDS,
            )
        return AIProbeCheck(configured=True, ok=True)
    except Exception as exc:
        status, reason = _sanitized_failure(exc)
        logger.warning(
            "AI chat probe failed",
            provider=provider,
            model=model,
            status=status,
            error=str(exc),
        )
        return AIProbeCheck(configured=True, ok=False, status=status, error=reason)


async def _probe_embeddings(db) -> AIProbeCheck:  # type: ignore[no-untyped-def]
    """One-input embeddings call via the embedding provider extension.

    Anthropic has no embedding API, so embeddings are configured iff an
    OpenAI-compatible key exists — a chat-only (Anthropic) deployment reports
    ``configured=False`` here rather than an error.
    """
    from app.core.persistent_config import EMBEDDING_MODEL
    from app.platform.extensions import get_embedding_provider

    if not settings.openai_api_key:
        return AIProbeCheck(configured=False)

    provider_ext = get_embedding_provider("openai_compatible")
    runtime_config = await provider_ext.resolve_runtime_config(db)
    model = await EMBEDDING_MODEL.get(db) or runtime_config.get("default_model")

    try:
        await provider_ext.embed(
            texts=["ping"],
            model=model,
            dimensions=None,
            base_url=runtime_config.get("base_url"),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        return AIProbeCheck(configured=True, ok=True)
    except Exception as exc:
        status, reason = _sanitized_failure(exc)
        logger.warning(
            "AI embeddings probe failed",
            model=model,
            status=status,
            error=str(exc),
        )
        return AIProbeCheck(configured=True, ok=False, status=status, error=reason)


async def run_ai_probe(db) -> AIProbeReport:  # type: ignore[no-untyped-def]
    """Run both purpose probes sequentially.

    Sequential on purpose: the two probes share the caller's AsyncSession
    for config resolution, and an AsyncSession must not be used concurrently.
    """
    chat = await _probe_chat(db)
    embeddings = await _probe_embeddings(db)
    return AIProbeReport(chat=chat, embeddings=embeddings)
