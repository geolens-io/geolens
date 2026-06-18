# W3C DCAT 3 Profile

GeoLens exposes a **W3C DCAT 3** JSON-LD serialization alongside the DCAT-US 3.0
(`app.standards.dcat_us`) and GeoDCAT-AP 2.0.0 (`app.standards.geodcat_ap`)
profiles. This is the baseline, vendor-neutral catalog serialization.

## Version Source

- Recommendation: <https://www.w3.org/TR/vocab-dcat-3/>
- Pinned version: `3.0` (W3C Recommendation, 2024-08-22) — see
  `schemas.py` (`DCAT3_SCHEMA_VERSION`, `DCAT3_SCHEMA_COMMIT`), pinned the way
  DCAT-US pins `DCAT_US_SCHEMA_VERSION` and GeoDCAT-AP pins
  `GEODCAT_AP_SCHEMA_VERSION`.
- JSON-LD context: `dcat`, `dcterms`, `dqv`, `foaf`, `oa`, `skos`, `vcard`,
  `xsd`.

The W3C DCAT 3 Recommendation does **not** publish an official,
machine-consumable JSON Schema for a JSON-LD serialization (its normative
artifacts are the RDF vocabulary plus SHACL-style constraints in the spec
text). Validation therefore applies structural / required-field checks
(`validation.py`, `validate_dcat3`) in the same spirit and report shape as the
DCAT-US JSON Schema validator and the GeoDCAT-AP structural validator.

## Routes

| Route | Purpose |
|-------|---------|
| `GET /datasets/dcat/` | DCAT 3 catalog feed for datasets visible to the caller |
| `GET /datasets/{dataset_id}/dcat/` | DCAT 3 document for one accessible dataset |
| `GET /datasets/dcat/validation/` | Structural validation report for the visible catalog feed |
| `GET /datasets/{dataset_id}/dcat/validation/` | Structural validation report for one accessible dataset |

## Validation Behavior

Validation is a metadata-quality signal, not an authorization bypass. Catalog
validation sees only datasets visible to the caller; per-dataset validation runs
the same access checks as per-dataset export. Reports include `valid`,
`error_count`, and `errors[]` with `path`, `schema_path`, `validator`, and
`message` — identical in shape to the DCAT-US and GeoDCAT-AP validators.

## Conformance Posture: Filter the Feed

The DCAT 3 **catalog feed** (`GET /datasets/dcat/`) emits **only** records that
pass DCAT 3 structural validation — records missing a mandatory property (title
or description) are silently skipped so the feed stays conformant with zero
onboarding friction. The **per-dataset** endpoint
(`GET /datasets/{id}/dcat/`) is **not** filtered and always serializes the
requested record as-is. See
[`app/standards/dcat_us/README.md`](../dcat_us/README.md#conformance-posture-filter-the-feed)
for the full posture, including the optional stricter
`REQUIRE_METADATA_FOR_PUBLISH` publish-time lever.
