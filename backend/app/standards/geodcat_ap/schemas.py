"""GeoDCAT-AP profile version pinning and structural schema constants.

Unlike DCAT-US 3.0, the GeoDCAT-AP specification does not publish an official,
machine-consumable JSON Schema for the JSON-LD serialization. The normative
artifacts are the SHACL shapes (RDF) plus the human-readable specification.
GeoLens therefore pins the targeted GeoDCAT-AP version here and applies
structural/required-field validation (see :mod:`validation`) that mirrors the
mandatory-class expectations of the specification, in the same spirit as the
DCAT-US JSON Schema validator.
"""

from __future__ import annotations

# GeoDCAT-AP 2.0.0 is the published SEMIC recommendation aligned to DCAT-AP 2.
# (The 3.0.0 line is still a working draft at time of writing.) We pin 2.0.0
# the way DCAT-US pins DCAT_US_SCHEMA_VERSION / DCAT_US_SCHEMA_COMMIT.
GEODCAT_AP_SCHEMA_VERSION = "2.0.0"
GEODCAT_AP_SCHEMA_REPOSITORY = "https://github.com/SEMICeu/GeoDCAT-AP"
# Pinned to the 2.0.0 release tag of the SEMIC GeoDCAT-AP specification.
GEODCAT_AP_SCHEMA_COMMIT = "2.0.0"
GEODCAT_AP_SPEC_URI = "https://semiceu.github.io/GeoDCAT-AP/releases/2.0.0/"

# Mandatory properties per the GeoDCAT-AP / DCAT-AP cardinality tables.
# Used by the structural validator. Property names match the serialized
# JSON-LD keys (compact IRIs) produced by service.py.
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

# Mandatory dataset @type for the profile.
DATASET_TYPE = "dcat:Dataset"
CATALOG_TYPE = "dcat:Catalog"
