# 1.21 demo content rollout

This is the operator record for the [showcase seed](../seed-showcase.py), its
[state snapshot tool](../showcase-121-state.py), and the [issues found during
rehearsal](ISSUES.md). It does not authorize a public demo change. As checked on
September 27, 2026, the latest GitHub release was `v1.20.0`; the isolated
rehearsal checkout started at `66a76cd2c1f3c4cd18061c4a892fc9e93f25a07d` and
was rebased onto `origin/main` `8653c4b79` the same evening; the staging API
bind-mounts the checkout, so it now runs that code.
Recheck the release, deployed build, and current main before applying this plan.

The public demo had seven maps, 28 public datasets, and two collections in the
read-only inventory. Its health endpoint reported `1.20.0`. The rehearsal uses
the separate `showcase121` Compose project from the showcase worktree, with
frontend/API/DB on localhost ports 63578/63577/63576. The project serves the
worktree files; the shared primary checkout and its stack are separate. Its
health endpoint also reports `1.20.0` because the application version was not
bumped for this content change. That label alone does not prove the container
image's source commit. Record the built image digests and final source commits
in the deployment record before public rollout.

## Source and prepared artifact manifest

All sizes and hashes below were measured on the rehearsal artifacts. The large
files stay outside Git. A source changing bytes is a stop condition: review the
new source and update the pinned preparation script and manifest deliberately.

