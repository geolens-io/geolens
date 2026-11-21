<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-emblem-dark.svg">
    <img src=".github/assets/geolens-emblem.svg" alt="GeoLens logo: a magnifying glass over a globe with crosshair ticks" width="96">
  </picture>
</p>

<h1 align="center">GeoLens</h1>

<p align="center">
  <b>An open-source, self-hosted alternative to ArcGIS Online: a spatial data catalog with maps, stories and dashboards.</b>
</p>

<p align="center">
  <a href="https://demo.getgeolens.com"><b>Live demo</b></a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="https://docs.getgeolens.com">Documentation</a> ·
  <a href="#use-the-data-from-anywhere">Connect QGIS or code</a> ·
  <a href="https://github.com/geolens-io/geolens/discussions">Discussions</a>
</p>

<div align="center">

[English](README.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [简体中文](README.zh.md)

[![Latest release](https://img.shields.io/github/v/release/geolens-io/geolens?style=flat-square&label=release)](https://github.com/geolens-io/geolens/releases/latest)
[![CI status](https://img.shields.io/github/actions/workflow/status/geolens-io/geolens/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/geolens-io/geolens/badge)](https://securityscorecards.dev/viewer/?uri=github.com/geolens-io/geolens)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/15857/badge)](https://www.bestpractices.dev/projects/15857)

</div>

<p align="center">
  <a href="https://demo.getgeolens.com/maps">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-manhattan-3d-hero-dark.jpg">
      <img src=".github/assets/geolens-manhattan-3d-hero.jpg" alt="The GeoLens map builder showing Manhattan's buildings extruded to their surveyed roof heights and colored by construction era, with the subway network, the layer list and a legend" width="100%">
    </picture>
  </a>
  <br>
  <sub>Manhattan's buildings at their surveyed roof heights, colored by construction era, with the subway network. <a href="https://demo.getgeolens.com/maps">Browse the demo's maps</a>.</sub>
</p>

GeoLens is for teams whose spatial data is spread across file shares, databases, web services and
STAC catalogs. It puts that data in one searchable catalog and records where each dataset came
from. Teams build maps, stories and dashboards in the browser and share them with groups or the
public, and QGIS, scripts and AI agents read the same data through OGC API and STAC. It runs on
your own servers with Docker Compose, sends no telemetry and is licensed under Apache 2.0.

The [demo](https://demo.getgeolens.com) needs no install or account; sign in with Google, GitHub
or Microsoft to use the map builder. Demo data may be wiped at any time.

## Quick start

You need Git, curl and Docker with the Compose plugin, with 8 GB of memory available to Docker.

```sh
curl -fsSL https://getgeolens.com/install.sh | sh    # clone, generate secrets, start the stack
cd geolens
grep '^GEOLENS_ADMIN_PASSWORD=' .env                  # the generated admin password
```

Open http://localhost:8080 and sign in as `admin` with that password. [Install](#install) covers
verifying the script, building from source and running in production.

## A closer look

<table>
<tr>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-catalog-search-dark.png">
<img src=".github/assets/geolens-catalog-search.png" alt="GeoLens catalog search for 'where storms hit the coast', signed out, listing hurricane and coastal datasets with type, source and freshness badges beside the dataset filters" width="100%">
</picture>
<br><sub>Search by meaning: "where storms hit the coast" finds hurricane tracks and coastal exposure layers.</sub>
</td>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-arcgis-webmap-dark.jpg">
<img src=".github/assets/geolens-arcgis-webmap.jpg" alt="The map builder with a map of Cambridge street trees imported from an ArcGIS Online web map: trees colored by site type, neighborhood outlines and names, the layer list and a legend" width="100%">
</picture>
<br><sub>An ArcGIS Online web map imported into GeoLens. Its colors, popups, outlines and zoom ranges carried over.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-story-dark.jpg">
<img src=".github/assets/geolens-story.jpg" alt="A published story, Where the Atlantic's Major Hurricanes Go: a chapter with a cover photo and text beside a globe of storm tracks colored by Saffir-Simpson category, with the legend" width="100%">
</picture>
<br><sub>A story walks readers through a map chapter by chapter.</sub>
</td>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-dashboard-dark.jpg">
<img src=".github/assets/geolens-dashboard.jpg" alt="A dashboard beside a map of recent earthquakes around the Pacific: the strongest magnitude in view, a bar chart of earthquakes per week and a list of the strongest events, all following the map view" width="100%">
</picture>
<br><sub>A dashboard puts indicators, charts and lists beside the map, and they follow what's in view.</sub>
</td>
</tr>
</table>

## How it fits together

```mermaid
flowchart LR
    subgraph IN ["Bring data in"]
      F["Files<br/>GeoPackage · Shapefile · GeoParquet<br/>GeoTIFF · COPC · 3D Tiles"]
      DB["Databases<br/>PostGIS tables · SQL Server"]
      SVC["Services<br/>ArcGIS · WFS · OGC API Features"]
      ST["Remote STAC assets"]
    end
    subgraph GL ["GeoLens"]
      CAT["Catalog<br/>search · metadata · provenance"]
      MB["Map builder<br/>styles · 3D · analysis · stories · dashboards · sharing"]
      STD["Open APIs<br/>OGC API · STAC · DCAT · tiles"]
    end
    subgraph OUT ["Use it anywhere"]
      WEB["Browsers and embeds"]
      GIS["QGIS · ArcGIS · CesiumJS"]
      CODE["curl · Python · TypeScript · DuckDB"]
      AG["AI agents via MCP"]
    end
    F & DB & SVC & ST --> CAT
    CAT --> MB --> WEB
    CAT --> STD --> GIS & CODE & AG
```

## One catalog for scattered data

- Upload Shapefile, GeoPackage, GeoJSON, GeoParquet, FlatGeobuf, KML/KMZ, zipped File
  Geodatabase, CSV, Excel or GeoTIFF (converted to Cloud-Optimized GeoTIFF). 3D Tiles and COPC
  point clouds are hosted for CesiumJS, QGIS and Potree.
- Serve tables already in GeoLens's PostGIS database in place, import WFS, ArcGIS and OGC API
  Features layers and SQL Server tables and refresh them on demand, or reference remote STAC
  assets without copying them.
- Draw new datasets in the browser.
- Find data with fuzzy search, or by meaning once an embedding provider is configured. Filter by
  type, place and time, group datasets into collections, edit metadata and restore a dataset's
  previous version after a replacement.

### Coming from ArcGIS Online

`geolens arcgis inventory` reads an ArcGIS Online organization or a self-hosted ArcGIS portal and
reports what would carry over to GeoLens. It changes nothing and needs no GeoLens instance. `geolens
arcgis migrate` then moves layers, files and web maps into GeoLens with their owners, folders and
sharing, and writes a loss report of what didn't carry over. The [CLI
guide](https://docs.getgeolens.com/guides/cli/#arcgis-migration) walks through it.

## Know where every dataset came from

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-provenance-dark.png">
    <img src=".github/assets/geolens-provenance.png" alt="The Source tab of the USGS Earthquakes dataset: imported from the USGS ArcGIS service into an owned copy, with last refreshed and last checked times, the feature count, and Healthy, Fresh and No drift badges" width="100%">
  </picture>
  <br>
  <sub>A dataset imported from the USGS earthquake service.</sub>
</p>

Each dataset records where it came from: an uploaded file, a database table, a service, a STAC
item or a drawing in the browser. Imported datasets also record when they were last refreshed, and
with an update cadence GeoLens marks them fresh, due or overdue. For services and
STAC sources, GeoLens also checks that the source still answers, and for services it flags upstream
schema changes before they reach your maps. If a service disappears, the imported copy keeps working.

## Build and share maps

- Point, symbol, heatmap, cluster, line, arrow, fill, 3D extrusion, raster and hillshade layers,
  with data-driven styles, labels, icons, patterns, filters and popups. Terrain comes from your own
  elevation models.
- Buffer, centroid, clip, dissolve, spatial join, select by location, measure and intersect. Most
  operations preview on the map, and each result is saved as a new dataset, from the builder or
  the CLI.
- Story maps walk readers through a map scene by scene, with Markdown text, images, buttons and
  separators. Dashboards put indicators, charts, filters and Markdown notes beside a map. A Map
  data panel shows the rows behind each layer, as a table or a list.
- Share a dataset, map or story with groups, with everyone signed in, or with the public. Public
  maps and published stories show their title and image when pasted into Slack, Teams or social
  posts, and maps embed in other sites with private tokens.
- The interface is in English, Spanish, French, German and Simplified Chinese.

## Use the data from anywhere

Vector datasets are OGC API Features collections, the catalog is OGC API Records and STAC, and
every layer has a tile URL. You can try this against the demo without an account (the second
command needs `jq`):

```sh
# Search the catalog (OGC API Records)
curl "https://demo.getgeolens.com/api/collections/datasets/items?q=volcanic%20eruptions"

# Read the top match with a CQL2 filter (OGC API Features): eruptions of VEI 6 or larger
ID=$(curl -s "https://demo.getgeolens.com/api/collections/datasets/items?q=volcanic%20eruptions&limit=1" | jq -r '.features[0].id')
curl -G "https://demo.getgeolens.com/api/collections/$ID/items" \
  --data-urlencode "filter=vei >= 6" -d limit=3
```

QGIS adds the same API as an OGC API Features connection, as the
[QGIS guide](https://docs.getgeolens.com/guides/api/qgis/) shows. The
[GeoLens plugin for QGIS](https://github.com/geolens-io/qgis-geolens-plugin) adds catalog search,
private datasets and edits that sync back to GeoLens.

<p align="center">
  <img src=".github/assets/geolens-qgis.png" alt="QGIS 4 with the GeoLens demo added as an OGC API Features connection: the Browser panel lists the demo's collections, and recent earthquakes, significant volcanic eruptions, plate boundaries and countries from the demo are loaded as layers on a world map" width="100%">
  <br>
  <sub>QGIS reading the demo over OGC API Features, without a plugin.</sub>
</p>

| Standard | Where | Use it with |
|---|---|---|
| OGC API Features, with CQL2 filtering and queryables | `/api/collections/{id}/items` | QGIS, ArcGIS, GDAL/OGR and other OGC API clients |
| OGC API Records | `/api/collections/datasets/items` | Catalog search from other portals and tools |
| STAC API 1.0 | `/api/stac/` | STAC clients such as pystac-client and STAC Browser |
| DCAT 3, DCAT-US 3.0 and GeoDCAT-AP as JSON-LD | `/api/datasets/dcat/`, `/api/datasets/dcat-us/3.0/`, `/api/datasets/geodcat-ap/` | Harvesting into national and EU open-data portals |
| Vector tiles and COG raster tiles | a tile URL on every layer | MapLibre, OpenLayers, Leaflet |
| 3D Tiles and COPC | each 3D dataset's page | CesiumJS, QGIS, Potree |

Data exports as GeoJSON, Shapefile, GeoPackage, CSV, FlatGeobuf, GeoParquet, PMTiles or
Cloud-Optimized GeoTIFF.

The `geolens` CLI publishes files and applies catalog manifests, Python and TypeScript SDKs cover
the API, and an MCP server lets AI agents search the catalog and, with a `map_author` API key,
create and style maps. The [API reference](https://docs.getgeolens.com/guides/api/) and
[SDK guides](https://docs.getgeolens.com/guides/sdk/) document them, and the
[examples gallery](https://geolens-io.github.io/geolens-examples/) has runnable code for
MapLibre, Leaflet, OpenLayers, the ArcGIS Maps SDK, QGIS and DuckDB.

## Optional AI

GeoLens can answer questions about a dataset, edit maps from plain-language requests, draft
metadata and search in natural language. It works with any OpenAI-compatible endpoint, including
a local server such as Ollama, and with Claude through Anthropic, Microsoft Foundry, Amazon Bedrock
or Google Vertex AI. AI stays off until an administrator configures a provider, and every workflow
works without it.

## Install

[Quick start](#quick-start) has the install command. The
[Install Guide](https://docs.getgeolens.com/guides/quickstart/install/) lists the versions, memory
and ports it expects. Each [release](https://github.com/geolens-io/geolens/releases) includes a
`SHA256SUMS` file for checking `install.sh` before you run it. To build from source instead, clone
the repository and run `bash scripts/install.sh`; the first build takes 5-10 minutes.

For production, read the
[cloud deployment guide](https://docs.getgeolens.com/guides/quickstart/cloud-deployment/), which
also lists what an external database needs. Docker Compose is the supported path, and
[geolens-deployments](https://github.com/geolens-io/geolens-deployments) has a community-maintained
Helm chart and Terraform recipes for AWS ECS Fargate and Azure Container Apps.

The bundled database is backed up daily, and the
[backup guide](https://docs.getgeolens.com/guides/admin/backups/) covers off-site copies and
restores. [UPGRADING.md](UPGRADING.md) covers upgrades and rollback, [RUNBOOK.md](RUNBOOK.md)
covers operations, and the
[Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) lists every
setting.

## Your first dataset

With the [CLI](https://docs.getgeolens.com/guides/cli/) installed, publish the sample file from the
install directory:

```sh
geolens login http://localhost:8080/api               # your admin username and password
geolens publish examples/manifests/first-catalog/city-parks.geojson --name "City Parks"
```

`geolens publish` prints the new dataset's URL. To manage a whole catalog, describe the sources in
a `geolens.yaml` manifest and run `geolens apply`; [`examples/manifests/`](examples/manifests/) has
templates.

To load the demo's maps and datasets, export `GEOLENS_ADMIN_PASSWORD` from `.env` and run
`python scripts/seed-showcase.py --username admin`. The script needs Python 3.10+ and `httpx` and
downloads public data from about a dozen sources; [scripts/README.md](scripts/README.md) has the
sizes and options.

## Privacy and access

- GeoLens sends no telemetry. Apart from the default basemap tiles and the remote services or
  STAC sources your users register, it makes outbound calls only for features an administrator
  turns on. [EGRESS.md](EGRESS.md) lists them and explains how to run air-gapped.
- Your data stays readable without GeoLens. Vector datasets are ordinary PostGIS tables in a
  `data` schema, rasters are Cloud-Optimized GeoTIFFs in your own storage (local disk, S3/MinIO or
  Azure Blob), and the catalog exports through OGC API, STAC and DCAT.
- Sign-in uses local accounts or OAuth 2.0/OIDC (Google, Microsoft, GitHub or a generic provider),
  with roles, groups, per-dataset permissions, per-user API keys and an audit log. Self-registration is
  off by default.
- Features released in this repository stay free.
  [EDITIONS.md](EDITIONS.md) describes the optional paid support and add-ons.

## Known limitations

- The supported install, Docker Compose, runs on one host. For high availability, run several
  replicas of the API, worker, frontend and Titiler against a managed PostgreSQL with automatic
  failover, shared object storage and one Valkey or Redis cache. With Azure Blob or local storage,
  API and worker replicas also need a shared staging volume, since only S3 keeps uploads in the
  bucket. Local storage keeps every file on that volume, so Titiler replicas mount it too.
  [geolens-deployments](https://github.com/geolens-io/geolens-deployments) has a
  community-maintained Helm chart, Terraform recipes for AWS and Azure, and guides for AWS, Azure,
  Google Cloud and DigitalOcean. GeoLens itself doesn't cluster the database or read from replicas.
- One organization per deployment.
- Terrain rendering assumes elevation in meters; other vertical units render exaggerated.
- GeoLens's own REST API can change between minor releases (the standards endpoints follow their
  specifications). The [CHANGELOG](CHANGELOG.md) lists contract changes. When a change breaks
  callers, the old form keeps working for the later of the next minor release and 90 days, and
  the CHANGELOG records its removal date. That covers REST routes and fields, the map and
  dashboard JSON clients write, and CLI commands and flags; the SDKs follow the API, and MCP
  tool names and arguments aren't covered.

## Contributing

Bug reports, fixes, translations and docs are welcome. [CONTRIBUTING](.github/CONTRIBUTING.md)
covers setup and tests, and [ARCHITECTURE](.github/ARCHITECTURE.md) maps the code.
The [QGIS plugin](https://github.com/geolens-io/qgis-geolens-plugin),
[examples](https://github.com/geolens-io/geolens-examples) and
[deployments](https://github.com/geolens-io/geolens-deployments) repositories take issues and pull
requests too. Ask questions in
[GitHub Discussions](https://github.com/geolens-io/geolens/discussions), report bugs in
[Issues](https://github.com/geolens-io/geolens/issues), and report security problems privately as
described in [SECURITY.md](.github/SECURITY.md). The [roadmap](https://docs.getgeolens.com/roadmap/)
shows what's planned.

## Built on

GeoLens is built on these open source projects. Thanks to everyone who maintains them.

- [PostgreSQL](https://www.postgresql.org/) and [PostGIS](https://postgis.net/) hold the catalog and every vector dataset, and
  [pgvector](https://github.com/pgvector/pgvector) stores the embeddings behind search by meaning.
- [GDAL](https://gdal.org/) reads the files and services GeoLens imports and writes the formats it exports,
  and [PROJ](https://proj.org/) handles coordinate transformations.
- [TiTiler](https://developmentseed.org/titiler/) serves raster tiles from Cloud Optimized GeoTIFFs.
- [FastAPI](https://fastapi.tiangolo.com/) serves the API, and [Procrastinate](https://procrastinate.readthedocs.io/) runs background
  jobs with PostgreSQL as the queue.
- [MapLibre GL JS](https://maplibre.org/) draws the maps, [deck.gl](https://deck.gl/) and
  [loaders.gl](https://loaders.gl/) render 3D Tiles and point clouds, and [Terra Draw](https://terradraw.io/)
  handles drawing and editing.
- The web app is written in [React](https://react.dev/).

These names belong to their owners, and listing them doesn't mean they endorse GeoLens; see
[TRADEMARKS.md](TRADEMARKS.md#other-projects-names).

## License

GeoLens is licensed under the [Apache License 2.0](LICENSE). The GeoLens name, logo and brand
assets are not covered by this license; see [TRADEMARKS.md](TRADEMARKS.md). Sample-data
attribution is in [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md). The web app serves the license notices for the
code it bundles at `/third-party-licenses.txt`, and the backend image's copyleft notices are in
[backend/licenses](backend/licenses/).

Project policies: [editions](EDITIONS.md) · [support](SUPPORT.md) · [governance](GOVERNANCE.md) · [maintainers](MAINTAINERS.md) · [security](.github/SECURITY.md) · [release process](RELEASE.md) · [egress &amp; air-gap](EGRESS.md)
