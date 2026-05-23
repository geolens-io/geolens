# GeoLens

[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

**Die raumbezogenen Daten Ihres Teams, an einem Ort durchsuchbar.**

Laden Sie Shapefiles, GeoTIFFs, GeoPackages oder CSVs hoch. GeoLens speichert alles in PostGIS, indexiert Metadaten mit pgvector + pg_trgm für semantische und unscharfe Suche und stellt OGC APIs bereit, die QGIS, ArcGIS und MapLibre Clients direkt nutzen können. Gebaut mit FastAPI und React, bereitgestellt mit einem einzigen Befehl.

> Diese Übersetzung folgt dem englischen README als kanonischer Quelle. Wenn eine Übersetzung ungenau ist, öffnen Sie bitte eine Issue oder Pull Request.

[![CI](https://github.com/geolens-io/geolens/actions/workflows/ci.yml/badge.svg)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: backend 3.13 / SDK 3.10+](https://img.shields.io/badge/python-3.13_backend_%7C_3.10%2B_SDK-blue.svg)]()
[![PostgreSQL 17 + PostGIS 3.5](https://img.shields.io/badge/PostGIS_3.5-PostgreSQL_17-336791.svg)](https://postgis.net/)
[![OGC Compliant](https://img.shields.io/badge/OGC_API-Features_%7C_Records-green.svg)](https://ogcapi.ogc.org/)

```bash
git clone https://github.com/geolens-io/geolens.git && cd geolens
bash scripts/install.sh
# Öffnen Sie http://localhost:8080 — Login mit den von Ihnen gewählten Anmeldedaten
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

## Veröffentlichte Artefakte

GeoLens wird über die Standard-Paketregister veröffentlicht:

```bash
pip install geolens          # Python SDK
pip install geolens-cli      # CLI; installiert den Befehl `geolens`
npm install @geolens/sdk     # TypeScript/JavaScript SDK
```

Öffentliche API- und Frontend-Images in GitHub Container Registry:

```bash
docker pull ghcr.io/geolens-io/geolens-api:latest
docker pull ghcr.io/geolens-io/geolens-frontend:latest
```

Die Tags `1.0`, `1` und `latest` folgen der aktuellen 1.x Release-Linie.

## Warum GeoLens?

Raumbezogene Daten landen oft verstreut: Shapefiles auf Netzlaufwerken, Tabellen in Datenbankschemas, Raster in Buckets und Metadaten in Tabellenkalkulationen. Den richtigen Datensatz zu finden bedeutet häufig, in Slack zu fragen oder Dateiserver zu durchsuchen. Teilen heißt exportieren, per E-Mail versenden und hoffen, dass das CRS passt.

GeoLens ersetzt diesen Ablauf:

- **Ein Katalog**: Shapefiles, GeoPackages, GeoTIFFs oder CSVs hochladen und in Minuten durchsuchbar, voranschaubar und exportierbar machen.
- **Kompatibel mit Ihren Werkzeugen**: OGC API Features/Records mit CQL2-Filterung, STAC 1.0 und direkte Tile-URLs für QGIS, ArcGIS und MapLibre.
- **Semantische + räumliche Suche**: Datensätze nach Bedeutung finden, nicht nur nach Schlagworten, mit pgvector und pg_trgm.
- **Integrierter Map Builder**: Mehrschichtige Karten zusammenstellen, stylen und per öffentlichem Link oder eingebettetem iframe teilen.
- **Optionale KI**: Mit Karten chatten, Beschreibungen generieren und natürliche Sprache für Suche nutzen. Verwenden Sie jede OpenAI-kompatible API oder lassen Sie KI deaktiviert.

## In Aktion

Suchen Sie Datensätze nach Bedeutung, nicht nur nach Schlagworten:

```bash
# Semantische Suche: findet "hydrology"-Datensätze auch bei der Suche nach "rivers"
curl 'http://localhost:8080/api/search/datasets/?q=rivers+near+mountains&limit=3' \
  -H 'Authorization: Bearer <token>' | jq '.features[].properties.title'
```

Jeder Datensatz ist auch ein standardmäßiger OGC API Features Endpoint:

```bash
# GeoJSON-Features mit bbox-Filter: funktioniert in QGIS, ArcGIS und jedem OGC-Client
curl 'http://localhost:8080/api/collections/ne_10m_admin_0_countries/items?bbox=-10,35,30,60&limit=5'
```

Aus QGIS verbinden Sie sich über **Layer > Add WFS / OGC API Features** und verwenden `http://localhost:8080/api/`.

## Funktionen

### Map Builder und Teilen

- Interaktive Karten mit mehreren Layern, Drag-and-drop-Reihenfolge, Styling und Layer-Filtern.
- Punkt-, Linien- und Polygonstile mit Farbskalen und Kategorieklassen.
- Öffentliche Links und einbettbare `<iframe>` Snippets.
- Raster-COG- und Vektor-Layer nebeneinander.

### KI-gestützt (optional)

- Mit Karten chatten: Fragen in natürlicher Sprache stellen; die KI fügt Layer hinzu und stylt sie.
- Semantische Vektorsuche über Metadaten mit pgvector und HNSW-Indexierung.
- Automatisch generierte Datensatzbeschreibungen und Tags beim Import.
- Funktioniert mit jeder OpenAI-kompatiblen API (OpenAI, Anthropic, Ollama); GeoLens ist auch ohne sie voll funktionsfähig.

### Suche und Discovery

- Volltext- und Trigramm-Suche über Namen, Beschreibungen und Metadaten.
- Räumliche Suche mit Bounding Boxes und auf der Karte gezeichneten Filtern.
- Facettierte Filter nach Format, Tags, Sammlungen und Record-Typ.
- Optionale semantische Suche mit pgvector.
- Gespeicherte Suchen für wiederkehrende Abläufe.

### Datenimport und Export

- **Vektor:** Shapefile, GeoPackage, GeoJSON, CSV und XLSX.
- **Raster:** GeoTIFF und Cloud-Optimized GeoTIFF mit automatischer Konvertierung.
- **Mosaike:** VRT-basierte Rastermosaike.
- **Export:** GeoJSON, Shapefile, GeoPackage und CSV mit CRS-Reprojektion.
- Provenienzverfolgung und Metadatenbearbeitung.

### Standards und Interoperabilität

- Kompatibel mit OGC API - Features und OGC API - Records.
- STAC 1.0 Katalog-Endpoint.
- Direkte Tile-URLs für QGIS, ArcGIS, MapLibre und OGC Clients.
- API-Key-Authentifizierung für externe Werkzeuge.
- JWT + OAuth 2.0/OIDC und RBAC mit Berechtigungen pro Datensatz.

<details>
<summary>Enterprise und Sicherheit</summary>

- JWT-Authentifizierung mit Refresh Tokens.
- API-Key-Verwaltung pro Benutzer.
- OAuth 2.0 / OIDC-Unterstützung (Google, Microsoft und generische Anbieter).
- Rollenbasierte Zugriffskontrolle (RBAC) mit Berechtigungen pro Datensatz.
- Audit Logging für alle administrativen Aktionen.
- Internationalisierung: Englisch, Spanisch, Französisch, Deutsch.

</details>

## Screenshots

<p align="center">
  <img src=".github/assets/geolens-catalog.png" alt="GeoLens Katalogansicht" width="900" />
  <br />
  <em>Katalogansicht mit Suche, räumlichen Filtern und Datensatzkarten</em>
</p>

<p align="center">
  <img src=".github/assets/geolens-dataset.png" alt="GeoLens Datensatzdetail" width="900" />
  <br />
  <em>Datensatzdetail mit Kartenvorschau, Metadaten und Attributtabelle</em>
</p>

## Schnellstart

**Voraussetzungen:** Docker Engine 24+ und Docker Compose v2. Minimale Host-Empfehlung: 4 GB RAM und 10 GB freier Speicher für den Basis-Stack und einen kleinen Datensatz; 8 GB+ RAM für Rasterarbeit oder Kataloge mit mehr als 100 Datensätzen. Siehe [Resource Sizing](https://docs.getgeolens.com/guides/quickstart/resource-sizing/) für Produktionsdimensionierung.

```bash
git clone https://github.com/geolens-io/geolens.git
cd geolens
bash scripts/install.sh
```

`scripts/install.sh` kopiert `.env.example` nach `.env`, generiert ein
JWT-Signing-Secret, fragt nach Admin-Anmeldedaten (Standard: `admin` / `admin`)
und führt `docker compose up -d` aus. Für unbeaufsichtigte Installationen können
Sie `GEOLENS_ADMIN_USERNAME` und `GEOLENS_ADMIN_PASSWORD` als Umgebungsvariablen
setzen, dann werden die Eingabeaufforderungen übersprungen. Erneutes Ausführen
des Skripts ist idempotent — vorhandene Werte in `.env` bleiben erhalten.

Warten Sie etwa 60 Sekunden, öffnen Sie [http://localhost:8080](http://localhost:8080), und melden Sie sich mit den gewählten Admin-Anmeldedaten an.

Prüfen Sie, dass alle Services fehlerfrei laufen:

```bash
docker compose ps
```

Zur Produktionsbereitstellung siehe den [Install Guide](https://docs.getgeolens.com/guides/quickstart/install/). Für Upgrades siehe den [Upgrade Guide](https://docs.getgeolens.com/guides/quickstart/upgrade/).

### Seed Data

Befüllen Sie den Katalog mit [Natural Earth](https://www.naturalearthdata.com/) 1:10m Datensätzen:

```bash
pip install httpx  # einmalige Abhängigkeit auf dem Host
python scripts/seed-natural-earth.py --username admin --password admin
```

Das Skript meldet sich an, erstellt einen temporären API-Key für den Lauf, ingestiert die Datensätze und löscht den Key beim Beenden. Es lädt vom [NACIS CDN](https://naciscdn.org/naturalearth/) herunter, überspringt Duplikate bei erneuter Ausführung und erstellt zwei Sammlungen (Cultural 10m, Physical 10m). Nutzen Sie `--dry-run` zur Vorschau oder `--theme cultural` zum Filtern nach Thema.

Wenn Sie bereits einen API-Key haben (Admin > API Keys > Create New, oder via `POST /api/auth/api-keys/`), übergeben Sie `--api-key <plaintext>` anstelle von `--username/--password`.

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

Die gesamte Konfiguration wird über Umgebungsvariablen in `.env` verwaltet. Siehe die [Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) für die vollständige Optionsliste mit Standardwerten und Beschreibungen.

## Referenz

| Guide | Beschreibung |
|------|--------------|
| [Install Guide](https://docs.getgeolens.com/guides/quickstart/install/) | Schrittweise Bereitstellung mit Docker Compose |
| [Upgrade Guide](https://docs.getgeolens.com/guides/quickstart/upgrade/) | Upgrades zwischen Versionen mit Rollback |
| [Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) | Umgebungsvariablen und Standardwerte |
| [Admin Guide](https://docs.getgeolens.com/guides/admin/) | Benutzerverwaltung, Datensätze und Systemzustand |
| [Cloud Deployment](https://docs.getgeolens.com/guides/quickstart/cloud-deployment/) | AWS-, GCP- und DigitalOcean-Bereitstellungsanleitungen |
| [Developer Docs](https://docs.getgeolens.com/) | Eigene Map-Builder-Widgets bauen |
| [API Reference](https://docs.getgeolens.com/guides/api/) | Auto-generierte Referenz auf docs.getgeolens.com; interaktive Swagger UI unter `/api/docs` |
| [Manifest-Beispiele](examples/manifests/) | Funktionierende `geolens.yaml`-Beispiele — first-catalog, public-cog (entferntes COG), s3-source, url-source |

## Community

- [GitHub Discussions](https://github.com/geolens-io/geolens/discussions): Fragen, Ideen, Show and Tell.
- [Beitragsleitfaden](.github/CONTRIBUTING.md): Entwicklungsumgebung, Codestil und Pull Requests.

## Lizenz

GeoLens ist unter der [Apache License 2.0](LICENSE) lizenziert.
