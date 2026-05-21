# Quick Task 260331-9wb: Add raster extensions to default allowed upload extensions - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Task Boundary

The admin Storage settings page shows `.zip,.gpkg,.geojson,.json,.csv` as the allowed extensions — missing `.tif`, `.tiff`, `.xlsx`, `.xls` that are in the env default. This is because a DB override was saved before raster support (v10.0) was added and never updated.

</domain>

<decisions>
## Implementation Decisions

### Fix approach
- Reset the DB override for `upload_allowed_extensions` so the env default (`.zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls`) takes effect
- No Alembic migration — just reset the stored value

### Extension scope
- Only `.tif` and `.tiff` for raster — the only formats the ingest pipeline supports today
- No `.vrt` (created server-side), no additional GDAL formats

### Claude's Discretion
- Method of resetting: data migration vs. manual reset vs. programmatic reset at startup

</decisions>

<specifics>
## Specific Ideas

- The `PersistentConfig` system supports `.reset()` which deletes the DB row and reverts to env_default
- Could add an Alembic data migration that DELETEs the `upload_allowed_extensions` row from `app_settings`
- Alternatively, document that admin should click "Reset" on the setting in the UI

</specifics>
