"""W3C DCAT 3 profile version pinning and structural schema constants.

The W3C DCAT 3 Recommendation does not publish an official, machine-consumable
JSON Schema for a JSON-LD serialization (its normative artifacts are the RDF
vocabulary plus SHACL-style constraints in the spec text). GeoLens therefore
pins the targeted DCAT version here and applies structural / required-field
validation (see :mod:`validation`) that mirrors the mandatory-property
expectations of the Recommendation, in the same spirit as the DCAT-US JSON
Schema validator and the GeoDCAT-AP structural validator.
"""

from __future__ import annotations

# W3C DCAT version 3 (the "DCAT 3" Recommendation). Pinned the way DCAT-US
# pins DCAT_US_SCHEMA_VERSION and GeoDCAT-AP pins GEODCAT_AP_SCHEMA_VERSION.
DCAT3_SCHEMA_VERSION = "3.0"
DCAT3_SCHEMA_REPOSITORY = "https://www.w3.org/TR/vocab-dcat-3/"
# DCAT 3 reached W3C Recommendation status on 2024-08-22.
DCAT3_SCHEMA_COMMIT = "REC-vocab-dcat-3-20240822"
DCAT3_SPEC_URI = "https://www.w3.org/TR/vocab-dcat-3/"

# Mandatory properties per the DCAT 3 Recommendation cardinality expectations.
# Property names match the serialized JSON-LD keys (compact IRIs) produced by
# ``service.py``. DCAT 3 itself marks very few properties as mandatory; GeoLens
# treats title + description as the minimum a feed entry must carry to be a
# useful, discoverable catalog record (the same minimum the GeoDCAT-AP
# structural validator enforces).
DATASET_REQUIRED_PROPERTIES: tuple[str, ...] = (
    "dcterms:title",
    "dcterms:description",
)

CATALOG_REQUIRED_PROPERTIES: tuple[str, ...] = (
    "dcterms:title",
    "dcterms:description",
    "dcterms:publisher",
    "dcat:dataset",
)

# Mandatory @type values for the profile.
DATASET_TYPE = "dcat:Dataset"
CATALOG_TYPE = "dcat:Catalog"
