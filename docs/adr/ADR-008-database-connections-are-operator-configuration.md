# ADR-008: Database connections are operator configuration

**Status:** accepted. **Scope:** how GeoLens reads databases outside itself,
and which edition that belongs to.

## Context

Many organizations keep their spatial data in SQL Server, often behind ArcGIS,
and want it in the catalog. Running GeoLens itself on SQL Server isn't
practical. The backend makes hundreds of PostGIS calls, reprojection and
vector tile encoding have no SQL Server equivalent, and the job queue runs
only on PostgreSQL. So the data comes in as a database import: a managed copy
of one table or view, refreshed from its source.

Two existing rules shape how GeoLens reaches that database. The SSRF guard
refuses private addresses, and an organization's database is almost always on
its internal network. The open build never stores a source credential, and
`EDITIONS.md` lists stored source credentials, persistent connector
configurations and scheduled refresh as paid.

## Decision

A database connection is part of the deployment's configuration. The operator
lists connections in `DATABASE_SOURCES`, next to the deployment's other
secrets, and each one names an engine (only `sqlserver` for now), a server, a
database and a login. Users pick a connection by name and a spatial table or
view from its listing. They never type a server, a login or SQL.

- Database import and manual refresh are Community features. GeoLens reads a
  connection from its configuration the way it reads the SMTP password, and
  never writes it to its own database. Connectors stored in the app, stored
  source credentials and scheduled refresh stay paid, and a scheduled refresh
  of a database import goes through the paid scheduler like any other.
- Only servers the operator names are reachable. The SSRF guard still refuses
  private addresses in everything a user types.
- The source binding records the connection's name, the schema and the table,
  never the server or the login. The name is the identity, so pointing a name
  at another server moves every dataset imported through it.
- Every user who can create datasets can import from every connection. The
  login's grants decide which tables they see.
- The configuration is global to the deployment, so `multi_tenant` mode
  refuses to start with a connection configured. Tenant-scoped connections
  would need a tenant-scoped store, which is the paid connector capability.

We rejected running GeoLens on SQL Server, for the reasons above, and letting
users enter their own server and login. That would need a private-address
exception to the SSRF guard and a stored credential for every refresh. We
also considered making the whole feature paid. A connection kept in the
deployment's configuration needs neither the in-app connector store nor
credential storage, so the paid capabilities stay where they are.

## Consequences

Adding a connection or changing its login means editing the deployment's
configuration and restarting, so only someone who runs the deployment can do
it. `EDITIONS.md` states that connections in deployment configuration are
Community.

An open feature can't later move behind an edition, so database import stays
open for good.

The origin kind is `database`, and the engine is part of the connection. A
second engine adds a configuration value, not a new origin kind in the API.

The implementation plan is in #3714.
