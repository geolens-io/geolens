"""Dataset domain service — thin re-export façade.

Logic lives in the service_* sub-modules plus _sql_safety; cross-imports
between them are fine. External callers MUST import from this façade, never
a sub-module directly — enforced by
`test_no_external_imports_of_dataset_domain_submodules` in
`backend/tests/test_layering.py` (DECOUPLE-04).
"""

from app.modules.catalog.datasets.domain._sql_safety import (
    _safe_table_ref,  # noqa: F401 -- re-exported for tests/test_sql_safety.py
)
from app.modules.catalog.datasets.domain.service_analysis import (
    PREVIEW_FEATURE_CAP,
    build_preview_sql,
    resolve_source_feature_count,
    run_analysis_preview,
)
from app.modules.catalog.datasets.domain.service_create import (
    create_dataset,
    create_empty_dataset,
)
from app.modules.catalog.datasets.domain.service_lifecycle import (
    DatasetDeletion,
    DatasetTitleMismatchError,
    DependentVrtError,
    delete_dataset,
    get_dataset_versions,
    reap_managed_storage,
)
from app.modules.catalog.datasets.domain.service_metadata import (
    compute_schema_diff,
    get_attribute,
    list_attributes,
    reset_attribute,
    sample_example_values,
    update_attribute,
    update_user_metadata,
)
from app.modules.catalog.datasets.domain.service_query import (
    get_dataset,
    get_dataset_detail,
    get_dataset_rows,
    get_datasets_list,
    list_datasets,
)
from app.modules.catalog.datasets.domain.service_relationships import (
    auto_detect_relationships,
    create_relationship,
    delete_relationship,
    get_related_datasets,
    get_related_records,
    get_relationship_datasets,
    list_relationships,
    list_relationships_with_total,
)

__all__ = [
    "DatasetDeletion",
    "reap_managed_storage",
    "DatasetTitleMismatchError",
    "DependentVrtError",
    "PREVIEW_FEATURE_CAP",
    "auto_detect_relationships",
    "build_preview_sql",
    "compute_schema_diff",
    "create_dataset",
    "create_empty_dataset",
    "create_relationship",
    "delete_dataset",
    "delete_relationship",
    "get_attribute",
    "get_dataset",
    "get_dataset_detail",
    "get_dataset_rows",
    "get_dataset_versions",
    "get_datasets_list",
    "get_related_datasets",
    "get_related_records",
    "get_relationship_datasets",
    "list_attributes",
    "list_datasets",
    "list_relationships",
    "list_relationships_with_total",
    "reset_attribute",
    "sample_example_values",
    "resolve_source_feature_count",
    "run_analysis_preview",
    "update_attribute",
    "update_user_metadata",
]
