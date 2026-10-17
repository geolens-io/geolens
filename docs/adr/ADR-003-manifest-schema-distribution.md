# ADR-003: Manifest schema distribution

**Status:** accepted. **Scope:** where the versioned manifest JSON Schema ships.

## Context

`geolens apply` reads a `geolens.yaml` manifest whose shape is described by a
versioned JSON Schema. Editors and non-Python tooling want that schema for
validation and completion.

## Decision

The schema ships inside the `geolens-cli` package, not as a separate artifact.
Anyone can read the exact installed schema with `geolens schema` or
`geolens schema -o schema.json`. Its stable `$id` identifies manifest v1.

A second package would add a release and version-skew surface without a
demonstrated independent consumer. The CLI is already the canonical tool for
authoring and validating manifests, so schema changes and CLI versions ship
together, and a package-resource test checks that the schema ships inside
`geolens_cli`.

## Revisit when

Several consumers need schema releases on a cadence independent of the CLI.
