# GeoLens open source

GeoLens is Apache-2.0 open-source software for self-hosting a spatial data catalog and map builder on infrastructure you control.

This repository is the self-hosted GeoLens application for one organization's spatial data catalog and map builder. It includes the backend, frontend, CLI, generated SDKs, Docker Compose setup, examples, and release workflows needed to run GeoLens yourself. Everything here is Apache-2.0.

## What's here, and what stays free

Everything in this repository is Apache-2.0: catalog, semantic and full-text search, the map builder, editing, the open standards it implements (OGC API Features/Records, STAC, DCAT), single-organization multi-user collaboration, and the CLI/SDKs. You can run it, modify it, and self-host it indefinitely with no license fee.

These commitments define the free and paid boundary:

- OGC API Features/Records, STAC, DCAT, and data export will remain in the Apache-2.0 software. We will not charge for interoperability.
- Capabilities released for free in this repository will stay free. Paid modules will add separate capabilities instead of taking existing ones away.
- Your data and catalog remain exportable through open standards.

Carto Concepts, LLC offers optional paid support and add-ons. Enterprise includes SAML identity, SIEM streaming, compliance automation, branding controls, arbitrary share-link expiration, origin-restricted embeds, and support with an SLA. Community includes OIDC and OAuth, bounded CSV and JSON audit export, share creation and revocation, fixed expiration presets, non-expiring links, and default-lifetime embeds. The paid modules ship in a separately licensed, immutable Enterprise image. You do not need them to build or run this repository.

A valid commercial license grants perpetual use of the installed version. The maintenance term controls access to updates and support. When maintenance ends, the installed version keeps working, data and backups remain accessible, and local administrators keep their login path.

GeoLens core also contains dormant, generic multi-tenant infrastructure: nullable tenant columns, mode-gated RLS and tenant schemas, request and worker context, and typed extension ports. This code is Apache-2.0 and remains inactive in the default single-tenant mode. The vendor-hosted Cloud product, tenant provisioning, billing, and private provider implementations are separate commercial work. GeoLens refuses to start in multi-tenant mode without an isolation overlay.

CI prevents public application code from importing private paid or Cloud packages. Optional behavior uses typed extension protocols, and the Community defaults preserve the free product.

The GeoLens name, logo, and brand assets are not covered by the software license. See [TRADEMARKS.md](TRADEMARKS.md). Third-party sample-data attribution is in [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md).

## Optional overlay deployment contract

The base Compose files also provide an explicit, fail-closed handoff for an
optional extension overlay image. This plumbing does not enable or download
paid code; it only ensures a pre-baked overlay receives the same edition,
tenancy, and signed-license inputs in the migration, API, and worker processes.

- `GEOLENS_EDITION=enterprise` requires a loaded extension. The
  application and Alembic refuse to continue when the overlay is absent.
- `GEOLENS_TENANCY_MODE=multi_tenant` requires the overlay's tenant-isolation
  layer. The default is `single_tenant`.
- `GEOLENS_LICENSE_KEY` supplies a signed token inline.
  `GEOLENS_LICENSE_FILE` is the alternative and must name a file mounted
  read-only into migrate, api, and worker by a Compose override.
- `GEOLENS_LICENSE_AUDIENCE` binds an audience-restricted token to a
  deployment. `GEOLENS_LICENSE_ENFORCE=true` keeps the process in community
  mode unless a valid signed license is present.

All six inputs are optional and empty/disabled by default. The canonical
placeholders and constraints live in [`.env.example`](.env.example).
