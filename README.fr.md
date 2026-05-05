# GeoLens

[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md)

**Les donnees spatiales de votre equipe, consultables au meme endroit.**

Importez des Shapefiles, GeoTIFFs, GeoPackages ou CSVs. GeoLens stocke tout dans PostGIS, indexe les metadonnees avec pgvector + pg_trgm pour la recherche semantique et approximative, et expose des APIs OGC utilisables directement par QGIS, ArcGIS et les clients MapLibre. L'application est construite avec FastAPI et React, et se deploie avec une seule commande.

> Cette traduction suit le README anglais comme source canonique. Si une traduction vous semble incorrecte, ouvrez une issue ou une pull request.

[![CI](https://github.com/geolens-io/geolens/actions/workflows/ci.yml/badge.svg)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)]()
[![PostgreSQL 17 + PostGIS 3.5](https://img.shields.io/badge/PostGIS_3.5-PostgreSQL_17-336791.svg)](https://postgis.net/)
[![OGC Compliant](https://img.shields.io/badge/OGC_API-Features_%7C_Records-green.svg)](https://ogcapi.ogc.org/)

```bash
git clone https://github.com/geolens-io/geolens.git && cd geolens
cp .env.example .env && docker compose up -d
# Ouvrez http://localhost:8080 - identifiants: admin / admin
```

<p align="center">
  <img src=".github/assets/geolens-map-builder.png" alt="Constructeur de cartes GeoLens composant des cartes interactives multicouches" width="900" />
  <br />
  <em>Importez un shapefile et obtenez un jeu de donnees consultable, previsualisable et exportable en quelques minutes</em>
</p>

## Documentation

La documentation utilisateur, administrateur et API est disponible sur **[docs.getgeolens.com](https://docs.getgeolens.com)**.

- **Installation et demarrage rapide:** [docs.getgeolens.com/guides/quickstart](https://docs.getgeolens.com/guides/quickstart/)
- **Guide d'administration:** [docs.getgeolens.com/guides/admin](https://docs.getgeolens.com/guides/admin/)
- **Reference API:** [docs.getgeolens.com/guides/api](https://docs.getgeolens.com/guides/api/)

## Essayer la demo thematique

GeoLens fournit trois collections de demo thematiques: **Planet Earth** (raster + mosaiques VRT), **Global Development & People** (choroplethes d'indicateurs) et **Borders, Boundaries & Contested Space** (geopolitique traitee avec soin). Neuf cartes signatures se chargent de facon deterministe avec une seule commande:

```bash
cp .env.demo .env
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d --build
```

<p align="center">
  <img src=".github/assets/geolens-demo-tour.gif" alt="Tour de demo GeoLens montrant le constructeur de cartes, la recherche catalogue et le detail d'un jeu de donnees" width="900" />
</p>

Quand la construction de l'image du seeder est terminee, ouvrez http://localhost:8080 et allez dans **Maps**. Le telechargement GEBCO 2024 est souvent l'etape la plus longue, environ 10 a 15 minutes sur une connexion rapide, puis il est mis en cache.

Toutes les donnees sont integrees pendant la construction de l'image: **aucun appel reseau sortant au runtime**. La demo peut etre reinitialisee toutes les 24 heures par le service `reset`.

## Artefacts publies

GeoLens est publie sur les registres de paquets standards:

```bash
pip install geolens          # SDK Python
pip install geolens-cli      # CLI; installe la commande `geolens`
npm install @geolens/sdk     # SDK TypeScript/JavaScript
```

Images runtime publiques sur GitHub Container Registry:

```bash
docker pull ghcr.io/geolens-io/geolens-api:latest
docker pull ghcr.io/geolens-io/geolens-worker:latest
docker pull ghcr.io/geolens-io/geolens-frontend:latest
```

Les tags `1.0`, `1` et `latest` suivent la ligne de release 1.x actuelle.

## Pourquoi GeoLens?

Les donnees spatiales finissent dispersees: shapefiles sur des partages reseau, tables dans des schemas de base de donnees, rasters dans des buckets et metadonnees dans des feuilles de calcul. Trouver le bon jeu de donnees revient souvent a demander sur Slack ou a fouiller des serveurs de fichiers. Le partager signifie exporter, envoyer par e-mail et esperer que le CRS corresponde.

GeoLens remplace ce flux:

- **Un catalogue**: importez Shapefiles, GeoPackages, GeoTIFFs ou CSVs et rendez-les consultables, previsualisables et exportables en quelques minutes.
- **Compatible avec vos outils**: OGC API Features/Records, STAC 1.1 et URLs directes de tuiles pour QGIS, ArcGIS et MapLibre.
- **Recherche semantique + spatiale**: trouvez les jeux de donnees par sens, pas seulement par mot-cle, avec pgvector et pg_trgm.
- **Constructeur de cartes integre**: composez des cartes multicouches, appliquez des styles et partagez-les par lien public ou iframe.
- **IA optionnelle**: discutez avec vos cartes, genere des descriptions et recherchez en langage naturel. Utilisez toute API compatible OpenAI ou ignorez l'IA.

## En action

Recherchez des jeux de donnees par sens, pas seulement par mot-cle:

```bash
curl 'http://localhost:8080/api/search/datasets/?q=rivers+near+mountains&limit=3' \
  -H 'Authorization: Bearer <token>' | jq '.features[].properties.title'
```

Chaque jeu de donnees est aussi un endpoint OGC API Features standard:

```bash
curl 'http://localhost:8080/api/collections/ne_10m_admin_0_countries/items?bbox=-10,35,30,60&limit=5'
```

Depuis QGIS, utilisez **Layer > Add WFS / OGC API Features** et pointez vers `http://localhost:8080/api/`.

## Fonctionnalites

### Constructeur de cartes et partage

- Cartes interactives multicouches avec ordre par glisser-deposer, styles et filtres par couche.
- Styles pour points, lignes et polygones avec rampes de couleurs et classes par categorie.
- Liens publics et snippets `<iframe>` embarquables.
- Couches raster COG et vectorielles cote a cote.

### Recherche et decouverte

- Recherche plein texte et trigrammes sur noms, descriptions et metadonnees.
- Recherche spatiale par bounding box et filtres dessines sur la carte.
- Facettes par format, tags, collections et type d'enregistrement.
- Recherche semantique optionnelle avec pgvector.

### Ingestion et export

- **Vecteur:** Shapefile, GeoPackage, GeoJSON, CSV et XLSX.
- **Raster:** GeoTIFF et Cloud-Optimized GeoTIFF avec conversion automatique.
- **Mosaiques:** mosaiques raster basees sur VRT.
- **Export:** GeoJSON, Shapefile, GeoPackage et CSV avec reprojection CRS.
- Suivi de provenance et edition de metadonnees.

### Standards et interoperabilite

- Conforme a OGC API - Features et OGC API - Records.
- Endpoint de catalogue STAC 1.1.
- URLs directes de tuiles pour QGIS, ArcGIS, MapLibre et clients OGC.
- Authentification par API key pour les outils externes.
- JWT + OAuth 2.0/OIDC et RBAC avec permissions par jeu de donnees.

## Demarrage rapide

**Prerequis:** Docker Engine 24+ et Docker Compose v2. Minimum conseille: 4 Go de RAM et 10 Go d'espace libre pour la pile de base et un petit jeu de donnees; 8 Go+ de RAM pour les traitements raster ou les catalogues de plus de 100 jeux de donnees.

```bash
git clone https://github.com/geolens-io/geolens.git
cd geolens
cp .env.example .env
docker compose up -d
```

Attendez environ 60 secondes, ouvrez [http://localhost:8080](http://localhost:8080), puis connectez-vous avec `admin` / `admin`.

## Architecture

| Composant | Technologie |
|-----------|-------------|
| Frontend | React 19, Vite, MapLibre GL v5, TanStack Query, Tailwind CSS |
| Backend API | FastAPI (Python), GDAL/ogr2ogr, Procrastinate |
| Tuiles raster | Titiler |
| Stockage objet | MinIO ou tout fournisseur S3 |
| Cache | Valkey |
| Base de donnees | PostgreSQL 17 + PostGIS 3.5 + pgvector + pg_trgm |
| Proxy inverse | Nginx en production / proxy Vite en developpement |

## Reference

| Guide | Description |
|------|-------------|
| [Install Guide](https://docs.getgeolens.com/guides/quickstart/install/) | Deploiement pas a pas avec Docker Compose |
| [Upgrade Guide](https://docs.getgeolens.com/guides/quickstart/upgrade/) | Mises a niveau avec procedures de rollback |
| [Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) | Variables d'environnement et valeurs par defaut |
| [Admin Guide](https://docs.getgeolens.com/guides/admin/) | Gestion des utilisateurs, datasets et sante systeme |
| [API Reference](#en-action) | Swagger UI interactif sur `/api/docs` |

## Communaute

- [GitHub Discussions](https://github.com/geolens-io/geolens/discussions): questions, idees, show and tell.
- [Guide de contribution](.github/CONTRIBUTING.md): environnement de developpement, style de code et pull requests.

## Licence

Apache-2.0. Voir [LICENSE](LICENSE).
