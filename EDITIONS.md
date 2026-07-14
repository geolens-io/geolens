# GeoLens open source

GeoLens is Apache-2.0 open-source software for self-hosting a spatial data catalog and map builder on infrastructure you control.

This repository is the self-hosted GeoLens application for one organization's spatial data catalog and map builder. It includes the backend, frontend, CLI, generated SDKs, Docker Compose setup, examples, and release workflows needed to run GeoLens yourself — everything here is Apache-2.0.

## What's here, and what stays free

Everything in this repository is Apache-2.0: catalog, semantic and full-text search, the map builder, editing, the open standards it implements (OGC API Features/Records, STAC, DCAT), single-organization multi-user collaboration, and the CLI/SDKs. You can run it, modify it, and self-host it indefinitely with no license fee.

To give the teams who self-host GeoLens confidence to build on it, we commit that:

- **The open standards stay free, always.** OGC API Features/Records, STAC, and DCAT — and the ability to get your data out — will always be in the Apache-2.0 software. We will not paywall interoperability.
- **What is free today stays free.** Capabilities that ship free in this repository stay free; new paid value is added alongside the software, never by taking free features away.
- **No lock-in.** GeoLens is standards-native by design, so your data and catalog remain exportable and portable.

Carto Concepts, LLC offers optional paid support and add-ons. Enterprise includes SAML identity, SIEM streaming, compliance automation, branding controls, arbitrary share-link expiration, origin-restricted embeds, and support with an SLA. Community includes OIDC and OAuth, bounded CSV and JSON audit export, share creation and revocation, fixed expiration presets, non-expiring links, and default-lifetime embeds. The paid modules ship in a separately licensed, immutable Enterprise image. You do not need them to build or run this repository.

A valid commercial license grants perpetual use of the installed version. The maintenance term controls access to updates and support. When maintenance ends, the installed version keeps working, data and backups remain accessible, and local administrators keep their login path.

GeoLens core also contains dormant, generic multi-tenant substrate—nullable tenant columns, mode-gated RLS and tenant schemas, request/worker context, and typed processing/catalog/serving/entitlement extension ports. It is Apache-2.0 and remains inert in the default single-tenant mode. The vendor-hosted Cloud product, tenant provisioning, billing, and private provider implementations are separate commercial work; setting multi-tenant mode without an isolation overlay fails at startup.

The architectural boundary is enforced in CI: public application code cannot import private paid or Cloud packages. Optional behavior enters through typed extension protocols whose Community defaults preserve the free product.

The GeoLens name, logo, and brand assets are not covered by the software license. See [TRADEMARKS.md](TRADEMARKS.md). Third-party sample-data attribution is in [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md).
