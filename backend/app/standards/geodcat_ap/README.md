# GeoDCAT-AP 2.0.0 Profile

GeoLens exposes a **GeoDCAT-AP** serialization alongside the W3C DCAT 3
(`app.standards.dcat`) and DCAT-US 3.0 (`app.standards.dcat_us`) profiles.

GeoDCAT-AP is the geospatial profile of DCAT-AP — the European Union /
INSPIRE Application Profile of DCAT. It extends DCAT with the geospatial and
ISO 19115 / 19139 metadata that GeoLens already stores (lineage, constraints,
responsible-party roles, maintenance frequency, reference system, spatial
resolution, and spatial/temporal extents).

## Version Source

- Specification: <https://semiceu.github.io/GeoDCAT-AP/releases/2.0.0/>
- Repository: <https://github.com/SEMICeu/GeoDCAT-AP>
- Pinned version / tag: `2.0.0`
- JSON-LD context: DCAT 3 namespaces plus `adms`, `gsp` (GeoSPARQL),
  `locn`, `prov`, `rdfs`, and `geodcat` (`http://data.europa.eu/930/`).

GeoDCAT-AP's normative artifacts are SHACL shapes plus the human-readable
specification; unlike DCAT-US 3.0 there is **no official machine-consumable
JSON Schema** to vendor. Validation therefore applies structural /
required-field checks consistent with the mandatory-class cardinalities of the
specification (see `validation.py`), in the same spirit and report shape as the
DCAT-US validator.

## Mapping Contract (ISO 19115 → GeoDCAT-AP)

| GeoLens / ISO source | GeoDCAT-AP term |
|----------------------|-----------------|
| `Record.title` | `dcterms:title` |
| `Record.summary` | `dcterms:description` |
| `Record.language` | `dcterms:language` (EU Authority Table URI) |
| `Record.created_at` / `updated_at` | `dcterms:issued` / `dcterms:modified` |
| `Record.keywords` | `dcat:keyword` |
| `Record.theme_category` (ISO topic categories) | `dcat:theme` `skos:Concept` |
| `Record.source_organization` / `owner_org` | `dcterms:publisher` `foaf:Agent` |
| `Record.license` | `dcterms:license` (dataset + distribution) |
| `Record.lineage_summary` (LI_Lineage) | `dcterms:provenance` `dcterms:ProvenanceStatement` |
| `Record.update_frequency` (MD_MaintenanceFrequencyCode) | `dcterms:accrualPeriodicity` |
| `Record.access_constraints` | `dcterms:accessRights` `dcterms:RightsStatement` |
| `Record.usage_constraints` | `dcterms:rights` `dcterms:RightsStatement` |
| `Dataset.srid` / `original_srid` (MD_ReferenceSystem) | `dcterms:conformsTo` → OGC EPSG CRS URI |
| `Record.temporal_start` / `temporal_end` | `dcterms:temporal` `dcterms:PeriodOfTime` |
| `Record.spatial_extent` | `dcterms:spatial` `dcterms:Location` with GeoSPARQL `gsp:wktLiteral` (CRS84) |
| `RecordContact.role` (CI_RoleCode) | role-mapped DCAT-AP property (see below) |
| `RecordDistribution` | `dcat:Distribution` (+ `dcat:DataService` for service URLs) |

### Responsible-party role mapping (CI_RoleCode)

`RecordContact.role` is mapped to the GeoDCAT-AP-recommended property:

| ISO CI_RoleCode | GeoDCAT-AP property |
|-----------------|---------------------|
| `pointOfContact` | `dcat:contactPoint` (`vcard:Kind`) |
| `publisher` | `dcterms:publisher` |
| `author`, `originator` | `dcterms:creator` |
| `owner`, `custodian` | `geodcat:custodian` |
| `distributor` | `geodcat:distributor` |
| `principalInvestigator` | `geodcat:principalInvestigator` |
| `processor` | `geodcat:processor` |
| `resourceProvider` | `geodcat:resourceProvider` |
| `user` | `geodcat:user` |
| `rightsHolder` | `dcterms:rightsHolder` |
| `contributor` | `dcterms:contributor` |
| (any other role) | `dcat:contactPoint` |

Contacts are **not fabricated**: a contact with neither a name nor an
organization is skipped entirely, matching the DCAT-US behavior.

## Routes

| Route | Purpose |
|-------|---------|
| `GET /datasets/geodcat-ap/` | GeoDCAT-AP catalog feed for datasets visible to the caller |
| `GET /datasets/{dataset_id}/geodcat-ap/` | GeoDCAT-AP document for one accessible dataset |
| `GET /datasets/geodcat-ap/validation/` | Structural validation report for the visible catalog feed |
| `GET /datasets/{dataset_id}/geodcat-ap/validation/` | Structural validation report for one accessible dataset |

The W3C DCAT 3 (`/datasets/dcat/`) and DCAT-US 3.0 (`/datasets/dcat-us/3.0/`)
routes are unchanged.

## Validation Behavior

Validation is a metadata-quality signal, not an authorization bypass. Catalog
validation sees only datasets visible to the caller; per-dataset validation
runs the same access checks as per-dataset export. Reports include `valid`,
`error_count`, and `errors[]` with `path`, `schema_path`, `validator`, and
`message` — identical in shape to the DCAT-US validator.

## Conformance Posture: Filter the Feed

Like the W3C DCAT 3 and DCAT-US 3.0 profiles, the GeoDCAT-AP **catalog feed**
(`GET /datasets/geodcat-ap/`) emits **only** records that pass GeoDCAT-AP
structural validation — records missing a mandatory property (title or
description) are silently skipped so the feed stays conformant with zero
onboarding friction. The **per-dataset** endpoint
(`GET /datasets/{id}/geodcat-ap/`) is **not** filtered and always serializes
the requested record as-is. See
[`app/standards/dcat_us/README.md`](../dcat_us/README.md#conformance-posture-filter-the-feed)
for the full posture, including the optional stricter
`REQUIRE_METADATA_FOR_PUBLISH` publish-time lever.

## Known Gaps

- Structured ISO constraint codes (`MD_RestrictionCode`, INSPIRE limitations)
  are surfaced as free-text `dcterms:RightsStatement` labels rather than
  controlled-vocabulary URIs; the underlying metadata model stores free text.
- Spatial resolution (`dcat:spatialResolutionInMeters`) is not yet a
  first-class field on the metadata model and is therefore not emitted.
- CRS is referenced via an OGC EPSG URI derived from the dataset SRID; a full
  `dcterms:conformsTo` `dcterms:Standard` description is deferred.
