# DCAT-US 3.0 Profile

GeoLens keeps DCAT-US Schema v3.0 support separate from the existing W3C DCAT 3 serializer.

## Schema Source

- Repository: <https://github.com/GSA/dcat-us>
- Vendored commit: `98408dc000f0b71131a03920e2dec6247a84abff`
- Root catalog schema: `jsonschema/definitions/Catalog.json`
- JSON Schema draft: 2020-12

The schema definitions are vendored so validation is deterministic and does not depend on network access at runtime.

## Mapping Contract

| DCAT-US class | GeoLens source |
|---------------|----------------|
| Catalog | Visible `Dataset` rows selected through the existing catalog visibility filter |
| Dataset | `Dataset` plus joined `Record` metadata |
| Distribution | `RecordDistribution` rows |
| DataService | Service-like `RecordDistribution` rows when the current metadata has an API/service URL |
| Organization | `Record.source_organization`, `Record.owner_org`, or GeoLens fallback publisher |
| Kind | `RecordContact` rows with `name`/`organization` and `email` |
| PeriodOfTime | `Record.temporal_start` and `Record.temporal_end` |
| Location | `Record.spatial_extent` serialized as WKT bounding polygon |
| Concept | `Record.theme_category` and keyword values where appropriate |

## Known Gaps

- DatasetSeries is not first-class in the current catalog model. Use future requirement `DCAT-FU-01` before adding authoring or persistence.
- Structured `AccessRestriction`, `UseRestriction`, and `CUIRestriction` are not first-class in the current metadata model. Current free-text access/use constraints can be surfaced, but structured authoring is future requirement `DCAT-FU-02`.
- Dataset `contactPoint` is mandatory in DCAT-US 3.0. GeoLens should not invent federal contact emails. Validation reports must identify datasets missing usable contact metadata.
