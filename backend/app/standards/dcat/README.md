# W3C DCAT 3 Profile

GeoLens exposes a **W3C DCAT 3** JSON-LD serialization alongside the DCAT-US 3.0
(`app.standards.dcat_us`) and GeoDCAT-AP 2.0.0 (`app.standards.geodcat_ap`)
profiles. This is the baseline, vendor-neutral catalog serialization.

## Version source

- Recommendation: <https://www.w3.org/TR/vocab-dcat-3/>
- Pinned version: `3.0` (W3C Recommendation, 2024-08-22). See
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

## Validation behavior

Validation is a metadata-quality signal, not an authorization bypass. Catalog
validation sees only datasets visible to the caller; per-dataset validation runs
the same access checks as per-dataset export. Reports include `valid`,
`error_count`, and `errors[]` with `path`, `schema_path`, `validator`, and
`message`, identical in shape to the DCAT-US and GeoDCAT-AP validators.

## Conformance and feed completeness

The DCAT 3 catalog and per-dataset serializers use the dataset title when the
optional source description is absent. Every visible input record remains in
the feed; validation no longer filters records before reporting success.
Catalog responses expose source, serialized, excluded, and fallback dataset
counts in `X-GeoLens-*` headers, and validation reports include the same counts.
