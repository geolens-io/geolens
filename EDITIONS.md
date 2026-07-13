# GeoLens open source

GeoLens is Apache-2.0 open-source software for self-hosting a spatial data catalog and map builder on infrastructure you control.

This repository is the self-hosted GeoLens application for one organization's spatial data catalog and map builder. It includes the backend, frontend, CLI, generated SDKs, Docker Compose setup, examples, and release workflows needed to run GeoLens yourself — everything here is Apache-2.0.

## What's here, and what stays free

Everything in this repository is Apache-2.0: catalog, semantic and full-text search, the map builder, editing, the open standards it implements (OGC API Features/Records, STAC, DCAT), single-organization multi-user collaboration, and the CLI/SDKs. You can run it, modify it, and self-host it indefinitely with no license fee.

To give the teams who self-host GeoLens confidence to build on it, we commit that:

- **The open standards stay free, always.** OGC API Features/Records, STAC, and DCAT — and the ability to get your data out — will always be in the Apache-2.0 software. We will not paywall interoperability.
- **What is free today stays free.** Capabilities that ship free in this repository stay free; new paid value is added alongside the software, never by taking free features away.
- **No lock-in.** GeoLens is standards-native by design, so your data and catalog remain exportable and portable.

Optional paid support and add-ons for organizations that want them are available separately from Carto Concepts, LLC. The paid surface currently includes support with an SLA, SAML identity, audit-log export, branding controls, custom share-link expiration, and origin-restricted embeds. Community retains basic OIDC/OAuth, share creation and revocation, non-expiring links, and default-lifetime embeds. Paid modules are distributed in a separately licensed, immutable Enterprise image; they are not required to build or run this repository.

GeoLens core also contains dormant, generic multi-tenant substrate—nullable tenant columns, mode-gated RLS and tenant schemas, request/worker context, and typed processing/catalog/serving/entitlement extension ports. It is Apache-2.0 and remains inert in the default single-tenant mode. The vendor-hosted Cloud product, tenant provisioning, billing, and private provider implementations are separate commercial work; setting multi-tenant mode without an isolation overlay fails at startup.

The architectural boundary is enforced in CI: public application code cannot import private Enterprise or Cloud packages. Optional behavior enters through typed extension protocols whose Community defaults preserve the free product.

The GeoLens name, logo, and brand assets are not covered by the software license. See [TRADEMARKS.md](TRADEMARKS.md). Third-party sample-data attribution is in [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md).
