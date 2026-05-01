"""Dataset service layer.

Handles CRUD operations for dataset records in the catalog.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Re-exports from sibling sub-modules (Phase 224 extraction — DECOUPLE-01
# preservation). Consumers continue to import these names from
# `app.modules.catalog.datasets.domain.service` unchanged. The bodies live in
# sibling modules.
# ---------------------------------------------------------------------------
from app.modules.catalog.datasets.domain.service_create import (  # noqa: E402,F401
    create_dataset,
    create_empty_dataset,
)
from app.modules.catalog.datasets.domain.service_lifecycle import (  # noqa: E402,F401
    DependentVrtError,
    _safe_table_ref,
    delete_dataset,
    get_dataset_versions,
)
from app.modules.catalog.datasets.domain.service_metadata import (  # noqa: E402,F401
    compute_schema_diff,
    get_attribute,
    list_attributes,
    reset_attribute,
    update_attribute,
    update_auto_metadata,
    update_user_metadata,
)
from app.modules.catalog.datasets.domain.service_query import (  # noqa: E402,F401
    get_dataset,
    get_dataset_detail,
    get_dataset_rows,
    get_datasets_list,
    list_datasets,
)
from app.modules.catalog.datasets.domain.service_relationships import (  # noqa: E402,F401
    auto_detect_relationships,
    create_relationship,
    delete_relationship,
    get_related_datasets,
    get_related_records,
    list_relationships,
)
