"""Standards DCAT namespace (W3C DCAT 3)."""

from app.standards.dcat.schemas import (
    DCAT3_SCHEMA_COMMIT,
    DCAT3_SCHEMA_VERSION,
)
from app.standards.dcat.service import catalog_to_dcat, record_to_dcat
from app.standards.dcat.validation import validate_dcat3

__all__ = [
    "DCAT3_SCHEMA_COMMIT",
    "DCAT3_SCHEMA_VERSION",
    "catalog_to_dcat",
    "record_to_dcat",
    "validate_dcat3",
]
