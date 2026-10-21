# ADR-005: An ArcGIS migration is a one-way exit

**Status:** accepted. **Scope:** what an ArcGIS migration from an ArcGIS Online
organization or ArcGIS Enterprise portal leaves behind in GeoLens, and what
happens to the portal afterwards.

## Context

A migration can take one of two shapes. In a mirror, the portal stays
authoritative and GeoLens keeps pulling changes from it. In an exit, GeoLens
takes over and the portal can be retired.

A mirror needs a stored portal credential and scheduled refresh, which are paid
capabilities, plus incremental sync, which isn't built. It also keeps the
organization paying for ArcGIS. GeoLens builds no mirror mode. Scheduled
refresh in the Enterprise image comes close for a portal that stays in
service, but it replaces whole tables rather than syncing changes.

## Decision

An ArcGIS migration is a one-way exit. Service layers arrive through a service
import and data files through an upload, each as a managed copy. Every
dataset records the portal item id and portal URL as provenance.

Until cutover the operator can run the migration again. A rerun merges new
portal items into the migration plan without losing the operator's edits,
brings migrated datasets up to date (a refresh for service imports, a replace
for files), and keeps datasets whose items were deleted in the portal. A
refresh that stops for review is reported and never accepted on the
operator's behalf, so edits made in GeoLens aren't silently overwritten.

Cutover is the last run, made after edits in the portal are frozen. It refuses
while a migrated layer carries content GeoLens can't hold yet, such as
attachments, unless the operator accepts that loss. From then on GeoLens is
the system of record. Nothing detaches a migrated dataset from its source;
after the portal is retired, a refresh fails with the service's own error.

## Consequences

The migration has no sync job and needs no stored credential. What it can't
carry over goes into the loss report, and the operator has to deal with each
gap before cutover, because the portal is gone afterwards.
