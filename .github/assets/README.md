# README assets

Images embedded in the top-level `README.md`. They're committed here because
GitHub renders README images from the repository itself, not from an
external URL or CDN. Keep finished images in this folder; keep the *capture
tooling* out of this public repo (see "Where the tooling lives" below).

## Current set

The README hero plus a six-step Find -> Inspect -> Ask your data -> Build ->
Ask AI -> Operate story. Displayed at `width="900"`; sources are ~1200–1600 px
wide. Use PNG for UI shots (crisp text) and JPG for photographic 3D terrain
(smaller). Files with a `-dark` sibling are light/dark pairs wired into the
README via `<picture>` + `prefers-color-scheme` so GitHub serves the right
variant per theme.

| File | Beat | Shows | Subject (live seeded stack) |
| --- | --- | --- | --- |
| `geolens-manhattan-3d-hero.jpg` | Hero | Manhattan footprints extruded to roof height, colored by era, with the layer editor open | **Manhattan - A Century of Skyline** map, Buildings (3D) layer selected |
| `geolens-search.png` | Find | Semantic search: "natural disasters" ranks earthquakes + volcanic eruptions with no keyword match | Catalog, search `natural disasters` (2 results) |
| `geolens-dataset.png` | Inspect | Dataset map preview + typed metadata over a dense point cloud | **Meteorite Landings** dataset detail (32,186 points) |
| `geolens-dataset-chat{,-dark}.png` | Ask your data | Dataset Q&A in natural language: question -> answer + result table -> open in builder | **Meteorite Landings** detail, Ask AI: "How many meteorites were seen falling versus found later?" |
| `geolens-matterhorn-terrain.jpg` | Build | Matterhorn 3D terrain mesh + layer stack + legend | **The Matterhorn in 3D** map |
| `geolens-ai-labels.png` | Ask AI | AI editing a map in natural language | **Restless Earth** map, Ask AI: "Label the volcanoes with their names" |
| `geolens-admin-overview{,-dark}.png` | Operate | Admin overview: live health panel, dataset/storage totals, AI status | Admin -> Overview, seeded demo users |
| `geolens-admin-users{,-dark}.png` | — (announcements) | Admin user management: roles, status, quotas, CSV export | Admin -> Users; not embedded in the README — kept here as a stable public URL for announcement posts |

## Seeding the data

`scripts/seed-showcase.py` builds the showcase maps behind the Hero (Manhattan),
Build (Matterhorn), and Ask AI (Restless Earth) shots, plus the catalog datasets
the Find and Inspect shots use (the earthquake / volcanic-eruption datasets and
Meteorite Landings). Terrain is built by default.

```bash
python scripts/seed-showcase.py \
  --username "${GEOLENS_ADMIN_USERNAME:-admin}" \
  --password "$GEOLENS_ADMIN_PASSWORD"
```

## Reproducing the shots

The canonical recipe is now automated. From a checkout of the private
getgeolens.com site repo, sitting next to this one, against a live seeded stack:

```bash
cd ../getgeolens.com
GEOLENS_ADMIN_PASSWORD="$GEOLENS_ADMIN_PASSWORD" npm run capture:readme
# writes the original 5 images straight into this folder (GEOLENS_REPO_DIR, default ../geolens)
```

The 2026-07-21 additions (`geolens-dataset-chat`, `geolens-admin-overview`,
`geolens-admin-users`, light + dark pairs at 1200×750) were captured against the
local seeded stack with demo users seeded for the admin views; they are not yet
part of the automated `capture:readme` target list.

Then review the `git diff` here before committing — these images are public.

Two shots need a human eye after every run:

- **Ask AI** performs a real, non-deterministic AI edit that *mutates* the
  Restless Earth map. Re-seed to reset it; a second run against an
  already-labeled map is expected to fall back to the plain map.
- **Matterhorn** framing rides that map's saved camera (`jumpTo` ≈
  `{ center: [7.66, 45.97], zoom: 13.7, pitch: 60, bearing: -122 }`; the builder
  caps pitch at 60°). Adjust the saved map, not the script, to reframe.

The three content shots (Find / Inspect / Ask AI panel) are deterministic — they
are the ones that drift with catalog data, which is exactly what the automated
recipe keeps in parity with the marketing site.

## Capture notes

- Sources are captured at 1600×900; the README renders them at `width="900"`.
  Optionally strip/optimize before committing (e.g. `magick in.png -strip out.png`;
  JPG at quality ~88 for terrain).
- These images are public. Keep them free of private/draft dataset titles,
  internal hostnames, and PII.

## Where the tooling lives

The reusable Playwright capture machinery and the canonical capture recipe live
in the private getgeolens.com site repo (it drives that site's own
marketing/docs screenshots, and `capture:readme` is a third target list sharing
the same core). Do not add capture scripts to this public repo. The recipe writes
finished images in from the live stack, the same way brand assets are vendored
(`BRANDING-VERSION`) — the copy is automated, the tooling stays out.
