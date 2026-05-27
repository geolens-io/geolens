# DCAT-US 3.0 Stack Research

**Milestone:** v1029 DCAT 3.0
**Sources checked:** resources.data.gov DCAT-US 3.0 reference; GSA/dcat-us JSON Schema repository at HEAD `98408dc000f0b71131a03920e2dec6247a84abff`.

## Current GeoLens Stack

- Backend already serializes W3C DCAT 3 JSON-LD in `backend/app/standards/dcat/service.py`.
- Existing export routes live in `backend/app/modules/catalog/datasets/api/router_export.py`.
- Backend dev dependencies already include `jsonschema>=4.19`, which supports JSON Schema 2020-12; runtime validation endpoints need this dependency in production dependencies as well.
- Existing catalog fields cover many DCAT-US mandatory and recommended fields: title, summary/description, identifier, publisher/source organization, language, temporal extent, spatial extent, keywords/themes, contacts, distributions, license, access constraints, and update frequency.

## Additions Needed

- A separate `app.standards.dcat_us` package so DCAT-US profile behavior does not break existing W3C DCAT 3 output.
- Vendored official DCAT-US 3.0 JSON Schema definition files for deterministic offline validation.
- A validator wrapper around `jsonschema.Draft202012Validator` with a registry that resolves the official `/dcat-us/3.0.0/definitions/*` references.
- Explicit DCAT-US 3.0 routes/aliases while preserving current `/datasets/dcat/` compatibility routes.
- Focused backend tests for serialization, visibility filtering, validation success/failure, and route ordering.

## What Not To Add

- No RDF graph engine is needed; the existing project decision is plain dict JSON-LD.
- No schema fetch at runtime; validation must work without network access.
- No broad catalog schema migration in the first pass unless a required field has no credible mapping or configurable fallback.
