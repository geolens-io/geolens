# GeoLens

[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

**Die raumbezogenen Daten Ihres Teams, an einem Ort durchsuchbar.**

Laden Sie Shapefiles, GeoTIFFs, GeoPackages oder CSVs hoch. GeoLens speichert alles in PostGIS, indexiert Metadaten mit pgvector + pg_trgm fuer semantische und unscharfe Suche und stellt OGC APIs bereit, die QGIS, ArcGIS und MapLibre Clients direkt nutzen koennen. Gebaut mit FastAPI und React, bereitgestellt mit einem einzigen Befehl.

> Diese Uebersetzung folgt dem englischen README als kanonischer Quelle. Wenn eine Uebersetzung ungenau ist, oeffnen Sie bitte eine Issue oder Pull Request.

[![CI](https://github.com/geolens-io/geolens/actions/workflows/ci.yml/badge.svg)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)]()
[![PostgreSQL 17 + PostGIS 3.5](https://img.shields.io/badge/PostGIS_3.5-PostgreSQL_17-336791.svg)](https://postgis.net/)
[![OGC Compliant](https://img.shields.io/badge/OGC_API-Features_%7C_Records-green.svg)](https://ogcapi.ogc.org/)

```bash
git clone https://github.com/geolens-io/geolens.git && cd geolens
cp .env.example .env && docker compose up -d
# Oeffnen Sie http://localhost:8080 - Login: admin / admin
```

<p align="center">
  <img src=".github/assets/geolens-map-builder.png" alt="GeoLens Map Builder erstellt interaktive Karten mit mehreren Layern" width="900" />
  <br />
  <em>Laden Sie ein Shapefile hoch und erhalten Sie in Minuten einen durchsuchbaren, voranschaubaren und exportierbaren Datensatz</em>
</p>

## Dokumentation

Die Benutzer-, Admin- und API-Dokumentation finden Sie unter **[docs.getgeolens.com](https://docs.getgeolens.com)**.

- **Installation und Quickstart:** [docs.getgeolens.com/guides/quickstart](https://docs.getgeolens.com/guides/quickstart/)
- **Admin-Handbuch:** [docs.getgeolens.com/guides/admin](https://docs.getgeolens.com/guides/admin/)
- **API-Referenz:** [docs.getgeolens.com/guides/api](https://docs.getgeolens.com/guides/api/)

## Thematische Demo ausprobieren

GeoLens enthaelt drei thematische Demo-Sammlungen: **Planet Earth** (Raster + VRT-Mosaike), **Global Development & People** (Indikator-Choroplethen) und **Borders, Boundaries & Contested Space** (sorgfaeltig behandelte Geopolitik). Neun Beispielkarten werden deterministisch mit einem Befehl geladen:

```bash
cp .env.demo .env
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

<p align="center">
  <img src=".github/assets/geolens-demo-tour.gif" alt="GeoLens Demo-Tour mit Map Builder, Katalogsuche und Datensatzdetails" width="900" />
</p>

Wenn der Seeder-Image-Build abgeschlossen ist, oeffnen Sie http://localhost:8080 und wechseln Sie zu **Maps**. Der Download von GEBCO 2024 ist meist der langsamste Teil, etwa 10 bis 15 Minuten bei einer schnellen Verbindung, und wird danach im Cache wiederverwendet. Die Beispielgeschichten umfassen:

- **Earth as Seen from Space**: Bathymetrie + Topografie + Eis in einer dunklen Weltansicht
- **Global Bathymetry**: GEBCO 2024 Meeresboden mit Viridis-Colormap
- **GDP per Capita PPP 2023**: Laender-Choropleth aus World Bank Open Data
- **Manhattan Skyline**: OpenStreetMap-Gebaeudegrundrisse hoehenextrudiert fuer 3D-Fill-Extrusion-Rendering
- **Population at a Glance**: bevoelkerte Orte als proportionale Symbole, nach Einwohnerzahl skaliert
- **The World's Disputed Places**: alle umstrittenen Gebiete, die Natural Earth fuehrt
- **One Territory, Multiple Official Maps**: Kashmir aus Sicht von China, Indien und Pakistan (Layer ein-/ausschalten)
- **Conflict Events 2024**: UCDP Georeferenced Event Dataset, toedliche Ereignisse organisierter Gewalt
- **Refugees by Country of Origin 2023**: UNHCR-Statistiken mit Laenderpolygonen verknuepft

Alle Daten werden beim Image-Build gebuendelt: **keine ausgehenden Netzwerkaufrufe zur Laufzeit**. Die Demo kann alle 24 Stunden ueber den `reset` Service zurueckgesetzt werden. Einen vollstaendigen Reset erzwingen Sie so:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml exec reset /scripts/reset-demo.sh
docker compose -f docker-compose.yml -f docker-compose.demo.yml restart seeder
```

Quellenangaben und Lizenzen fuer jeden Demo-Datensatz sind auf der jeweiligen Detailseite dokumentiert. Alle gebuendelten Daten sind CC-BY 4.0, ODbL 1.0 oder Public Domain.

## Veroeffentlichte Artefakte

GeoLens wird ueber die Standard-Paketregister veroeffentlicht:

```bash
pip install geolens          # Python SDK
pip install geolens-cli      # CLI; installiert den Befehl `geolens`
npm install @geolens/sdk     # TypeScript/JavaScript SDK
```

Oeffentliche API- und Frontend-Images in GitHub Container Registry:

```bash
docker pull ghcr.io/geolens-io/geolens-api:latest
docker pull ghcr.io/geolens-io/geolens-frontend:latest
```

Die Tags `1.0`, `1` und `latest` folgen der aktuellen 1.x Release-Linie.

## Warum GeoLens?

Raumbezogene Daten landen oft verstreut: Shapefiles auf Netzlaufwerken, Tabellen in Datenbankschemas, Raster in Buckets und Metadaten in Tabellenkalkulationen. Den richtigen Datensatz zu finden bedeutet haeufig, in Slack zu fragen oder Dateiserver zu durchsuchen. Teilen heisst exportieren, per E-Mail versenden und hoffen, dass das CRS passt.

GeoLens ersetzt diesen Ablauf:

- **Ein Katalog**: Shapefiles, GeoPackages, GeoTIFFs oder CSVs hochladen und in Minuten durchsuchbar, voranschaubar und exportierbar machen.
- **Kompatibel mit Ihren Werkzeugen**: OGC API Features/Records mit CQL2-Filterung, STAC 1.0 und direkte Tile-URLs fuer QGIS, ArcGIS und MapLibre.
- **Semantische + raeumliche Suche**: Datensaetze nach Bedeutung finden, nicht nur nach Schlagworten, mit pgvector und pg_trgm.
- **Integrierter Map Builder**: Mehrschichtige Karten zusammenstellen, stylen und per oeffentlichem Link oder eingebettetem iframe teilen.
- **Optionale KI**: Mit Karten chatten, Beschreibungen generieren und natuerliche Sprache fuer Suche nutzen. Verwenden Sie jede OpenAI-kompatible API oder lassen Sie KI deaktiviert.

## In Aktion

Suchen Sie Datensaetze nach Bedeutung, nicht nur nach Schlagworten:

```bash
# Semantische Suche: findet "hydrology"-Datensaetze auch bei der Suche nach "rivers"
curl 'http://localhost:8080/api/search/datasets/?q=rivers+near+mountains&limit=3' \
  -H 'Authorization: Bearer <token>' | jq '.features[].properties.title'
```

Jeder Datensatz ist auch ein standardmaessiger OGC API Features Endpoint:

```bash
# GeoJSON-Features mit bbox-Filter: funktioniert in QGIS, ArcGIS und jedem OGC-Client
curl 'http://localhost:8080/api/collections/ne_10m_admin_0_countries/items?bbox=-10,35,30,60&limit=5'
```

Aus QGIS verbinden Sie sich ueber **Layer > Add WFS / OGC API Features** und verwenden `http://localhost:8080/api/`.

## Funktionen

### Map Builder und Teilen

- Interaktive Karten mit mehreren Layern, Drag-and-drop-Reihenfolge, Styling und Layer-Filtern.
- Punkt-, Linien- und Polygonstile mit Farbskalen und Kategorieklassen.
- Oeffentliche Links und einbettbare `<iframe>` Snippets.
- Raster-COG- und Vektor-Layer nebeneinander.

### KI-gestuetzt (optional)

- Mit Karten chatten: Fragen in natuerlicher Sprache stellen; die KI fuegt Layer hinzu und stylt sie.
- Semantische Vektorsuche ueber Metadaten mit pgvector und HNSW-Indexierung.
- Automatisch generierte Datensatzbeschreibungen und Tags beim Import.
- Funktioniert mit jeder OpenAI-kompatiblen API (OpenAI, Anthropic, Ollama); GeoLens ist auch ohne sie voll funktionsfaehig.

### Suche und Discovery

- Volltext- und Trigramm-Suche ueber Namen, Beschreibungen und Metadaten.
- Raeumliche Suche mit Bounding Boxes und auf der Karte gezeichneten Filtern.
- Facettierte Filter nach Format, Tags, Sammlungen und Record-Typ.
- Optionale semantische Suche mit pgvector.
- Gespeicherte Suchen fuer wiederkehrende Ablaeufe.

### Datenimport und Export

- **Vektor:** Shapefile, GeoPackage, GeoJSON, CSV und XLSX.
- **Raster:** GeoTIFF und Cloud-Optimized GeoTIFF mit automatischer Konvertierung.
- **Mosaike:** VRT-basierte Rastermosaike.
- **Export:** GeoJSON, Shapefile, GeoPackage und CSV mit CRS-Reprojektion.
- Provenienzverfolgung und Metadatenbearbeitung.

### Standards und Interoperabilitaet

- Kompatibel mit OGC API - Features und OGC API - Records.
- STAC 1.0 Katalog-Endpoint.
- Direkte Tile-URLs fuer QGIS, ArcGIS, MapLibre und OGC Clients.
- API-Key-Authentifizierung fuer externe Werkzeuge.
- JWT + OAuth 2.0/OIDC und RBAC mit Berechtigungen pro Datensatz.

<details>
<summary>Enterprise und Sicherheit</summary>

- JWT-Authentifizierung mit Refresh Tokens.
- API-Key-Verwaltung pro Benutzer.
- OAuth 2.0 / OIDC-Unterstuetzung (Google, Microsoft und generische Anbieter).
- Rollenbasierte Zugriffskontrolle (RBAC) mit Berechtigungen pro Datensatz.
- Audit Logging fuer alle administrativen Aktionen.
- Internationalisierung: Englisch, Spanisch, Franzoesisch, Deutsch.

</details>

## Screenshots

<p align="center">
  <img src=".github/assets/geolens-catalog.png" alt="GeoLens Katalogansicht" width="900" />
  <br />
  <em>Katalogansicht mit Suche, raeumlichen Filtern und Datensatzkarten</em>
</p>

<p align="center">
  <img src=".github/assets/geolens-dataset.png" alt="GeoLens Datensatzdetail" width="900" />
  <br />
  <em>Datensatzdetail mit Kartenvorschau, Metadaten und Attributtabelle</em>
</p>

## Schnellstart

**Voraussetzungen:** Docker Engine 24+ und Docker Compose v2. Minimale Host-Empfehlung: 4 GB RAM und 10 GB freier Speicher fuer den Basis-Stack und einen kleinen Datensatz; 8 GB+ RAM fuer Rasterarbeit oder Kataloge mit mehr als 100 Datensaetzen. Siehe [Resource Sizing](https://docs.getgeolens.com/guides/quickstart/resource-sizing/) fuer Produktionsdimensionierung.

```bash
git clone https://github.com/geolens-io/geolens.git
cd geolens
cp .env.example .env
docker compose up -d
```

Warten Sie etwa 60 Sekunden, oeffnen Sie [http://localhost:8080](http://localhost:8080), und melden Sie sich mit `admin` / `admin` an.

Pruefen Sie, dass alle Services fehlerfrei laufen:

```bash
docker compose ps
```

Zur Produktionsbereitstellung siehe den [Install Guide](https://docs.getgeolens.com/guides/quickstart/install/). Fuer Upgrades siehe den [Upgrade Guide](https://docs.getgeolens.com/guides/quickstart/upgrade/).

### Demo Mode

Starten Sie eine vorbefuellte Demo-Instanz mit Natural Earth Beispieldaten:

```bash
cp .env.demo .env
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d
```

Das Demo-Overlay seedet automatisch 20 repraesentative Datensaetze, setzt sie auf oeffentliche Sichtbarkeit und setzt Daten alle 24 Stunden zurueck. Siehe `.env.demo` fuer die Konfiguration.

### Seed Data

Befuellen Sie den Katalog mit [Natural Earth](https://www.naturalearthdata.com/) 1:10m Datensaetzen:

```bash
pip install httpx  # einmalige Abhaengigkeit auf dem Host
python scripts/seed-natural-earth.py --username admin --password admin
```

Das Skript meldet sich an, erstellt einen temporaeren API-Key fuer den Lauf, ingestiert die Datensaetze und loescht den Key beim Beenden. Es laedt vom [NACIS CDN](https://naciscdn.org/naturalearth/) herunter, ueberspringt Duplikate bei erneuter Ausfuehrung und erstellt zwei Sammlungen (Cultural 10m, Physical 10m). Nutzen Sie `--dry-run` zur Vorschau oder `--theme cultural` zum Filtern nach Thema.

Wenn Sie bereits einen API-Key haben (Admin > API Keys > Create New, oder via `POST /api/auth/api-keys/`), uebergeben Sie `--api-key <plaintext>` anstelle von `--username/--password`.

## Architektur

| Komponente | Technologie |
|------------|-------------|
| Frontend | React 19, Vite, MapLibre GL v5, TanStack Query, Tailwind CSS |
| Backend API | FastAPI (Python), GDAL/ogr2ogr, Procrastinate (Task Queue) |
| Raster Tiles | Titiler (COG Tile Server) |
| Object Storage | MinIO (S3-kompatibel, lokale Entwicklung) oder jeder S3-Anbieter |
| Cache | Valkey (Tile- und Query-Cache) |
| Datenbank | PostgreSQL 17 + PostGIS 3.5 + pgvector + pg_trgm |
| Reverse Proxy | Nginx (Produktion) / Vite Dev Proxy (Entwicklung) |

## Konfiguration

Die gesamte Konfiguration wird ueber Umgebungsvariablen in `.env` verwaltet. Siehe die [Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) fuer die vollstaendige Optionsliste mit Standardwerten und Beschreibungen.

## Referenz

| Guide | Beschreibung |
|------|--------------|
| [Install Guide](https://docs.getgeolens.com/guides/quickstart/install/) | Schrittweise Bereitstellung mit Docker Compose |
| [Upgrade Guide](https://docs.getgeolens.com/guides/quickstart/upgrade/) | Upgrades zwischen Versionen mit Rollback |
| [Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) | Umgebungsvariablen und Standardwerte |
| [Admin Guide](https://docs.getgeolens.com/guides/admin/) | Benutzerverwaltung, Datensaetze und Systemzustand |
| [Cloud Deployment](https://docs.getgeolens.com/guides/quickstart/cloud-deployment/) | AWS-, GCP- und DigitalOcean-Bereitstellungsanleitungen |
| [Developer Docs](https://docs.getgeolens.com/) | Eigene Map-Builder-Widgets bauen |
| [API Reference](#in-aktion) | Interaktive Swagger UI unter `/api/docs` |

## Community

- [GitHub Discussions](https://github.com/geolens-io/geolens/discussions): Fragen, Ideen, Show and Tell.
- [Beitragsleitfaden](.github/CONTRIBUTING.md): Entwicklungsumgebung, Codestil und Pull Requests.

## Lizenz

GeoLens ist unter der [Apache License 2.0](LICENSE) lizenziert.
