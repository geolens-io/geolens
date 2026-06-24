# GeoLens

[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

**Die raumbezogenen Daten Ihres Teams, an einem Ort durchsuchbar.**

Laden Sie Shapefiles, GeoTIFFs, GeoPackages oder CSVs hoch. GeoLens speichert alles in PostGIS, indexiert Metadaten mit pgvector + pg_trgm für semantische und unscharfe Suche und stellt OGC APIs bereit, die QGIS, ArcGIS und MapLibre Clients direkt nutzen können. Gebaut mit FastAPI und React, bereitgestellt mit einem einzigen Befehl.

> Dies ist eine gekürzte Übersetzung. Das englische [README](README.md) ist die kanonische Quelle; die vollständige, stets aktuelle deutschsprachige Dokumentation finden Sie unter **[docs.getgeolens.com/de](https://docs.getgeolens.com/de)**.

[![CI](https://github.com/geolens-io/geolens/actions/workflows/ci.yml/badge.svg)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: backend 3.13 / SDK 3.10+](https://img.shields.io/badge/python-3.13_backend_%7C_3.10%2B_SDK-blue.svg)]()
[![PostgreSQL 17 + PostGIS 3.5](https://img.shields.io/badge/PostGIS_3.5-PostgreSQL_17-336791.svg)](https://postgis.net/)
[![OGC API](https://img.shields.io/badge/OGC_API-Features_%7C_Records-green.svg)](https://ogcapi.ogc.org/)

```bash
curl -fsSL https://getgeolens.com/install.sh | sh
# Öffnen Sie http://localhost:8080 — Login mit den von Ihnen gewählten Anmeldedaten
```

<p align="center">
  <img src=".github/assets/geolens-manhattan-3d-hero.jpg" alt="GeoLens Map Builder: Gebäudegrundrisse von Manhattan zu einer 3D-Skyline extrudiert, nach Dachhöhe eingefärbt, mit geöffnetem Layer-Stil-Editor neben der Karte" width="900" />
  <br />
  <em>Der Map Builder — Manhattans Gebäudegrundrisse, extrudiert nach Dachhöhe und durch einen datengesteuerten Stil eingefärbt, erstellt aus offenen Daten mit <code>scripts/seed-showcase.py</code></em>
</p>

## Dokumentation

Vollständige Benutzer-, Admin- und API-Dokumentation:

- **Auf Deutsch:** [docs.getgeolens.com/de](https://docs.getgeolens.com/de)
- **Installation und Quickstart:** [docs.getgeolens.com/guides/quickstart](https://docs.getgeolens.com/guides/quickstart/)
- **Admin-Handbuch:** [docs.getgeolens.com/guides/admin](https://docs.getgeolens.com/guides/admin/)
- **API-Referenz:** [docs.getgeolens.com/guides/api](https://docs.getgeolens.com/guides/api/)

## Veröffentlichte Artefakte

```bash
pip install geolens          # Python SDK
pip install geolens-cli      # CLI; installiert den Befehl `geolens`
npm install @geolens/sdk     # TypeScript/JavaScript SDK
```

Öffentliche API- und Frontend-Images in der GitHub Container Registry:

```bash
docker pull ghcr.io/geolens-io/geolens-api:latest
docker pull ghcr.io/geolens-io/geolens-frontend:latest
```

## Mehr erfahren

Dieses README ist eine Kurzfassung. Den vollständigen Funktionsüberblick, die Konfiguration, die Architektur und den Beitragsleitfaden finden Sie im **[englischen README](README.md)** und in der **[vollständigen Dokumentation](https://docs.getgeolens.com/de)**.

## Lizenz

Apache-2.0 — siehe [LICENSE](LICENSE) und [NOTICE](NOTICE).
