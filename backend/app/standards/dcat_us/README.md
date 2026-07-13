# DCAT-US 3.0 Profile

GeoLens keeps DCAT-US Schema v3.0 support separate from the existing W3C DCAT 3 serializer.

## Schema source

- Repository: <https://github.com/GSA/dcat-us>
- Vendored commit: `98408dc000f0b71131a03920e2dec6247a84abff`
- Root catalog schema: `jsonschema/definitions/Catalog.json`
- JSON Schema draft: 2020-12

The schema definitions are vendored so validation is deterministic and does not depend on network access at runtime.

## Mapping contract

| DCAT-US class | GeoLens source |
|---------------|----------------|
| Catalog | Visible `Dataset` rows selected through the existing catalog visibility filter |
| Dataset | `Dataset` plus joined `Record` metadata |
| Distribution | `RecordDistribution` rows |
| DataService | Service-like `RecordDistribution` rows when the current metadata has an API/service URL |
| Organization | `Record.source_organization`, `Record.owner_org`, or GeoLens fallback publisher |
| Kind | `RecordContact` rows with `name`/`organization` and `email`, or the configured catalog organization role mailbox |
| PeriodOfTime | `Record.temporal_start` and `Record.temporal_end` |
| Location | `Record.spatial_extent` serialized as WKT bounding polygon |
| Concept | `Record.theme_category` and keyword values where appropriate |

## Known gaps

- DatasetSeries is not first-class in the current catalog model. Use future requirement `DCAT-FU-01` before adding authoring or persistence.
- Structured `AccessRestriction`, `UseRestriction`, and `CUIRestriction` are not first-class in the current metadata model. Current free-text access/use constraints can be surfaced, but structured authoring is future requirement `DCAT-FU-02`.
- Dataset `contactPoint` is mandatory in DCAT-US 3.0. GeoLens never invents an address: operators may configure a monitored organization role mailbox with `DCAT_CONTACT_EMAIL`. Without a record contact or this setting, validation reports the gap and export returns an RFC 7807 `503` instead of publishing a deceptive feed.

## Routes

| Route | Purpose |
|-------|---------|
| `GET /datasets/dcat-us/3.0/` | DCAT-US 3.0 Catalog feed for datasets visible to the caller |
| `GET /datasets/{dataset_id}/dcat-us/3.0/` | DCAT-US 3.0 Dataset document for one accessible dataset |
| `GET /datasets/dcat-us/3.0/validation/` | JSON Schema validation report for the visible catalog feed |
| `GET /datasets/{dataset_id}/dcat-us/3.0/validation/` | JSON Schema validation report for one accessible dataset |

The existing W3C DCAT 3 routes remain unchanged:

- `GET /datasets/dcat/`
- `GET /datasets/{dataset_id}/dcat/`

## Validation behavior

Validation uses the vendored JSON Schema 2020-12 definitions with local `$ref` resolution. Reports include:

- `valid`
- `error_count`
- `errors[].path`
- `errors[].schema_path`
- `errors[].validator`
- `errors[].message`
- catalog source/serialized/excluded/fallback counts
- per-dataset `uses_metadata_fallback` and `metadata_fallback_fields`

Validation is a metadata-quality signal, not an authorization bypass. Catalog validation sees only datasets visible to the caller, and per-dataset validation runs the same access checks as per-dataset export.

## Conformance and feed completeness

Every visible input dataset is serialized; validators no longer act as a hidden
feed filter. A missing description uses the dataset title. A missing usable
record contact uses `DCAT_CONTACT_EMAIL` as an organization-level role contact.
The fallback is explicit in response headers and validation reports.

If neither contact source exists, the validation endpoint reports the required
`contactPoint` error and the catalog/per-dataset export returns RFC 7807 `503`.
This preserves protocol truthfulness and makes remediation discoverable without
misrepresenting a populated catalog as empty.

### Optional stricter lever: `REQUIRE_METADATA_FOR_PUBLISH`

Operators who want to **block publish** of incomplete records can additionally
enable the optional `REQUIRE_METADATA_FOR_PUBLISH` persistent-config lever
(default **False**). Export-time fallbacks and explicit failures remain the
machine-client safety net for existing published records.

## Migration notes

DCAT-US v3.0 differs from DCAT-US v1.1 in areas that matter for GeoLens operators:

- `temporal` is structured as `PeriodOfTime`, not a single interval string.
- `spatial` can carry structured `Location` data such as WKT or GeoJSON bounding boxes.
- `language` is an ISO 639-1 code or list of codes.
- `modified` should describe actual data changes, not only metadata edits.
- `license` is more naturally represented on Distributions.
- Access/use/CUI restrictions are structured supporting classes in v3.0; current GeoLens free-text constraints are not a full substitute.
- `DataService` and `DatasetSeries` are first-class classes. GeoLens can derive simple DataService metadata from service-like distributions, while first-class DatasetSeries authoring is deferred.
