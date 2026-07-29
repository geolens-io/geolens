"""Community-edition default implementations of extension protocols.

Facade module (#836): the former 1,815-line single module is split by job into
``defaults_extensions.py`` (extension-seam policy defaults),
``defaults_processing_port.py`` (ProcessingPort), ``defaults_catalog_port.py``
(CatalogPort), and ``defaults_ai_anthropic.py`` / ``defaults_ai_openai.py``
(AI providers). External code — core, overlays, and tests — imports every
``Default*`` name from THIS module; the sub-modules are private to the split
(mirrors the ``datasets/domain/service.py`` facade convention enforced by
``backend/tests/test_layering.py``).

Every re-exported name MUST be listed in ``__all__`` — ruff treats a facade
import without an ``__all__`` entry as unused and deletes it under ``--fix``.
"""

from __future__ import annotations

from app.platform.extensions.defaults_ai_anthropic import DefaultAnthropicProvider
from app.platform.extensions.defaults_ai_openai import (
    DefaultOpenAICompatibleProvider,
    DefaultOpenAIEmbeddingProvider,
)
from app.platform.extensions.defaults_catalog_port import DefaultCatalogPort
from app.platform.extensions.defaults_extensions import (
    DefaultAuditExtension,
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
    # fix(#873 review r1): deprecated import-compatibility alias, removed at
    # the next EXTENSION_API_VERSION bump.
    "DefaultAuditExtension",
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
]
