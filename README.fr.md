# GeoLens

[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

**Les données spatiales de votre équipe, consultables au même endroit.**

Importez des Shapefiles, GeoTIFFs, GeoPackages ou CSVs. GeoLens stocke tout dans PostGIS, indexe les métadonnées avec pgvector + pg_trgm pour la recherche sémantique et approximative, et expose des APIs OGC utilisables directement par QGIS, ArcGIS et les clients MapLibre. L'application est construite avec FastAPI et React, et se déploie avec une seule commande.

> Ceci est une traduction abrégée. Le [README anglais](README.md) est la source canonique ; la documentation complète et à jour en français est disponible sur **[docs.getgeolens.com/fr](https://docs.getgeolens.com/fr)**.

[![CI](https://github.com/geolens-io/geolens/actions/workflows/ci.yml/badge.svg)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: backend 3.13 / SDK 3.10+](https://img.shields.io/badge/python-3.13_backend_%7C_3.10%2B_SDK-blue.svg)]()
[![PostgreSQL 17 + PostGIS 3.5](https://img.shields.io/badge/PostGIS_3.5-PostgreSQL_17-336791.svg)](https://postgis.net/)
[![OGC API](https://img.shields.io/badge/OGC_API-Features_%7C_Records-green.svg)](https://ogcapi.ogc.org/)

```bash
curl -fsSL https://getgeolens.com/install.sh | sh
# Ouvrez http://localhost:8080, puis connectez-vous avec les identifiants choisis
```

<p align="center">
  <img src=".github/assets/geolens-manhattan-3d-hero.jpg" alt="Constructeur de cartes GeoLens : empreintes des bâtiments de Manhattan extrudées en une skyline 3D, colorées selon la hauteur du toit, avec l'éditeur de style de couche ouvert à côté de la carte" width="900" />
  <br />
  <em>Le constructeur de cartes : les empreintes des bâtiments de Manhattan extrudées selon la hauteur du toit et colorées par un style fondé sur les données, créé à partir de données ouvertes avec <code>scripts/seed-showcase.py</code></em>
</p>

## Documentation

Documentation complète utilisateur, administrateur et API :

- **En français :** [docs.getgeolens.com/fr](https://docs.getgeolens.com/fr)
- **Installation et démarrage rapide :** [docs.getgeolens.com/guides/quickstart](https://docs.getgeolens.com/guides/quickstart/)
- **Guide d'administration :** [docs.getgeolens.com/guides/admin](https://docs.getgeolens.com/guides/admin/)
- **Référence API :** [docs.getgeolens.com/guides/api](https://docs.getgeolens.com/guides/api/)

## Artefacts publiés

```bash
pip install geolens          # SDK Python
pip install geolens-cli      # CLI; installe la commande `geolens`
npm install @geolens/sdk     # SDK TypeScript/JavaScript
```

Images publiques API et frontend sur GitHub Container Registry :

```bash
docker pull ghcr.io/geolens-io/geolens-api:latest
docker pull ghcr.io/geolens-io/geolens-frontend:latest
```

## En savoir plus

Ce README est une version abrégée. Vous trouverez l'aperçu complet des fonctionnalités, la configuration, l'architecture et le guide de contribution dans le **[README anglais](README.md)** et dans la **[documentation complète](https://docs.getgeolens.com/fr)**.

## Licence

Apache-2.0. Voir [LICENSE](LICENSE) et [NOTICE](NOTICE).
