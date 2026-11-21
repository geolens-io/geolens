# README assets

Images embedded in the top-level `README.md` and its translations. They're
committed here because GitHub renders README images from the repository itself,
not from an external URL or CDN.

## Current set

Besides the logo, `README.md` shows 7 images: the hero, a four-tile grid under "A closer look", and
full-width shots for provenance and QGIS. All are 1600×900 except the provenance
crop (1600×694). The browser shots come in light and dark pairs wired through
`<picture>` + `prefers-color-scheme`, so GitHub serves the variant that matches
the reader's theme. Use PNG for UI shots (crisp text) and JPG for maps and
imagery (smaller).

| File | Section | Shows | Subject |
| --- | --- | --- | --- |
| `geolens-manhattan-3d-hero{,-dark}.jpg` | Hero | Manhattan's buildings extruded to roof height, colored by era, with the subway | **Manhattan: A Century of Skyline** map in the builder |
| `geolens-catalog-search{,-dark}.png` | Grid | Search by meaning with origin and freshness badges | Public catalog, signed out, search `where storms hit the coast` |
| `geolens-arcgis-webmap{,-dark}.jpg` | Grid | A map imported from an ArcGIS Online web map, in the builder with its layer list and legend | **Cambridge Open Data: Street Trees From an ArcGIS Online Web Map** |
| `geolens-story{,-dark}.jpg` | Grid | A published story as a reader sees it: a chapter beside a globe of storm tracks | **Where the Atlantic's Major Hurricanes Go**, signed out, first chapter |
| `geolens-dashboard{,-dark}.png` | Grid | A dashboard as a reader sees it: indicators, two pie charts and notes, with the map hidden | **Cambridge Open Data: Land and Zoning in Numbers**, signed out |
| `geolens-provenance{,-dark}.png` | Provenance | Source tab of a live service import: owned copy, refresh and check times, Healthy, Fresh, No drift | **Recent Earthquakes (M2.5+, last 30 days)**, right after a refresh from the USGS service |
| `geolens-qgis.png` | Use the data | QGIS 4 reading the demo over OGC API Features, with the connection open in the Browser panel | `https://demo.getgeolens.com/api/` with Recent Earthquakes, Significant Volcanic Eruptions, Tectonic Plate Boundaries and World Countries loaded |

The logo is the reticle emblem from `geolens-io/branding`, as light and dark SVGs
(`geolens-emblem{,-dark}.svg`). `BRANDING-VERSION` records the release they came
from; update them by syncing a newer release rather than editing them here.

## Seeding the data

`scripts/seed-showcase.py` builds the showcase maps, datasets, story and
dashboards behind the hero and the grid.

```bash
# The script reads GEOLENS_ADMIN_PASSWORD from the environment.
python scripts/seed-showcase.py --username "${GEOLENS_ADMIN_USERNAME:-admin}"
```

Search by meaning needs an embedding provider and **Admin → Settings → AI → Semantic
Search** turned on. The provenance shot needs a dataset imported from a live
service; refresh it from its Source tab just before the capture, so the panel
shows a current refresh and source check.

## Reproducing the shots

All browser shots (2026-11-21) were captured by hand against a seeded stack with
Playwright, each in its own browser context at device scale factor 2, once with
`prefers-color-scheme: light` and once with `dark`, then scaled down to 1600×900.
The search, story and dashboard shots come from a signed-out context. Viewports:
1600×900 for the hero, 1280×720 for search, and 1440×810 for the web map, story
and dashboard, so their text stays readable at half width. The provenance shot is
a clip of the dataset page from the tab row to the badges, at a 1600 px wide
viewport. The QGIS shot comes from a PyQGIS script run with `--code` that adds the
connection and layers and saves `iface.mainWindow().grab()`, downscaled from 2x.

Review the `git diff` here before committing; these images are public.

## Keeping the committed files intact

`npm run check:readme-assets` (from the repo root) pins every image in this
folder to an exact pixel size and fails if one moves. CI runs it on every PR, and
there is a pre-commit hook for it.

Some image tools resize a file in place when it is opened for viewing, so never
open a master with an image-previewing tool. Measure with `sips -g pixelWidth -g
pixelHeight`, and copy to a throwaway path first if you want to see one.

Adding an image here means adding it to `scripts/check-readme-assets.mjs` too;
the gate fails on an unpinned file rather than ignoring it.

## Capture notes

- Keep the images free of private or draft dataset titles, internal hostnames and
  personal data. A throwaway stack seeded from scratch is the easiest way.
- Optionally strip metadata before committing (`magick in.png -strip out.png`;
  JPG at quality ~88 for maps and terrain).
