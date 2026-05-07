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

Quand la construction de l'image du seeder est terminee, ouvrez http://localhost:8080 et allez dans **Maps**. Le telechargement GEBCO 2024 est souvent l'etape la plus longue, environ 10 a 15 minutes sur une connexion rapide, puis il est mis en cache. Les recits signatures incluent:

- **Earth as Seen from Space**: bathymetrie + topographie + glace dans une vue sombre du monde
- **Global Bathymetry**: fond oceanique GEBCO 2024 avec colormap viridis
- **GDP per Capita PPP 2023**: choroplethe de pays depuis World Bank Open Data
- **Manhattan Skyline**: empreintes de batiments OpenStreetMap extrudees par hauteur pour le rendu fill-extrusion 3D
- **Population at a Glance**: lieux peuples en symboles proportionnels, dimensionnes par population
- **The World's Disputed Places**: toutes les zones contestees suivies par Natural Earth
- **One Territory, Multiple Official Maps**: Kashmir vu par la Chine, l'Inde et le Pakistan (activez/desactivez les couches)
- **Conflict Events 2024**: UCDP Georeferenced Event Dataset, evenements mortels de violence organisee
- **Refugees by Country of Origin 2023**: statistiques UNHCR jointes aux polygones de pays

Toutes les donnees sont integrees pendant la construction de l'image: **aucun appel reseau sortant au runtime**. La demo peut etre reinitialisee toutes les 24 heures par le service `reset`. Pour forcer une reinitialisation complete:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml exec reset /scripts/reset-demo.sh
docker compose -f docker-compose.yml -f docker-compose.demo.yml restart seeder
```

L'attribution des sources et les licences de chaque jeu de donnees de demo sont documentees sur sa page de detail. Toutes les donnees integrees sont CC-BY 4.0, ODbL 1.0 ou Public Domain.

## Artefacts publies

GeoLens est publie sur les registres de paquets standards:

```bash
pip install geolens          # SDK Python
pip install geolens-cli      # CLI; installe la commande `geolens`
npm install @geolens/sdk     # SDK TypeScript/JavaScript
```

Images publiques API et frontend sur GitHub Container Registry:

```bash
docker pull ghcr.io/geolens-io/geolens-api:latest
docker pull ghcr.io/geolens-io/geolens-frontend:latest
```

Les tags `1.0`, `1` et `latest` suivent la ligne de release 1.x actuelle.

## Pourquoi GeoLens?

Les donnees spatiales finissent dispersees: shapefiles sur des partages reseau, tables dans des schemas de base de donnees, rasters dans des buckets et metadonnees dans des feuilles de calcul. Trouver le bon jeu de donnees revient souvent a demander sur Slack ou a fouiller des serveurs de fichiers. Le partager signifie exporter, envoyer par e-mail et esperer que le CRS corresponde.

GeoLens remplace ce flux:

- **Un catalogue**: importez Shapefiles, GeoPackages, GeoTIFFs ou CSVs et rendez-les consultables, previsualisables et exportables en quelques minutes.
- **Compatible avec vos outils**: OGC API Features/Records avec filtrage CQL2, STAC 1.0 et URLs directes de tuiles pour QGIS, ArcGIS et MapLibre.
- **Recherche semantique + spatiale**: trouvez les jeux de donnees par sens, pas seulement par mot-cle, avec pgvector et pg_trgm.
- **Constructeur de cartes integre**: composez des cartes multicouches, appliquez des styles et partagez-les par lien public ou iframe.
- **IA optionnelle**: discutez avec vos cartes, generez des descriptions et recherchez en langage naturel. Utilisez toute API compatible OpenAI ou ignorez l'IA.

## En action

Recherchez des jeux de donnees par sens, pas seulement par mot-cle:

```bash
# Recherche semantique: trouve les jeux de donnees "hydrology" meme avec "rivers"
curl 'http://localhost:8080/api/search/datasets/?q=rivers+near+mountains&limit=3' \
  -H 'Authorization: Bearer <token>' | jq '.features[].properties.title'
```

Chaque jeu de donnees est aussi un endpoint OGC API Features standard:

```bash
# Features GeoJSON avec filtre bbox: fonctionne dans QGIS, ArcGIS et tout client OGC
curl 'http://localhost:8080/api/collections/ne_10m_admin_0_countries/items?bbox=-10,35,30,60&limit=5'
```

Depuis QGIS, utilisez **Layer > Add WFS / OGC API Features** et pointez vers `http://localhost:8080/api/`.

## Fonctionnalites

### Constructeur de cartes et partage

- Cartes interactives multicouches avec ordre par glisser-deposer, styles et filtres par couche.
- Styles pour points, lignes et polygones avec rampes de couleurs et classes par categorie.
- Liens publics et snippets `<iframe>` embarquables.
- Couches raster COG et vectorielles cote a cote.

### IA assistee (optionnelle)

- Discutez avec vos cartes: posez des questions en langage naturel, l'IA ajoute et stylise des couches.
- Recherche vectorielle semantique dans les metadonnees avec pgvector et index HNSW.
- Descriptions et tags de jeux de donnees generes automatiquement a l'ingestion.
- Compatible avec toute API compatible OpenAI (OpenAI, Anthropic, Ollama); GeoLens fonctionne entierement sans elle.

### Recherche et decouverte

- Recherche plein texte et trigrammes sur noms, descriptions et metadonnees.
- Recherche spatiale par bounding box et filtres dessines sur la carte.
- Facettes par format, tags, collections et type d'enregistrement.
- Recherche semantique optionnelle avec pgvector.
- Recherches sauvegardees pour les flux repetes.

### Ingestion et export

