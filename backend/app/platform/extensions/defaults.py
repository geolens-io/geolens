"""Community-edition default implementations of extension protocols.

Facade module (#836): split by job into ``defaults_extensions.py``,
``defaults_processing_port.py``, ``defaults_catalog_port.py``, and
``defaults_ai_anthropic.py`` / ``defaults_ai_openai.py``. External code
imports every ``Default*`` name from THIS module; the sub-modules are
private (mirrors the ``datasets/domain/service.py`` facade convention
enforced by ``backend/tests/test_layering.py``).

Every re-exported name MUST be listed in ``__all__`` — ruff treats a facade
import without an ``__all__`` entry as unused and deletes it under ``--fix``.
"""

from __future__ import annotations

# fix(#873): re-export as redundant aliases to keep the pre-split import
# surface intact for out-of-tree callers that relied on it incidentally.
from app.core.db.tenant_session import (
    defer_async_with_tenant as defer_async_with_tenant,
)
from app.platform.ai_tool_payloads import (
    model_safe_tool_result as model_safe_tool_result,
)
from app.platform.extensions.defaults_ai_anthropic import DefaultAnthropicProvider
from app.platform.extensions.defaults_ai_openai import (
    DefaultOpenAICompatibleProvider,
    DefaultOpenAIEmbeddingProvider,
)
from app.platform.extensions.defaults_catalog_port import DefaultCatalogPort
from app.platform.extensions.defaults_extensions import (
    DefaultAuditSink,
    DefaultAuthExtension,
    DefaultBillingExtension,
    DefaultBrandingExtension,
    DefaultConnectorExtension,
    DefaultDataServingExtension,
    DefaultEntitlementPort,
    DefaultIdentityExtension,
    DefaultNotificationSink,
    DefaultPermissionExtension,
    DefaultWorkflowExtension,
)
from app.platform.extensions.defaults_processing_port import DefaultProcessingPort

__all__ = [
    "DefaultAnthropicProvider",
    "DefaultAuditSink",
    "DefaultAuthExtension",
    "DefaultBillingExtension",
    "DefaultBrandingExtension",
    "DefaultCatalogPort",
    "DefaultConnectorExtension",
    "DefaultDataServingExtension",
    "DefaultEntitlementPort",
    "DefaultIdentityExtension",
    "DefaultNotificationSink",
    "DefaultOpenAICompatibleProvider",
    "DefaultOpenAIEmbeddingProvider",
    "DefaultPermissionExtension",
    "DefaultProcessingPort",
    "DefaultWorkflowExtension",
    # fix(#873): keep these two helper bindings wildcard-visible too, not
    # just directly importable.
    "defer_async_with_tenant",
    "model_safe_tool_result",
]
