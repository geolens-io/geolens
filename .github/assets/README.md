# README assets

Images embedded in the top-level `README.md` and its translations. They're
committed here because GitHub renders README images from the repository itself,
not from an external URL or CDN.

## Current set

Besides the logo, `README.md` shows 15 images: the hero, a ten-tile grid under "A closer look", and
full-width shots for provenance, QGIS and Ask AI. All are 1600×900 except the
provenance crop. The browser shots come in light and dark pairs wired through
`<picture>` + `prefers-color-scheme`, so GitHub serves the variant that matches
the reader's theme. Use PNG for UI shots (crisp text) and JPG for maps, terrain
and imagery (smaller).

| File | Section | Shows | Subject |
| --- | --- | --- | --- |
| `geolens-manhattan-3d-hero{,-dark}.jpg` | Hero | Manhattan's buildings extruded to roof height, colored by era, with the subway | **Manhattan - A Century of Skyline** map in the builder |
| `geolens-catalog-search{,-dark}.png` | Grid | Search by meaning with origin and freshness badges | Public catalog, signed out, search `where storms hit the coast` |
| `geolens-dataset-page{,-dark}.png` | Grid | Dataset overview: map preview, badges, feature count, geometry, CRS, version | **Atlantic Hurricane Tracks (HURDAT2, majors since 1950)** |
| `geolens-import-preview{,-dark}.png` | Grid | Service preview: CRS, geometry, feature count, sample rows | Service URL tab, `https://earthquake.usgs.gov/arcgis/rest/services/eq/Recent_Earthquakes/MapServer`, layer **Significant Earthquakes** |
| `geolens-version-history{,-dark}.png` | Grid | Three versions, the current one marked, Restore on the previous one | **Significant Volcanic Eruptions** after two re-uploads, Metadata tab with History expanded |
| `geolens-builder-style{,-dark}.png` | Grid | Heatmap style panel, grouped layer list, globe | **Restless Earth** map with **Quake intensity (heatmap)** selected and the legend closed |
| `geolens-matterhorn-terrain{,-dark}.jpg` | Grid | Matterhorn 3D terrain mesh, layer stack, legend | **The Matterhorn in 3D** map at its saved camera |
| `geolens-stac-imagery{,-dark}.jpg` | Grid | Four Sentinel-2 scenes referenced from Earth Search, with the legend | **New York From Orbit - Sentinel-2, by Reference** map |
| `geolens-share-embed{,-dark}.png` | Grid | Share dialog: visibility, share link, embed code | **Restless Earth** map after Generate Share Link |
| `geolens-admin-overview{,-dark}.png` | Grid | Health checks, dataset counts, storage used | Admin → Overview after a full seed |
| `geolens-admin-permissions{,-dark}.png` | Grid | Capabilities per role | Admin → Settings → Permissions with the default roles |
| `geolens-provenance{,-dark}.png` | Provenance | Source tab of a live service import: owned copy, refresh and check times, Healthy, Fresh, No drift | A dataset imported from the USGS Recent Earthquakes ArcGIS service, update frequency set to daily, after one refresh and one source check |
| `geolens-qgis.png` | Use the data | QGIS 4 reading the demo over OGC API Features, with the connection open in the Browser panel | `https://demo.getgeolens.com/api/` with Recent Earthquakes, Significant Volcanic Eruptions, Tectonic Plate Boundaries and World Countries loaded |
| `geolens-ask-ai{,-dark}.png` | AI | Dataset Q&A with a count table, the stated assumption and Open in builder | **Major Hurricane Tracks** dataset, Ask AI: `How many of these hurricanes made landfall?` |

The logo is the reticle emblem from `geolens-io/branding`, as light and dark SVGs
(`geolens-emblem{,-dark}.svg`). `BRANDING-VERSION` records the release they came
from; update them by syncing a newer release rather than editing them here.

## Seeding the data

`scripts/seed-showcase.py` builds the showcase maps and datasets behind the hero,
the grid's map and dataset shots, and the Ask AI shot. Terrain is built by default.

```bash
# The script reads GEOLENS_ADMIN_PASSWORD from the environment.
python scripts/seed-showcase.py --username "${GEOLENS_ADMIN_USERNAME:-admin}"
```

Search by meaning needs an embedding provider and **Admin → Settings → AI → Semantic
Search** turned on. The provenance shot needs a dataset imported from a live
service (the Service URL tab of the import page), so it shows a real refresh and
source check. The version history shot needs a dataset replaced twice, and the
admin shots had six sample editor and viewer accounts added.

## Reproducing the shots

All shots were captured by hand against a fresh, seeded stack with Playwright,
once with `prefers-color-scheme: light` and once with `dark`, and the search shot
from a signed-out browser context. The hero, provenance, terrain and Ask AI shots
(2026-10-16) used a 1600×900 viewport. The other grid tiles (2026-10-17) were
captured at 2x and scaled down to 1600×900 from smaller viewports, so their text
stays readable at half width: 1280×720 for search, import and admin, 1440×810 for
the map builder and dataset page, and 1024×576 for version history. The QGIS shot
comes from a PyQGIS script run with `--code` that adds the connection and layers
and saves `iface.mainWindow().grab()`, downscaled from 2x.

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
