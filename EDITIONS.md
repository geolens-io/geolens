# GeoLens open source

GeoLens is Apache-2.0 open-source software for self-hosting a spatial data catalog and map builder on infrastructure you control.

This repository is the self-hosted GeoLens application for one organization's spatial data catalog and map builder. It includes the backend, frontend, CLI, generated SDKs, Docker Compose setup, examples, and release workflows needed to run GeoLens yourself — everything here is Apache-2.0.

## What's here, and what stays free

Everything in this repository is Apache-2.0: catalog, semantic and full-text search, the map builder, editing, the open standards it implements (OGC API Features/Records, STAC, DCAT), single-organization multi-user collaboration, and the CLI/SDKs. You can run it, modify it, and self-host it indefinitely with no license fee.

To give the teams who self-host GeoLens confidence to build on it, we commit that:

- **The open standards stay free, always.** OGC API Features/Records, STAC, and DCAT — and the ability to get your data out — will always be in the Apache-2.0 software. We will not paywall interoperability.
- **What is free today stays free.** Capabilities that ship free in this repository stay free; new paid value is added alongside the software, never by taking free features away.
- **No lock-in.** GeoLens is standards-native by design, so your data and catalog remain exportable and portable.

Optional paid support and add-ons for organizations that want them (support with an SLA, advanced identity, audit-log export, and single-tenant deployment hardening) are available separately from Carto Concepts, LLC. They are entirely optional — nothing in this repository is disabled without them. We note it here so the free/paid boundary is never a surprise.

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
