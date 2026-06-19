"""GeoDCAT-AP profile support.

GeoDCAT-AP is the geospatial profile of DCAT-AP (the European Union /
INSPIRE Application Profile of DCAT). It extends DCAT with the geospatial
metadata expected by INSPIRE / ISO 19115, which GeoLens already stores
(lineage, constraints, contact roles, maintenance frequency, spatial
resolution, reference system, spatial/temporal extents).
"""

from app.standards.geodcat_ap.schemas import (
    GEODCAT_AP_SCHEMA_COMMIT,
    GEODCAT_AP_SCHEMA_VERSION,
)
from app.standards.geodcat_ap.service import (
    catalog_to_geodcat_ap,
    record_to_geodcat_ap,
)
from app.standards.geodcat_ap.validation import validate_geodcat_ap

__all__ = [
    "GEODCAT_AP_SCHEMA_COMMIT",
    "GEODCAT_AP_SCHEMA_VERSION",
    "catalog_to_geodcat_ap",
    "record_to_geodcat_ap",
    "validate_geodcat_ap",
]
