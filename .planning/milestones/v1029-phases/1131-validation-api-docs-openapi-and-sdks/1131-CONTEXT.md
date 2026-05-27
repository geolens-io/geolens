---
status: complete
phase: 1131
requirements:
  - VAL-02
  - VAL-03
  - VAL-04
  - API-05
  - DOC-01
  - DOC-02
  - DOC-03
---

# Phase 1131 Context

Phase 1131 makes the Phase 1130 DCAT-US serializer operational for API consumers and operators.

## Inputs

- Official DCAT-US 3.0 schema definitions vendored from GSA/dcat-us commit `98408dc000f0b71131a03920e2dec6247a84abff`.
- Compatibility route decision: existing `/datasets/dcat/` routes remain W3C DCAT 3, while DCAT-US v3.0 uses explicit `/datasets/dcat-us/3.0/` profile routes.
- Existing catalog visibility and per-dataset access helpers remain the authorization boundary for exports and validation.

## Constraints

- Validation must resolve the local JSON Schema `$ref` graph without network access.
- Validation reports must expose useful schema error paths without inventing required federal metadata.
- Public generated artifacts must reflect the DCAT-US routes, but unrelated dirty source-tree changes must not be mixed into the DCAT-US milestone commits.