- **Vecteur:** Shapefile, GeoPackage, GeoJSON, CSV et XLSX.
- **Raster:** GeoTIFF et Cloud-Optimized GeoTIFF avec conversion automatique.
- **Mosaiques:** mosaiques raster basees sur VRT.
- **Export:** GeoJSON, Shapefile, GeoPackage et CSV avec reprojection CRS.
- Suivi de provenance et edition de metadonnees.

### Standards et interoperabilite

- Conforme a OGC API - Features et OGC API - Records.
- Endpoint de catalogue STAC 1.0.
- URLs directes de tuiles pour QGIS, ArcGIS, MapLibre et clients OGC.
- Authentification par API key pour les outils externes.
- JWT + OAuth 2.0/OIDC et RBAC avec permissions par jeu de donnees.

<details>
<summary>Entreprise et securite</summary>

- Authentification JWT avec refresh tokens.
- Gestion des API keys par utilisateur.
- Prise en charge OAuth 2.0 / OIDC (Google, Microsoft et fournisseurs generiques).
- Controle d'acces base sur les roles (RBAC) avec permissions par jeu de donnees.
- Audit logging pour toutes les actions administratives.
- Internationalisation: anglais, espagnol, francais, allemand.

</details>

## Captures d'ecran

<p align="center">
  <img src=".github/assets/geolens-catalog.png" alt="Vue catalogue de GeoLens" width="900" />
  <br />
  <em>Vue catalogue avec recherche, filtres spatiaux et cartes de jeux de donnees</em>
</p>

<p align="center">
  <img src=".github/assets/geolens-dataset.png" alt="Detail de jeu de donnees GeoLens" width="900" />
  <br />
  <em>Detail de jeu de donnees avec apercu cartographique, metadonnees et table attributaire</em>
</p>

## Demarrage rapide

**Prerequis:** Docker Engine 24+ et Docker Compose v2. Minimum conseille: 4 Go de RAM et 10 Go d'espace libre pour la pile de base et un petit jeu de donnees; 8 Go+ de RAM pour les traitements raster ou les catalogues de plus de 100 jeux de donnees. Voir [Resource Sizing](https://docs.getgeolens.com/guides/quickstart/resource-sizing/) pour le dimensionnement de production.

```bash
git clone https://github.com/geolens-io/geolens.git
cd geolens
cp .env.example .env
docker compose up -d
```

Attendez environ 60 secondes, ouvrez [http://localhost:8080](http://localhost:8080), puis connectez-vous avec `admin` / `admin`.

Verifiez que tous les services sont sains:

```bash
docker compose ps
```

Pour un deploiement en production, consultez l'[Install Guide](https://docs.getgeolens.com/guides/quickstart/install/). Pour les mises a niveau, consultez l'[Upgrade Guide](https://docs.getgeolens.com/guides/quickstart/upgrade/).

### Demo Mode

Executez une instance de demo pre-remplie avec des donnees d'exemple Natural Earth:

```bash
cp .env.demo .env
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d
```

L'overlay de demo amorce automatiquement 20 jeux de donnees representatifs, les rend publics et reinitialise les donnees toutes les 24 heures. Consultez `.env.demo` pour la configuration.

### Seed Data

Remplissez le catalogue avec 130 jeux de donnees [Natural Earth](https://www.naturalearthdata.com/) 1:10m:

```bash
pip install httpx  # dependance unique sur l'hote
python scripts/seed-natural-earth.py --api-key admin
```

Le script telecharge depuis le [NACIS CDN](https://naciscdn.org/naturalearth/), ignore les doublons lors d'une nouvelle execution et cree deux collections (Cultural 10m, Physical 10m). Utilisez `--dry-run` pour previsualiser ou `--theme cultural` pour filtrer par theme.

## Architecture

| Composant | Technologie |
|-----------|-------------|
| Frontend | React 19, Vite, MapLibre GL v5, TanStack Query, Tailwind CSS |
| Backend API | FastAPI (Python), GDAL/ogr2ogr, Procrastinate (queue de taches) |
| Tuiles raster | Titiler (serveur de tuiles COG) |
| Stockage objet | MinIO (compatible S3, dev local) ou tout fournisseur S3 |
| Cache | Valkey (cache de tuiles et requetes) |
| Base de donnees | PostgreSQL 17 + PostGIS 3.5 + pgvector + pg_trgm |
| Proxy inverse | Nginx (production) / proxy Vite dev (developpement) |

## Configuration

Toute la configuration est geree par variables d'environnement dans `.env`. Consultez la [Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) pour la liste complete des options avec valeurs par defaut et descriptions.

## Reference

| Guide | Description |
|------|-------------|
| [Install Guide](https://docs.getgeolens.com/guides/quickstart/install/) | Deploiement pas a pas avec Docker Compose |
| [Upgrade Guide](https://docs.getgeolens.com/guides/quickstart/upgrade/) | Mises a niveau avec procedures de rollback |
| [Configuration Reference](https://docs.getgeolens.com/guides/quickstart/configuration/) | Variables d'environnement et valeurs par defaut |
| [Admin Guide](https://docs.getgeolens.com/guides/admin/) | Gestion des utilisateurs, datasets et sante systeme |
| [Cloud Deployment](https://docs.getgeolens.com/guides/quickstart/cloud-deployment/) | Guides de deploiement AWS, GCP et DigitalOcean |
| [Developer Docs](https://docs.getgeolens.com/) | Creer des widgets personnalises pour le map builder |
| [API Reference](#en-action) | Swagger UI interactif sur `/api/docs` |

## Communaute

- [GitHub Discussions](https://github.com/geolens-io/geolens/discussions): questions, idees, show and tell.
- [Guide de contribution](.github/CONTRIBUTING.md): environnement de developpement, style de code et pull requests.

## Licence

GeoLens est sous [Apache License 2.0](LICENSE).
