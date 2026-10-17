# README assets

Images embedded in the top-level `README.md`. They're committed here because
GitHub renders README images from the repository itself, not from an
external URL or CDN. Keep finished images in this folder; keep the *capture
tooling* out of this public repo (see "Where the tooling lives" below).

## Current set

`README.md` shows six images, each next to the claim it supports. All are 1600×900
except the provenance crop. The browser shots come in light and dark pairs wired
through `<picture>` + `prefers-color-scheme`, so GitHub serves the variant that
matches the reader's theme. Use PNG for UI shots (crisp text) and JPG for maps
and terrain (smaller).

| File | Section | Shows | Subject |
| --- | --- | --- | --- |
| `geolens-manhattan-3d-hero{,-dark}.jpg` | Hero | Manhattan's buildings extruded to roof height, colored by era, with the subway | **Manhattan - A Century of Skyline** map in the builder |
| `geolens-catalog-search{,-dark}.png` | One catalog | Search by meaning with origin and freshness badges | Public catalog, signed out, search `where storms hit the coast` |
| `geolens-provenance{,-dark}.png` | Provenance | Source tab of a live service import: owned copy, refresh and check times, Healthy, Fresh, No drift | A dataset imported from the USGS Recent Earthquakes ArcGIS service, update frequency set to daily, after one refresh and one source check |
| `geolens-matterhorn-terrain{,-dark}.jpg` | Maps | Matterhorn 3D terrain mesh, layer stack, legend | **The Matterhorn in 3D** map at its saved camera |
| `geolens-qgis.png` | Use the data | QGIS 4 reading the demo over OGC API Features, with the connection open in the Browser panel | `https://demo.getgeolens.com/api/` with Recent Earthquakes, Significant Volcanic Eruptions, Tectonic Plate Boundaries and World Countries loaded |
| `geolens-ask-ai{,-dark}.png` | AI | Dataset Q&A with a count table, the stated assumption and Open in builder | **Major Hurricane Tracks** dataset, Ask AI: `How many of these hurricanes made landfall?` |

The other images here are not in `README.md`. The translated READMEs, announcement
posts and older release notes link to them, so they stay until nothing does.

## Seeding the data

`scripts/seed-showcase.py` builds the showcase maps and datasets behind the hero,
search, terrain and Ask AI shots. Terrain is built by default.

```bash
# The script reads GEOLENS_ADMIN_PASSWORD from the environment.
python scripts/seed-showcase.py --username "${GEOLENS_ADMIN_USERNAME:-admin}"
```

Search by meaning needs an embedding provider and **Admin → Settings → AI → Semantic
Search** turned on. The provenance shot needs a dataset imported from a live
service (the Service URL tab of the import page), so it shows a real refresh and
source check.

## Reproducing the shots

The 2026-10-16 set was captured by hand against a fresh, seeded stack: Playwright
at a 1600×900 viewport, once with `prefers-color-scheme: light` and once with
`dark`, and the search shot from a signed-out browser context. The QGIS shot comes
from a PyQGIS script run with `--code` that adds the connection and layers and
saves `iface.mainWindow().grab()`, downscaled from 2x.

The private getgeolens.com site repo also has an automated recipe,
`npm run capture:readme`, that writes straight into this folder. It still
captures the previous framing (the hero with the layer editor open and the older
search), so don't run it over this set until it is updated.

Review the `git diff` here before committing; these images are public.

## Keeping the committed files intact

`npm run check:readme-assets` (from the repo root) pins every image in this
folder to an exact pixel size and fails if one moves. CI runs it on every PR, and
there is a pre-commit hook for it.

It exists because these files get silently downscaled. The `image-sanitizer`
Claude Code plugin hooks the **Read** tool and runs `magick -resize` in place on
anything wider than 1200px, so a committed image loses resolution the moment
somebody opens it to look at it — long after whatever produced it exited. Never
open a master with an image-previewing tool. Measure with `sips -g pixelWidth -g
pixelHeight`, and copy to a throwaway path first if you want to see one.

Adding an image here means adding it to `scripts/check-readme-assets.mjs` too;
the gate fails on an unpinned file rather than ignoring it.

## Capture notes

- Keep the images free of private or draft dataset titles, internal hostnames and
  personal data. A throwaway stack seeded from scratch is the easiest way.
- Optionally strip metadata before committing (`magick in.png -strip out.png`;
  JPG at quality ~88 for maps and terrain).

## Where the tooling lives

The reusable Playwright capture machinery and the canonical capture recipe live
in the private getgeolens.com site repo (it drives that site's own
marketing/docs screenshots, and `capture:readme` is a third target list sharing
the same core). Do not add capture scripts to this public repo. The recipe writes
finished images in from the live stack, the same way brand assets are vendored
(`BRANDING-VERSION`) — the copy is automated, the tooling stays out.
