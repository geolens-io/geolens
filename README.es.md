# GeoLens

[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

**Los datos espaciales de tu equipo, buscables en un solo lugar.**

Sube Shapefiles, GeoTIFFs, GeoPackages o CSVs. GeoLens guarda todo en PostGIS, indexa los metadatos con pgvector + pg_trgm para busqueda semantica y difusa, y sirve APIs OGC que QGIS, ArcGIS y clientes MapLibre pueden usar de forma nativa. Esta construido con FastAPI y React, y se despliega con un solo comando.

> Esta traduccion sigue el README en ingles como fuente canonica. Si encuentras una traduccion imprecisa, abre una issue o una pull request.

[![CI](https://github.com/geolens-io/geolens/actions/workflows/ci.yml/badge.svg)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)]()
[![PostgreSQL 17 + PostGIS 3.5](https://img.shields.io/badge/PostGIS_3.5-PostgreSQL_17-336791.svg)](https://postgis.net/)
[![OGC Compliant](https://img.shields.io/badge/OGC_API-Features_%7C_Records-green.svg)](https://ogcapi.ogc.org/)

```bash
git clone https://github.com/geolens-io/geolens.git && cd geolens
cp .env.example .env && docker compose up -d
# Abre http://localhost:8080 - usuario: admin / admin
```

<p align="center">
  <img src=".github/assets/geolens-map-builder.png" alt="Constructor de mapas de GeoLens componiendo mapas interactivos con varias capas" width="900" />
  <br />
  <em>Sube un shapefile y obten un dataset buscable, previsualizable y exportable en minutos</em>
</p>

## Documentacion

La documentacion de usuario, administracion y API vive en **[docs.getgeolens.com](https://docs.getgeolens.com)**.

- **Instalacion y quickstart:** [docs.getgeolens.com/guides/quickstart](https://docs.getgeolens.com/guides/quickstart/)
- **Guia de administracion:** [docs.getgeolens.com/guides/admin](https://docs.getgeolens.com/guides/admin/)
- **Referencia de API:** [docs.getgeolens.com/guides/api](https://docs.getgeolens.com/guides/api/)

## Prueba la demo tematica

GeoLens incluye tres colecciones de demo tematicas: **Planet Earth** (raster + mosaicos VRT), **Global Development & People** (coropletas de indicadores) y **Borders, Boundaries & Contested Space** (geopolitica con cuidado). Nueve mapas destacados se cargan de forma determinista con un comando:

```bash
cp .env.demo .env
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

<p align="center">
  <img src=".github/assets/geolens-demo-tour.gif" alt="Recorrido de la demo de GeoLens mostrando constructor de mapas, busqueda de catalogo y detalle de dataset" width="900" />
</p>

Cuando termine la construccion de la imagen del seeder, abre http://localhost:8080 y entra en **Maps**. La descarga de GEBCO 2024 suele ser la parte lenta, alrededor de 10 a 15 minutos en una conexion rapida, y queda en cache para reconstrucciones.

Todos los datos se empaquetan durante la construccion de la imagen: **no hay llamadas de red salientes en runtime**. La demo puede reiniciarse cada 24 horas con el servicio `reset`.

## Artefactos publicados

GeoLens se publica en los registros de paquetes habituales:

```bash
pip install geolens          # SDK de Python
pip install geolens-cli      # CLI; instala el comando `geolens`
npm install @geolens/sdk     # SDK TypeScript/JavaScript
```

Imagenes runtime publicas en GitHub Container Registry:

```bash
docker pull ghcr.io/geolens-io/geolens-api:latest
docker pull ghcr.io/geolens-io/geolens-worker:latest
docker pull ghcr.io/geolens-io/geolens-frontend:latest
```

Las etiquetas `1.0`, `1` y `latest` siguen la linea actual de releases 1.x.

## Por que GeoLens?

Los datos espaciales terminan dispersos: shapefiles en unidades compartidas, tablas en esquemas de base de datos, rasters en buckets y metadatos en hojas de calculo. Encontrar el dataset correcto suele significar preguntar en Slack o buscar en servidores de archivos. Compartirlo implica exportar, enviar por correo y esperar que el CRS coincida.

GeoLens reemplaza ese flujo:

- **Un catalogo**: sube Shapefiles, GeoPackages, GeoTIFFs o CSVs y quedan buscables, previsualizables y exportables en minutos.
- **Funciona con tus herramientas**: OGC API Features/Records, STAC 1.1 y URLs directas de tiles para QGIS, ArcGIS y MapLibre.
- **Busqueda semantica + espacial**: encuentra datasets por significado, no solo por palabras clave, con pgvector y pg_trgm.
- **Constructor de mapas integrado**: compone mapas multicapa, estilizalos y compartelos por enlace publico o iframe embebible.
- **IA opcional**: conversa con tus mapas, genera descripciones y busca con lenguaje natural. Usa cualquier API compatible con OpenAI o no uses IA.

## En accion

Busca datasets por significado, no solo por palabras clave:

```bash
curl 'http://localhost:8080/api/search/datasets/?q=rivers+near+mountains&limit=3' \
  -H 'Authorization: Bearer <token>' | jq '.features[].properties.title'
```

Cada dataset tambien es un endpoint OGC API Features estandar:

```bash
curl 'http://localhost:8080/api/collections/ne_10m_admin_0_countries/items?bbox=-10,35,30,60&limit=5'
```

Conecta desde QGIS con **Layer > Add WFS / OGC API Features** y apunta a `http://localhost:8080/api/`.

## Funciones

### Constructor de mapas y uso compartido

- Mapas interactivos multicapa con ordenamiento por arrastrar y soltar, estilos y filtros por capa.
- Estilos para puntos, lineas y poligonos con rampas de color y cortes por categoria.
- Enlaces publicos e iframes embebibles.
- Capas raster COG y vectoriales lado a lado.

### Busqueda y descubrimiento

- Busqueda de texto completo y trigramas en nombres, descripciones y metadatos.
- Busqueda espacial con bounding boxes y filtros dibujados en el mapa.
- Facetas por formato, tags, colecciones y tipo de registro.
- Busqueda semantica opcional con pgvector.

### Ingestion y exportacion

- **Vector:** Shapefile, GeoPackage, GeoJSON, CSV y XLSX.
- **Raster:** GeoTIFF y Cloud-Optimized GeoTIFF con conversion automatica.
- **Mosaicos:** mosaicos raster basados en VRT.
- **Exportacion:** GeoJSON, Shapefile, GeoPackage y CSV con reproyeccion CRS.
- Trazabilidad de procedencia y edicion de metadatos.

### Estandares e interoperabilidad

- Compatible con OGC API - Features y OGC API - Records.
- Endpoint de catalogo STAC 1.1.
- URLs directas de tiles para QGIS, ArcGIS, MapLibre y clientes OGC.
- Autenticacion por API key para herramientas externas.
- JWT + OAuth 2.0/OIDC y RBAC con permisos por dataset.

## Inicio rapido

**Requisitos:** Docker Engine 24+ y Docker Compose v2. Minimo recomendado para el host: 4 GB de RAM y 10 GB libres para la pila base y un dataset pequeno; 8 GB+ de RAM para trabajos raster o catalogos de mas de 100 datasets.

```bash
git clone https://github.com/geolens-io/geolens.git
cd geolens
cp .env.example .env
docker compose up -d
```

Espera unos 60 segundos, abre [http://localhost:8080](http://localhost:8080) e inicia sesion con `admin` / `admin`.

## Arquitectura

| Componente | Tecnologia |
|-----------|------------|
| Frontend | React 19, Vite, MapLibre GL v5, TanStack Query, Tailwind CSS |
| Backend API | FastAPI (Python), GDAL/ogr2ogr, Procrastinate |
| Tiles raster | Titiler |
| Almacenamiento | MinIO o cualquier proveedor S3 |
| Cache | Valkey |
| Base de datos | PostgreSQL 17 + PostGIS 3.5 + pgvector + pg_trgm |
| Proxy inverso | Nginx en produccion / proxy Vite en desarrollo |

## Referencia

| Guia | Descripcion |
|-----|-------------|
| [Install Guide](https://docs.getgeolens.com/guides/quickstart/install/) | Despliegue paso a paso con Docker Compose |
| [Upgrade Guide](https://docs.getgeolens.com/guides/quickstart/upgrade/) | Actualizaciones entre versiones con rollback |
| [Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) | Variables de entorno y valores por defecto |
| [Admin Guide](https://docs.getgeolens.com/guides/admin/) | Usuarios, datasets y salud del sistema |
| [API Reference](#en-accion) | Swagger UI interactivo en `/api/docs` |

## Comunidad

- [GitHub Discussions](https://github.com/geolens-io/geolens/discussions): preguntas, ideas, show and tell.
- [Guia de contribucion](.github/CONTRIBUTING.md): entorno de desarrollo, estilo de codigo y pull requests.

## Licencia

Apache-2.0. Consulta [LICENSE](LICENSE).
