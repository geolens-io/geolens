# README assets

Images embedded in the top-level `README.md`. They're committed here because
GitHub renders README images from the repository itself, not from an
external URL or CDN. Keep finished images in this folder; keep the *capture
tooling* out of this public repo (see "Where the tooling lives" below).

## Current set

The README hero plus a four-step Find -> Inspect -> Build -> Ask AI story.
Displayed at `width="900"`; sources are ~1200 px wide. Use PNG for UI shots
(crisp text) and JPG for photographic 3D terrain (smaller).

| File | Beat | Shows | How to reproduce (live seeded stack) |
| --- | --- | --- | --- |
| `geolens-manhattan-3d-hero.jpg` | Hero | Manhattan footprints extruded to roof height in the builder | Open the **Manhattan Skyline - Real Roof Heights** map in the builder |
| `geolens-search.png` | Find | Semantic search ranking hydrology datasets | Catalog at `/?q=hydrology` (dismiss the autocomplete before the shot) |
| `geolens-dataset.png` | Inspect | Dataset map preview + typed attribute table | Rivers Lake Centerlines (10m) dataset, Data tab |
| `geolens-matterhorn-terrain.jpg` | Build | Matterhorn 3D terrain mesh + layer stack | Open The Matterhorn - swissALTI3D 3D Terrain map in the builder |
| `geolens-ai-labels.png` | Ask AI | AI adding county labels to a choropleth | New York Income by County map, Ask AI, "Add area labels" |

## Seeding the data

`scripts/seed-showcase.py` builds the demo maps behind the hero,
Build (Matterhorn), and Ask AI (NY income) shots:

```bash
python scripts/seed-showcase.py \
  --username "${GEOLENS_ADMIN_USERNAME:-admin}" \
  --password "$GEOLENS_ADMIN_PASSWORD" \
  --with-terrain
```

The Find (search) and Inspect (dataset) shots use a Natural Earth vector
catalog: rivers, lakes, subwatersheds. There is no bundled seeder for those;
load them into the catalog via the import flow (`geolens publish` / a manifest,
see the main README) before capturing.

## Capture notes

- Capture from a live stack at `http://localhost:8080` (username `admin` and
  the generated password from `.env`),
  viewport ~1280×800 / 1600×900, then crop/scale to ~1200 px wide and optimize
  (e.g. `magick in.png -strip out.png`; JPG at quality ~88 for terrain).
- The Matterhorn camera was framed via the live MapLibre map
  (`jumpTo` ≈ `{ center: [7.66, 45.97], zoom: 13.7, pitch: 60, bearing: -122 }`,
  with left padding for the layer panel). The builder caps pitch at 60°.
- These images are public. Keep them free of private/draft dataset titles,
  internal hostnames, and PII.

## Where the tooling lives

The reusable Playwright capture machinery and the canonical capture recipe live
in the private getgeolens.com site repo (it drives that site's own
marketing/docs screenshots). Do not add capture scripts to this public repo.
Capture from the live stack and copy the finished images in, the same way brand
assets are vendored (`BRANDING-VERSION`).
