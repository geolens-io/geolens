# ADR-007: A dashboard belongs to one map

**Status:** accepted. **Scope:** whether a dashboard is part of a saved map
or an item of its own.

## Context

In GeoLens a dashboard is a panel of widgets saved with a map. It follows the
map's visibility, share link and embed token, and its widgets summarize the
map's saved layers. ArcGIS Dashboards are items of their own that can hold no
map, one map or several.

A sample of 328 public ArcGIS Online dashboards (2026-10-30) found 27% with no
map widget, 59% with one and 14% with two or more.

## Decision

A dashboard stays part of one map. Dashboards that have no map are covered by
letting an author hide the map so the widgets fill the page. Dashboards with
two or more map widgets, on the same web map or not, are an ArcGIS migration
loss item: the migration report names those it can count and lists one whose
widgets it could not read for inspection, and an operator converts each one to
a single-map dashboard or splits it.

A standalone dashboard item was rejected. It would need its own visibility,
group sharing, share links, embed tokens, catalog entry and a rule for
widgets whose layers sit in maps the reader can't open, which would be a
second access model beside the map's. Keeping the dashboard inside its map
means widgets can only read layers the map's readers can already see.

## Consequences

The dashboard's layer picker lists only the map's saved layers. A dashboard
with its map hidden still has a map behind it, so its layers, filters and
picks work the same way, and View scope is unavailable there.

Revisiting this means designing the standalone item's access model, not
lifting the panel out of the map.