| Artifact and use | Source, terms, and geographic facts | Prepared result |
| --- | --- | --- |
| East Village canopy source for **City in Shade** | [NYC Tree Canopy Change, 2010-2017](https://data.cityofnewyork.us/d/by9k-vhck), produced by NYC OTI with the University of Vermont and partners. [Publisher metadata](https://github.com/CityOfNewYork/nyc-geo-metadata/blob/main/Metadata/Metadata_TreeCanopyChange.md) defines Gain, Loss, and No Change and identifies EPSG:2263 for the original data. [NYC Open Data](https://www.nyc.gov/opendata/get-started/FAQs) says its open data has no reuse restrictions; the [portal terms](https://data.cityofnewyork.us/stories/s/Terms-of-Use/k9k7-3cje/) still apply. The pinned download is a 666,685,898-byte GDB ZIP, SHA-256 `ee33f316e770fa3173892df3a334304dbd96f21eb7ffa76a550f80b57f571663`. | [Preparation script](../prepare-showcase-canopy.sh) selects and clips to WGS84 `[-73.989, 40.722, -73.973, 40.734]`. GeoJSON: 19,984,141 bytes; 16,345 polygons (11,476 Gain, 2,365 Loss, 2,504 No Change); SHA-256 `3cdb1bff4780691bfc70bb97c08a9f7fab607436ab7110c5c56b7dc1f70c8af4`. This is external preprocessing. GeoLens then materializes a separate clip to the rectangular Tompkins study window `[-73.9822, 40.7238, -73.9768, 40.7284]`, which is **not** the park boundary. Neither subset is a citywide measure or a current shade estimate. |
| Autzen Stadium classified point cloud, for an external COPC client | [PDAL/data Autzen file](https://github.com/PDAL/data/tree/main/autzen) and [PDAL/data license](https://github.com/PDAL/data/blob/main/LICENSE): CC BY 4.0, credit PDAL/data and link the license. Horizontal EPSG:2992; NAVD88 heights in US survey feet. Acquisition date is unverified. | Real COPC LAZ, 81,123,042 bytes; 10,653,336 points, point format 7; WGS84 extent `[-123.075542, 44.049719, -123.061960, 44.062780]`; SHA-256 `db2d56cdfa058bffccdc5d6019dae2fc9c6a551df10a5523c06c76a3e25a27fa`. No conversion was needed. |
| Central Amsterdam buildings, for an external 3D Tiles client | [3DBAG release `v20250903`](https://docs.3dbag.nl/en/delivery/webservices/), LoD 1.2. Its [copyright page](https://docs.3dbag.nl/en/copyright/) licenses the data under CC BY 4.0 and requires the credit **“© 3DBAG by tudelft3d and 3DGI”**, a link to that page, and notice of modifications. In a browsable map the credit belongs at bottom right. The release date is not an individual building acquisition date. | [Preparation script](../prepare-showcase-tiles3d.py) selects one hierarchy branch and its four GLBs without changing geometry. The source manifest SHA-256 is `9f9e4b0945838f91e2958988bf885d1cf176cb93ac2ff632d9ceb6e18c38ad1f`. The deterministic ZIP is 1,823,998 bytes, SHA-256 `28b6ccf9ed89cb378bd34019f3194a92e16c9bad27684166aa9d9c4639a01bb4`; unpacked tileset content totals 2,822,533 bytes. Its ECEF bounding box corners correspond approximately to WGS84 `[4.882770, 52.361631, 4.900449, 52.372465]`. The four GLBs have uniform colors, no textures, and require `EXT_meshopt_compression` and `KHR_mesh_quantization`. |

Prepare the files in a protected artifact directory. The two preparation scripts
refuse to overwrite existing outputs. The COPC URL and checksum are pinned by
the seed, so a different file fails before upload.

```bash
bash scripts/prepare-showcase-canopy.sh "$ARTIFACT_DIR/east-village-canopy-change.geojson"
curl -fL --retry 3 -o "$ARTIFACT_DIR/autzen-classified.copc.laz" \
  'https://media.githubusercontent.com/media/PDAL/data/refs/heads/main/autzen/autzen-classified.copc.laz'
python3 scripts/prepare-showcase-tiles3d.py "$ARTIFACT_DIR/amsterdam-3dbag.zip"
shasum -a 256 "$ARTIFACT_DIR"/*
```

The exact artifact storage location for a public rollout is **unassigned**.
Record it, access controls, and the final hashes in the deployment record. Do
not put the files, credentials, or private share/embed links in this repository.

## What the rehearsal established

On the separate staging project, the canopy source imported with 16,345
features; GeoLens produced a materialized clip from the rectangular mask and
published City in Shade. The COPC dataset reported 10,653,336 points and served
a 16-byte `Range` request with HTTP 206. The final MapLibre example, served
from the staging allowlisted origin, rendered the stadium from GeoLens-hosted
COPC byte-range 206 responses. The 3D Tiles dataset reported all four GLB contents;
the final Cesium example fetched GeoLens's tileset and four GLBs with 200
responses and rendered buildings. Neither final example produced a browser
error in that staging check. These are local staging results, not public demo
results. GeoLens catalogs and serves both formats; its own map viewer does not
render them.

The first full staging seed exited nonzero because the USGS earthquake service
was down upstream, and Restless Earth was built from a 2,000-feature snapshot.
Once the service recovered, a guarded `--only restless` run converted both
quake datasets to the service binding in place, and `--refresh-quakes` pulled
1,971 current features with source health `healthy`. No deployment config
schedules `--refresh-quakes`, so the public quakes stay overdue until an
operator runs it. An Overpass 504 left Matterhorn's OSM
overlays incomplete in that run. A subsequent retry used checksum-pinned route
and peak exports from the public datasets and restored all three layers on the
same map ID. The route file has 22 features and SHA-256
`fb331860d35ceb0c5a10520a64369b7e961205a4caa92099df6f8490d9b42a79`;
the peak file has five features and SHA-256
`5ab03d3304e46bf1c6db649a9164c8324fcb1de49781ad012917682d5b02c3c0`.
Keep these artifacts available for a public reseed if Overpass remains down.
See [ISSUES.md](ISSUES.md).

The observed staging-only IDs are City in Shade
`d1391fcc-7edd-4553-968e-de3c8a297234`, its source subset
`06219cdf-b38b-4845-a2f7-917223a080fe`, Autzen COPC
`fb575ea0-3421-45a0-bc2c-ded40ee2b6f3`, Amsterdam 3D Tiles
`64177d1b-8959-4cdc-b0c0-fe61a8788a45`, and Restless Earth
`ce8a6c2b-14ac-4eaa-80e7-db366205cee4`. They are not public demo IDs.

Playwright MCP checked Manhattan, Hurricane Exposure, City in Shade,
Matterhorn, Restless Earth, and New York From Orbit at 1440×900, 1366×768,
and 390×844. Each reached strict `data-map-ready`, made multiple successful
tile/feature requests, had no page or HTTP errors, and had no horizontal
overflow. Matterhorn also reached `data-terrain-ready`. Ignored local evidence
is in `.playwright-mcp/showcase121-{name}-{size}.png` in the primary checkout;
it must be attached separately for PR review. This network/readiness check
does not make every scene visually complete: Matterhorn routes/peaks were
missing during this first pass. After their retry, a 1440×900 check showed
routes, casing, peak labels, and terrain. A first
Manhattan pass exposed a subway-route legend that displaced building eras;
the route legend was hidden and Playwright then showed building eras in the
legend. Orbit's first camera showed an eastern imagery edge. The revised
camera `[-74.015, 40.725, 11.1]` had no image edge in
`.playwright-mcp/showcase121-orbit-final-v2.png`. Those findings are recorded
in [ISSUES.md](ISSUES.md). No separate load-timing study was run. As a rough
observation, the demo smoke's Matterhorn test took 9.7-10.4 s on a server-cold
staging stack and 8.6-8.9 s warm, measured from gallery search to a ready,
terrain-loaded map on this laptop. That is not a performance guarantee.

After a metadata replay, the staging API showed the corrected East Village
source summary and nonempty CC BY attribution for both client sample datasets.
The final Cesium example placed the required 3DBAG credit and copyright link at the
bottom right and disclosed its four-tile extraction. The public target still
needs the same checks after rollout.

The staging thumbnail backfill filled all nine missing maps. The first Orbit
thumbnail still contained mixed or missing raster tiles. After its map imagery
settled, an authorized builder **Save** triggered a fresh native capture and
the gallery showed a clean 400×250 thumbnail in
`.playwright-mcp/showcase121-gallery-final.png`. The partial first capture is
recorded as a bug in [ISSUES.md](ISSUES.md); a nonblank thumbnail is not proof
that all raster tiles have loaded.

A protected staging snapshot captured eight maps, 27 owned showcase datasets,
and three collections after the seed. In a rollback rehearsal, changing the
Manhattan camera/description, Hurricane input visibility, Natural Earth
metadata/keyword, and Human World membership/description and then restoring
produced an identical second snapshot. This tested restoration of controlled
edits **after** seeding. It did not test a pre-upgrade public snapshot or
rollback of the USGS service binding. Map thumbnails, private share tokens,
analysis tables, and external artifact files are outside this snapshot.

The presentation order is Manhattan (height and era), City in Shade (inspect
gain and loss, then its source and GeoLens clip), Hurricane Exposure (toggle
historical tracks against the derived corridor), Matterhorn (terrain and DEM
source), and Restless Earth (read the actual snapshot date and source state).
The COPC and 3D Tiles clients are a separate connection walkthrough. Keep
Hurricane Alley, Meteorites, and New York From Orbit reachable as additional
examples. No AI step is required.

## Guarded update and rollback

1. Recheck deployed version, source commits, release status, current map and
   dataset IDs, and external references. The four externally pinned map rows
   are Restless Earth `ca1c9bb8-01a9-40ba-9e56-d1e015613a7e`, Manhattan
   `146eddc1-30af-4c8e-aa6f-a6569e663823`, Matterhorn
   `05633c96-8c7b-40c0-93eb-fe8f40212e23`, and New York From Orbit
   `71c658e5-d7c0-4b12-8bab-3b4ee6968cd5` in the September 27 read-only
   inventory. Confirm them again immediately before mutation.
2. With the target credentials supplied through protected environment
   variables, save a new **pre-update** snapshot using
   `python3 scripts/showcase-121-state.py snapshot "$BUNDLE" --base-url "$GEOLENS_BASE_URL"`.
   The tool creates a mode-600 file and refuses to overwrite it. Store the
   bundle off-host too. Check that it contains the expected owned rows and
   that no other operator has changed the target since capture.
3. Apply only after the intended 1.21 release is deployed and the final PRs
   are reviewed. Use explicit artifacts and the snapshot precondition:

   ```bash
   python3 scripts/seed-showcase.py \
     --base-url "$GEOLENS_BASE_URL" --showcase-121 \
     --expected-state "$BUNDLE" \
     --canopy-geojson "$ARTIFACT_DIR/east-village-canopy-change.geojson" \
     --copc-file "$ARTIFACT_DIR/autzen-classified.copc.laz" \
     --tiles3d-archive "$ARTIFACT_DIR/amsterdam-3dbag.zip" \
     --no-thumbnails
   ```

   Avoid `--force`, `--force-pinned`, `--prune`, and `--prune-userdata`. If a
   source or expected-state check fails, stop and inspect the target. The
   seed also refuses when it would change something restore cannot undo: a
   legacy map or dataset name it would rename, or an earthquake dataset that
   is not yet bound to its USGS service. It also refuses before any write when
   the Manhattan or New York From Orbit camera matches neither its expected
   baseline nor the new view. The September 27 public inventory had
   neither; both quake datasets already report `origin: service`. The
   guarded seed does not provide a database transaction over all builders.
   With `--expected-state`, the seed first waits 61 seconds so the cached
   admin dataset list cannot hide a row an interrupted run committed.
   After an interrupted or partial run, the original bundle no longer matches
   and the seed refuses it. Keep that bundle for rollback, write a new
   snapshot to a different path, and pass the new file as `--expected-state`
   for the retry. Several logins in a minute can hit the login rate limit
   (HTTP 429); wait a minute before retrying.
   Then refresh the quakes from their service binding:
   `python3 scripts/seed-showcase.py --base-url "$GEOLENS_BASE_URL" --refresh-quakes`.
4. Verify unchanged public URLs and embeds, metadata, collections, analysis
   provenance, anonymous asset access, byte ranges, and browser rendering at
   desktop, laptop-height, and mobile widths. Inspect final thumbnails. The
   existing thumbnail backfill script fills *missing* images only. For an
   existing stale or partially painted image, open that map in the authorized
   builder, wait until its intended imagery has visibly settled and data
   requests have completed, then use **Save**. The builder's save path
   recaptures the thumbnail. Reopen the gallery and inspect the stored 400×250
   image; repeat the save if the first capture raced a raster tile. Do not
   call the check complete from a basemap-only screenshot or a fixed timer.
5. If the rollout fails, stop further builders. Use the same credentials and
   instance to run
   `python3 scripts/showcase-121-state.py restore "$BUNDLE" --base-url "$GEOLENS_BASE_URL"`.
   The tool verifies the saved owner and existing map/layer/dataset/collection
   identities, restores captured editable fields and collection membership,
   unpublishes newly named showcase maps/datasets, and removes a new Client
   Connections collection only when it contains only new showcase datasets.
   The seed restyles some layers by swapping in a copy, adding it and removing
   the original in one request so no embed token scoped to that dataset is
   revoked. The copy has a new ID. Restore matches it to the saved layer by
   dataset and display name, and refuses when the match is missing or
   ambiguous. It removes Matterhorn route
   and peak layers that an overlay repair added; any other new layer except
   the hurricane context layer stops the restore.
   Restore does not undo a quake `--refresh-quakes` pull, which is ordinary
   source maintenance rather than showcase content. The snapshot covers every
   dataset the seed's metadata pass edits, including the Sentinel-2 scenes and
   swissALTI3D tiles matched by title prefix. All refusals are checked before
   the first write. Restore waits 61 seconds for the cached admin dataset list
   before reading the target. After writing, it reads the target again and exits
   nonzero, naming each map, dataset, or collection that still differs from
   the bundle, or any new showcase map or dataset still public. One case it
   would report: a description the API cannot clear back to null.
   `--expected-state` refuses `--refresh-quakes` and `--refresh-hurdat2`,
   whose data replacement the snapshot cannot undo; run the quake refresh as
   its own step.
   After a rollback, the guarded seed refuses before any write while the City
   in Shade map or any new sample dataset is private. Review them and publish
   them deliberately (datasets first, then the map) before applying again.
   A guarded update skips the automatic Sentinel-2 refresh, because a moved
   asset pointer is outside the snapshot.
   It does not delete the new datasets or restore the whole database. Confirm
   the original pinned URLs, access, and embed behavior after restoration.

The staging role checks used real accounts and backend authorization. Their
protected status report is `/tmp/geolens-demo-121-role-report.json` (mode 600);
it is local evidence, not a file to commit or publish.

| Role | Observed staging behavior | Remaining limit |
| --- | --- | --- |
| Anonymous | Public map/dataset 200, private map/dataset 404, COPC range 206, 3D Tiles manifest 200, public export 200 | Public deployment still untested |
| Authenticated viewer | Same public reads and private denials; map creation and showcase edit 403; public export 200 | Public deployment still untested |
| Editor/owner | Own map creation 201, public canopy layer add 201, own map edit 200, analysis preview/materialize 200 with job complete, own derived refresh accepted 202; showcase edit/refresh 403 | Public deployment still untested |
| Administrator | Public and private map/dataset 200; COPC 206 and 3D Tiles manifest 200; job list, per-dataset jobs, refresh runs, and source health (`healthy`, service origin) all respond | Staging runs Community: scheduled sync is a paid capability and absent; the manual refresh path passed |
| Restricted export | A temporary viewer export-disabled permission matrix kept public reads at 200, denied export with 403, and was restored with 200 | Community roles are fixed (`admin`, `editor`, `viewer`), so creating a `restricted_custom` user correctly returned 422; the matrix is the configurable control |

These are staging results only.

The full demo smoke on staging passed every map except Matterhorn, which
intermittently throws a MapLibre `shaderPreludeCode` error on a server-cold
load ([#2428](https://github.com/geolens-io/geolens/issues/2428); one failure
in four repeats). The earlier Orbit failures came from a wrong short title, and
the 429s did not recur. The SSO and DCAT-US failures come from staging
configuration: no SSO providers and no DCAT contact address. Backfill generated
nine staging thumbnails. Orbit and Matterhorn were recaptured with a builder
Save after their scenes settled. Public thumbnails need the same check after
rollout, and the full live smoke has to wait for the deployed target version.

### Upgrade rehearsal

A second isolated project (`showcase121u`, ports 63586-63588) was seeded with
`origin/main`'s seed script, the generation the public demo runs. A share link
was minted on Restless Earth; the seed's private embed token was also kept.
The guarded update above then exited 0. All seven map IDs and every existing
dataset ID survived. City in Shade and five datasets were added. Restyling
replaced one layer each on Manhattan, Hurricane Exposure, and Restless Earth,
with the same dataset and name. That run skipped the Client Connections
collection because the cached admin dataset list had not yet shown the new
samples. The seed now reads titles it created itself. A retry with a fresh
precondition snapshot created that collection and changed nothing else: no
layer churn, no duplicate maps or datasets. Restoring the pre-update bundle
then reproduced every captured map, layer, dataset, and collection field (zero
differences), unpublished the new map and datasets, and removed Client
Connections. The share link (200) and embed (204, 403 without its token)
worked before, during, and after.

An adversarial review then found three more rollback gaps, and all three were
fixed and rehearsed. First, the layer delete revoked embed tokens scoped to the
restyled layer's dataset. The swap now happens in one request, and an embed
token minted on Manhattan stayed active through a re-apply and two restores.
Second, the snapshot missed the prefix-matched Sentinel-2 scenes. With the
scenes set back to main's `continual` cadence, the update changed them to
`notPlanned` and restore put `continual` back, again with zero differences.
Third, a new Client Connections collection holding pre-existing samples blocked
the final restore step. That check now runs before any write.
The standard post-deployment smoke is
`E2E_DEMO_BASE_URL=https://demo.getgeolens.com E2E_EXPECT_VERSION=1.21.0 npm run e2e:smoke:demo`.

Deferred work stays separate: Earth After Dark, temperature overlays, a
featured gallery, native COPC/3D Tiles rendering, timelines, and swipe views.
