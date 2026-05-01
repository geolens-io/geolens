"""Dataset domain service — thin re-export façade (Phase 224).

The 1407-LOC orchestration god-module that previously lived here was split
into 5 cohesive sub-modules along responsibility lines:

- service_create.py        -- dataset creation paths (empty, materialized)
- service_query.py         -- read-side queries (lookup, list, detail, rows)
- service_lifecycle.py     -- delete, version history, DependentVrtError,
                              _safe_table_ref helper
- service_metadata.py      -- user metadata, auto metadata, attribute CRUD,
                              schema diffing, _normalize_col_type helper
- service_relationships.py -- dataset relationships + related records

External callers MUST import from this façade
(`app.modules.catalog.datasets.domain.service`), NOT from the sub-modules
directly. The architecture-guard test
`test_no_external_imports_of_dataset_domain_submodules` in
`backend/tests/test_layering.py` enforces this in CI (DECOUPLE-04).
Cross-imports BETWEEN the 5 sub-modules are permitted.

Source: docs-internal/audits/oc-separation-audit-20260430-b.md §5 + §7 P0 #1.
"""

from app.modules.catalog.datasets.domain.service_create import (
    create_dataset,
    create_empty_dataset,
)
from app.modules.catalog.datasets.domain.service_lifecycle import (
    DependentVrtError,
    _safe_table_ref,  # noqa: F401 -- re-exported for tests/test_sql_safety.py
    delete_dataset,
    get_dataset_versions,
)
from app.modules.catalog.datasets.domain.service_metadata import (
    compute_schema_diff,
    get_attribute,
    list_attributes,
    reset_attribute,
    update_attribute,
    update_auto_metadata,
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
    list_relationships,
)

__all__ = [
    "DependentVrtError",
    "auto_detect_relationships",
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
    "list_attributes",
    "list_datasets",
    "list_relationships",
    "reset_attribute",
    "update_attribute",
    "update_auto_metadata",
    "update_user_metadata",
]
