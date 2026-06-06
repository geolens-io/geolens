# GeoLens

[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

**Los datos espaciales de tu equipo, buscables en un solo lugar.**

Sube Shapefiles, GeoTIFFs, GeoPackages o CSVs. GeoLens guarda todo en PostGIS, indexa los metadatos con pgvector + pg_trgm para búsqueda semántica y difusa, y sirve APIs OGC que QGIS, ArcGIS y clientes MapLibre pueden usar de forma nativa. Está construido con FastAPI y React, y se despliega con un solo comando.

> Esta es una traducción resumida. El [README en inglés](README.md) es la fuente canónica; la documentación completa y actualizada en español está en **[docs.getgeolens.com/es](https://docs.getgeolens.com/es)**.

[![CI](https://github.com/geolens-io/geolens/actions/workflows/ci.yml/badge.svg)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: backend 3.13 / SDK 3.10+](https://img.shields.io/badge/python-3.13_backend_%7C_3.10%2B_SDK-blue.svg)]()
[![PostgreSQL 17 + PostGIS 3.5](https://img.shields.io/badge/PostGIS_3.5-PostgreSQL_17-336791.svg)](https://postgis.net/)
[![OGC Compliant](https://img.shields.io/badge/OGC_API-Features_%7C_Records-green.svg)](https://ogcapi.ogc.org/)

```bash
git clone https://github.com/geolens-io/geolens.git && cd geolens
bash scripts/install.sh
# Abre http://localhost:8080 — inicia sesión con las credenciales que elegiste
```

<p align="center">
  <img src=".github/assets/geolens-manhattan-3d-hero.jpg" alt="Constructor de mapas de GeoLens: huellas de edificios de Manhattan extruidas en un horizonte 3D, coloreadas según la altura del tejado, con el editor de estilo de capa abierto junto al mapa" width="900" />
  <br />
  <em>El constructor de mapas — las huellas de edificios de Manhattan extruidas según la altura del tejado y coloreadas mediante un estilo basado en datos, creado a partir de datos abiertos con <code>scripts/seed-showcase.py</code></em>
</p>

## Documentación

Documentación completa de usuario, administración y API:

- **En español:** [docs.getgeolens.com/es](https://docs.getgeolens.com/es)
- **Instalación y quickstart:** [docs.getgeolens.com/guides/quickstart](https://docs.getgeolens.com/guides/quickstart/)
- **Guía de administración:** [docs.getgeolens.com/guides/admin](https://docs.getgeolens.com/guides/admin/)
- **Referencia de API:** [docs.getgeolens.com/guides/api](https://docs.getgeolens.com/guides/api/)

## Artefactos publicados

```bash
pip install geolens          # SDK de Python
pip install geolens-cli      # CLI; instala el comando `geolens`
npm install @geolens/sdk     # SDK TypeScript/JavaScript
```

Imágenes públicas de API y frontend en GitHub Container Registry:

```bash
docker pull ghcr.io/geolens-io/geolens-api:latest
docker pull ghcr.io/geolens-io/geolens-frontend:latest
```

## Más información

Este README es una versión resumida. Encontrarás el resumen completo de funcionalidades, la configuración, la arquitectura y la guía de contribución en el **[README en inglés](README.md)** y en la **[documentación completa](https://docs.getgeolens.com/es)**.

## Licencia

Apache-2.0 — consulta [LICENSE](LICENSE) y [NOTICE](NOTICE).
