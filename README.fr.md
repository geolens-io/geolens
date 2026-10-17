<p align="center">
  <img src="frontend/public/app-icon-dark.png" alt="Logo de GeoLens : une loupe devant un globe, avec des repères de réticule" width="96">
</p>

<h1 align="center">GeoLens</h1>

<p align="center">
  <b>Un catalogue de données spatiales et un générateur de cartes auto-hébergés, qui gardent la trace de l’origine de chaque jeu de données.</b>
</p>

<p align="center">
  <a href="https://demo.getgeolens.com"><b>Démonstration en ligne</b></a> ·
  <a href="#installation">Installation</a> ·
  <a href="https://docs.getgeolens.com">Documentation</a> ·
  <a href="#utiliser-les-données-partout">Connecter QGIS ou du code</a> ·
  <a href="https://github.com/geolens-io/geolens/discussions">Discussions</a>
</p>

<div align="center">

[English](README.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [简体中文](README.zh.md)

[![Dernière version](https://img.shields.io/github/v/release/geolens-io/geolens?style=flat-square&label=version)](https://github.com/geolens-io/geolens/releases/latest)
[![État de la CI](https://img.shields.io/github/actions/workflow/status/geolens-io/geolens/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![Licence : Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-2563eb?style=flat-square)](LICENSE)

</div>

<p align="center">
  <a href="https://demo.getgeolens.com/maps">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-manhattan-3d-hero-dark.jpg">
      <img src=".github/assets/geolens-manhattan-3d-hero.jpg" alt="Le générateur de cartes GeoLens affichant les bâtiments de Manhattan extrudés à la hauteur relevée de leur toit et colorés selon l’époque de construction, avec le réseau de métro, la liste des couches et une légende" width="100%">
    </picture>
  </a>
  <br>
  <sub>Les bâtiments de Manhattan à la hauteur relevée de leur toit, colorés selon l’époque de construction, avec le réseau de métro. <a href="https://demo.getgeolens.com/maps">Parcourir les cartes de la démonstration</a>.</sub>
</p>

GeoLens s’adresse aux équipes dont les données spatiales sont dispersées entre partages de
fichiers, bases PostGIS, services web et catalogues STAC. Il les réunit dans un seul catalogue
consultable, consigne l’origine de chaque jeu de données et vérifie que la source est toujours à
jour. Les équipes créent et partagent des cartes dans le navigateur, et QGIS, les scripts et les
agents IA lisent les mêmes données via OGC API et STAC. Il s’exécute sur vos propres serveurs avec
Docker Compose, n’envoie aucune télémétrie et est publié sous licence Apache 2.0.

La [démonstration](https://demo.getgeolens.com) ne demande ni installation ni compte ; connectez-vous
avec Google, GitHub ou Microsoft pour utiliser le générateur de cartes. Les données de
démonstration peuvent être effacées à tout moment.

## De plus près

<table>
<tr>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-catalog-search-dark.png">
<img src=".github/assets/geolens-catalog-search.png" alt="Recherche dans le catalogue GeoLens pour « where storms hit the coast », hors connexion, listant des jeux de données sur les ouragans et le littoral avec des badges de type, de source et d’actualité à côté des filtres" width="100%">
</picture>
<br><sub>Recherche par le sens : « where storms hit the coast » trouve des trajectoires d’ouragans et des couches d’exposition du littoral.</sub>
</td>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-dataset-page-dark.png">
<img src=".github/assets/geolens-dataset-page.png" alt="La page du jeu de données Atlantic Hurricane Tracks : trajectoires de tempêtes sur un aperçu cartographique, badges vectoriel, chargé, source à jour, publié et public, et le nombre d’entités, la géométrie, le SRC, la version et le nombre de colonnes" width="100%">
</picture>
<br><sub>Chaque jeu de données a une page avec un aperçu cartographique, ses métadonnées, ses attributs et son origine.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-import-preview-dark.png">
<img src=".github/assets/geolens-import-preview.png" alt="L’onglet URL de service de la page Importer des données, avec l’aperçu de la couche ArcGIS USGS Significant Earthquakes : SRC, type de géométrie, nombre d’entités, nom de la couche et lignes d’exemple" width="100%">
</picture>
<br><sub>Avant d’importer une couche de service, GeoLens en affiche les colonnes et les premières lignes.</sub>
</td>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-version-history-dark.png">
<img src=".github/assets/geolens-version-history.png" alt="Historique des versions du jeu de données Significant Volcanic Eruptions : trois versions GeoJSON avec dates, noms de fichiers et nombres d’entités, la version actuelle repérée et un bouton Restaurer sur la version précédente" width="100%">
</picture>
<br><sub>Remplacer un jeu de données conserve les anciennes versions, et vous pouvez restaurer la précédente.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-builder-style-dark.png">
<img src=".github/assets/geolens-builder-style.png" alt="Le générateur de cartes avec la carte Restless Earth sur un globe : une carte de chaleur des séismes le long des limites de plaques du Pacifique, la liste des couches groupées et le panneau de style de la carte de chaleur avec ses palettes de couleurs" width="100%">
</picture>
<br><sub>Les couches s’affichent en points, symboles, cartes de chaleur ou regroupements, et la liste des palettes peut se limiter à celles adaptées au daltonisme.</sub>
</td>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-matterhorn-terrain-dark.jpg">
<img src=".github/assets/geolens-matterhorn-terrain.jpg" alt="Le générateur de cartes GeoLens affichant le Cervin en terrain 3D à partir du lidar swissALTI3D, avec sommets nommés, itinéraires d’escalade, la liste des couches et une légende" width="100%">
</picture>
<br><sub>Un terrain 3D issu de vos propres données d’élévation, ici le Cervin à partir du lidar swissALTI3D.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-stac-imagery-dark.jpg">
<img src=".github/assets/geolens-stac-imagery.jpg" alt="Le générateur de cartes affichant quatre scènes Sentinel-2 en vraies couleurs, à des dates différentes, au-dessus de New York et du nord du New Jersey, référencées depuis le catalogue STAC Earth Search, avec la liste des couches et la légende" width="100%">
</picture>
<br><sub>Des scènes Sentinel-2 référencées depuis un catalogue STAC. L’imagerie reste où elle est et est découpée en tuiles à la demande.</sub>
</td>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-share-embed-dark.png">
<img src=".github/assets/geolens-share-embed.png" alt="La boîte de dialogue de partage d’une carte : visibilité réglée sur Public, avec Vous seul et Tous les membres de l’équipe comme autres options, un lien de partage et un code d’intégration iframe" width="100%">
</picture>
<br><sub>Gardez une carte pour vous, ouvrez-la à votre équipe ou rendez-la publique avec un lien et un code d’intégration.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-admin-overview-dark.png">
<img src=".github/assets/geolens-admin-overview.png" alt="La page Aperçu de l’administration : Tous les systèmes opérationnels, avec l’état de la base de données, du stockage, du cache et du cache de tuiles, le nombre total de jeux de données, les ajouts récents et l’espace utilisé, à côté du menu d’administration" width="100%">
</picture>
<br><sub>L’aperçu de l’administration montre l’état des services à côté des totaux de jeux de données et de stockage.</sub>
</td>
<td width="50%" valign="top">
<picture>
<source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-admin-permissions-dark.png">
<img src=".github/assets/geolens-admin-permissions.png" alt="La page Permissions de l’administration : des capacités comme Télécharger des jeux de données, Exporter des données, Modifier les métadonnées et Gérer les utilisateurs, avec une case à cocher pour chacun des rôles Lecteur, Éditeur et Administrateur" width="100%">
</picture>
<br><sub>Les rôles lecteur, éditeur et administrateur, avec chaque capacité activée ou non par rôle.</sub>
</td>
</tr>
</table>

## Comment tout s’articule

```mermaid
flowchart LR
    subgraph IN ["Apporter des données"]
      F["Fichiers<br/>GeoPackage · Shapefile · GeoParquet<br/>GeoTIFF · COPC · 3D Tiles"]
      DB["Tables PostGIS existantes"]
      SVC["Services<br/>ArcGIS · WFS · OGC API Features"]
      ST["Ressources STAC distantes"]
    end
    subgraph GL ["GeoLens"]
      CAT["Catalogue<br/>recherche · métadonnées · provenance"]
      MB["Générateur de cartes<br/>styles · 3D · analyse · partage"]
      STD["API ouvertes<br/>OGC API · STAC · DCAT · tuiles"]
    end
    subgraph OUT ["Utiliser partout"]
      WEB["Navigateurs et intégrations"]
      GIS["QGIS · ArcGIS · CesiumJS"]
      CODE["curl · Python · TypeScript · DuckDB"]
      AG["Agents IA via MCP"]
    end
    F & DB & SVC & ST --> CAT
    CAT --> MB --> WEB
    CAT --> STD --> GIS & CODE & AG
```

## Un seul catalogue pour des données dispersées

- Chargez des Shapefile, GeoPackage, GeoJSON, GeoParquet, FlatGeobuf, KML/KMZ, File Geodatabase
  zippées, CSV, Excel ou GeoTIFF (convertis en Cloud-Optimized GeoTIFF). Les jeux 3D Tiles et les
  nuages de points COPC sont hébergés pour CesiumJS, QGIS et Potree.
- Servez sur place les tables déjà présentes dans la base PostGIS de GeoLens, importez des couches
  WFS, ArcGIS et OGC API Features et actualisez-les à la demande, ou référencez des ressources
  STAC distantes sans les copier.
- Dessinez de nouveaux jeux de données dans le navigateur.
- Retrouvez les données par recherche approximative, ou par le sens une fois un fournisseur
  d’embeddings configuré. Filtrez par type, lieu et période, regroupez les jeux de données en
  collections, modifiez les métadonnées et restaurez la version précédente d'un jeu de données après un remplacement.

## Savoir d’où vient chaque jeu de données

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-provenance-dark.png">
    <img src=".github/assets/geolens-provenance.png" alt="L’onglet Source du jeu de données USGS Earthquakes : importé depuis le service ArcGIS de l’USGS dans une copie propre, avec les dates de dernière actualisation et de dernière vérification, le nombre d’entités et les badges Disponible, À jour et Aucune évolution" width="100%">
  </picture>
  <br>
  <sub>Un jeu de données importé depuis le service de séismes de l’USGS.</sub>
</p>

Chaque jeu de données consigne son origine : un fichier chargé, une table de base de données, un
service, un élément STAC ou un dessin réalisé dans le navigateur. Les jeux importés consignent aussi
la date de leur dernière actualisation, et avec une fréquence de mise à jour, GeoLens les marque
comme à jour, à actualiser ou en retard. Pour les services et les sources STAC, GeoLens
vérifie aussi que la source répond encore et, pour les services, signale les changements de
schéma en amont avant qu’ils n’atteignent vos cartes. Si un service disparaît, la copie importée continue de
fonctionner.

## Créer et partager des cartes

- Couches de points, de symboles, de cartes de chaleur, de regroupements, de lignes, de flèches,
  de remplissages, d’extrusion 3D, de rasters et d’ombrage du relief, avec styles pilotés par les
  données, étiquettes, icônes, motifs, filtres et fenêtres contextuelles. Le terrain provient de
  vos propres modèles d’élévation.
- Tampon, centroïde, découpage, fusion, jointure spatiale, sélection par localisation, mesure et
  intersection. La plupart des opérations s’affichent d’abord en aperçu sur la carte, et chaque
  résultat est enregistré comme un nouveau jeu de données, depuis le générateur ou la CLI.
- Les liens publics affichent le titre et l’image de la carte lorsqu’ils sont collés dans Slack,
  Teams ou les réseaux sociaux, et les cartes s’intègrent à d’autres sites avec des jetons privés.
- L’interface est disponible en anglais, espagnol, français, allemand et chinois simplifié.

## Utiliser les données partout

Les jeux de données vectoriels sont des collections OGC API Features, le catalogue est exposé en
OGC API Records et STAC, et chaque couche dispose d’une URL de tuiles. Vous pouvez l’essayer sur la
démonstration sans compte (la deuxième commande nécessite `jq`) :

```sh
# Search the catalog (OGC API Records)
curl "https://demo.getgeolens.com/api/collections/datasets/items?q=volcanic%20eruptions"

# Read the top match with a CQL2 filter (OGC API Features): eruptions of VEI 6 or larger
ID=$(curl -s "https://demo.getgeolens.com/api/collections/datasets/items?q=volcanic%20eruptions&limit=1" | jq -r '.features[0].id')
curl -G "https://demo.getgeolens.com/api/collections/$ID/items" \
  --data-urlencode "filter=vei >= 6" -d limit=3
```

Dans QGIS, ajoutez `https://demo.getgeolens.com/api/` comme connexion WFS / OGC API Features pour
lister les jeux de données publics comme couches. Le
[guide QGIS](https://docs.getgeolens.com/guides/api/qgis/) détaille les étapes.

<p align="center">
  <img src=".github/assets/geolens-qgis.png" alt="QGIS 4 avec la démonstration GeoLens ajoutée comme connexion OGC API Features : le panneau Explorateur liste les collections de la démonstration, et les séismes récents, les éruptions volcaniques importantes, les limites de plaques et les pays de la démonstration sont chargés comme couches sur une carte du monde" width="100%">
  <br>
  <sub>QGIS lit la démonstration via OGC API Features, sans extension.</sub>
</p>

| Standard | Emplacement | À utiliser avec |
|---|---|---|
| OGC API Features, avec filtrage CQL2 et queryables | `/api/collections/{id}/items` | QGIS, ArcGIS, GDAL/OGR et autres clients OGC API |
| OGC API Records | `/api/collections/datasets/items` | Recherche dans le catalogue depuis d’autres portails et outils |
| STAC API 1.0 | `/api/stac/` | Clients STAC comme pystac-client et STAC Browser |
| DCAT 3, DCAT-US 3.0 et GeoDCAT-AP en JSON-LD | `/api/datasets/dcat/`, `/api/datasets/dcat-us/3.0/`, `/api/datasets/geodcat-ap/` | Moissonnage vers les portails nationaux et européens de données ouvertes |
| Tuiles vectorielles et tuiles raster COG | une URL de tuiles sur chaque couche | MapLibre, OpenLayers, Leaflet |
| 3D Tiles et COPC | la page de chaque jeu de données 3D | CesiumJS, QGIS, Potree |

Les tuiles vectorielles suppriment les colonnes d’attributs en dessous du zoom 10 ; ajoutez
`cols=<column>,<column>` à une URL de tuiles pour conserver certaines colonnes. Les données
s’exportent en GeoJSON, Shapefile, GeoPackage, CSV, FlatGeobuf, GeoParquet, PMTiles ou
Cloud-Optimized GeoTIFF.

La CLI `geolens` publie des fichiers et applique des manifestes de catalogue, des SDK Python et
TypeScript couvrent l’API, et un serveur MCP en lecture seule permet aux agents IA de chercher dans
le catalogue. La [galerie d’exemples](https://geolens-io.github.io/geolens-examples/) propose du
code exécutable pour MapLibre, Leaflet, OpenLayers, l’ArcGIS Maps SDK, QGIS et DuckDB.

## IA facultative

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-ask-ai-dark.png">
    <img src=".github/assets/geolens-ask-ai.png" alt="Le panneau Demander à l’IA sur le jeu de données Major Hurricane Tracks répondant à « How many of these hurricanes made landfall? » par 119 sur 202, un tableau de comptage à deux lignes, une note sur la façon dont la colonne d’atterrissage a été interprétée et un bouton Ouvrir dans l’éditeur" width="100%">
  </picture>
  <br>
  <sub>« How many of these hurricanes made landfall? » renvoie le décompte, un tableau et l’hypothèse sur laquelle repose la réponse.</sub>
</p>

GeoLens peut répondre à des questions sur un jeu de données, modifier des cartes à partir de
demandes en langage courant, rédiger des métadonnées et chercher en langage naturel. Il fonctionne
avec n’importe quel point de terminaison compatible OpenAI, y compris un serveur local comme
Ollama, et avec Claude via Anthropic, Microsoft Foundry, Amazon Bedrock ou Google Vertex AI.
L’IA reste désactivée tant qu’un administrateur n’a pas configuré de fournisseur, et chaque
workflow fonctionne sans elle.

## Installation

Il vous faut Git, curl, Docker Engine 24+ et Docker Compose v2. Une installation neuve exécute six conteneurs
avec environ 1,3 Go de mémoire sur linux/amd64 ou linux/arm64.

```sh
curl -fsSL https://getgeolens.com/install.sh | sh    # clone, generate secrets, start the stack
cd geolens
grep '^GEOLENS_ADMIN_PASSWORD=' .env                  # the generated admin password
```

Ouvrez http://localhost:8080 et connectez-vous en tant que `admin`, le nom d’utilisateur par défaut
de l’installateur. L’installateur génère les secrets et le mot de passe administrateur, télécharge
les images précompilées et démarre la pile en une minute environ. Pour vérifier le script
d’abord, téléchargez `install.sh` et `SHA256SUMS` depuis la même
[version](https://github.com/geolens-io/geolens/releases) et lancez `sha256sum -c SHA256SUMS`
(`shasum -a 256 -c SHA256SUMS` sous macOS).

- Pour compiler depuis les sources, clonez le dépôt et lancez `bash scripts/install.sh`. La
  première compilation prend 5-10 minutes.
- Les images précompilées sont `ghcr.io/geolens-io/geolens-api` et
  `ghcr.io/geolens-io/geolens-frontend`, et `latest` est la dernière version stable.
- Pour la production, lisez le [guide d’installation](https://docs.getgeolens.com/guides/quickstart/install/)
  et les guides pour les [services cloud gérés](https://docs.getgeolens.com/guides/quickstart/cloud-deployment/).
  Docker Compose est la voie prise en charge ; un chart Helm expérimental, maintenu par la
  communauté, se trouve dans [geolens-deployments](https://github.com/geolens-io/geolens-deployments).

Une base de données externe doit être PostgreSQL 15+ avec PostGIS, pgvector 0.5+, pg_trgm et
unaccent, et ses sauvegardes vous incombent. La base fournie est sauvegardée chaque jour et chaque
semaine, avec des copies hors site facultatives vers S3. Pour mettre à jour une installation à
images précompilées, lancez `./scripts/upgrade.sh` dans le répertoire d’installation : il
sauvegarde la base, télécharge les nouvelles images et migre derrière un contrôle de santé. Les
installations compilées depuis les sources mettent à jour leur copie du dépôt et recompilent.
[UPGRADING.md](UPGRADING.md) couvre les deux cas, retour arrière compris.

[RUNBOOK.md](RUNBOOK.md) couvre l’exploitation, `infra/monitoring/` contient des règles d’alerte
Prometheus et un tableau de bord Grafana, et la
[référence de configuration](https://docs.getgeolens.com/guides/quickstart/configuration/) liste
chaque paramètre.

## Votre premier jeu de données

Publiez le fichier d’exemple avec la CLI, puis relisez-le via OGC API Features :

```sh
python3 -m venv .venv && . .venv/bin/activate         # Python 3.11+; on Debian/Ubuntu, apt install python3-venv
pip install geolens-cli
geolens login http://localhost:8080/api               # your admin username and password
geolens publish examples/manifests/first-catalog/city-parks.geojson --name "City Parks"
export GEOLENS_API_KEY="paste-your-api-key-here"      # create one on your Settings page
curl -H "X-Api-Key: $GEOLENS_API_KEY" \
  "http://localhost:8080/api/collections/<dataset-id>/items?limit=5"
```

`geolens publish` affiche l’URL du jeu de données, qui se termine par son identifiant. Pour gérer
un catalogue entier, décrivez les sources dans un manifeste `geolens.yaml` et lancez
`geolens apply` ; [`examples/manifests/`](examples/manifests/) contient des modèles et le
[guide de la CLI](https://docs.getgeolens.com/guides/cli/) donne le schéma.

Pour charger dans votre installation les cartes et les jeux de données de la démonstration,
lancez le script d’amorçage. Il nécessite un accès à internet et télécharge des données ouvertes
publiques depuis une douzaine de sources, dont un fichier de relief d’environ 466 Mo et 62 tuiles
de terrain ; `--no-oceans` et `--no-terrain` les ignorent, et
[scripts/README.md](scripts/README.md) liste toutes les options. Utilisez votre propre nom
d’administrateur si vous l’avez changé.

```sh
python3 -m venv .venv && . .venv/bin/activate         # the same virtualenv as above
pip install httpx
GEOLENS_ADMIN_PASSWORD="$(grep '^GEOLENS_ADMIN_PASSWORD=' .env | cut -d= -f2-)" \
  python scripts/seed-showcase.py --username admin
```

La [référence de l’API](https://docs.getgeolens.com/guides/api/) et les
[guides des SDK](https://docs.getgeolens.com/guides/sdk/) couvrent le reste.

## Confidentialité et accès

- GeoLens n’envoie aucune télémétrie. Hormis les tuiles de fond de carte par défaut et les
  services distants ou sources STAC que vos utilisateurs enregistrent, il n’effectue d’appels
  sortants que pour les fonctions qu’un administrateur active. [EGRESS.md](EGRESS.md) les liste et
  explique comment fonctionner en réseau isolé.
- Vos données restent lisibles sans GeoLens. Les jeux de données vectoriels sont de simples tables
  PostGIS dans un schéma `data`, les rasters sont des Cloud-Optimized GeoTIFF dans votre propre
  stockage (disque local, S3/MinIO ou Azure Blob), et le catalogue s’exporte via OGC API, STAC et
  DCAT.
- La connexion utilise des comptes locaux ou OAuth 2.0/OIDC (Google, Microsoft, GitHub ou un
  fournisseur générique), avec rôles, permissions par jeu de données, clés d’API par utilisateur et
  journal d’audit. L’inscription libre est désactivée par défaut.
- Le code de ce dépôt est sous licence Apache 2.0 (le nom et le logo ne le sont pas), et les fonctions publiées ici
  restent gratuites. [EDITIONS.md](EDITIONS.md) décrit le support payant et les modules
  complémentaires facultatifs.

## Limites connues

- Une seule instance PostgreSQL, sans haute disponibilité ni clustering intégrés.
- Une organisation par déploiement.
- Le rendu du terrain suppose une élévation en mètres ; les autres unités verticales produisent un
  rendu exagéré.
- L’API REST propre à GeoLens peut changer entre versions mineures (les points de terminaison
  standard suivent leurs spécifications). Le [CHANGELOG](CHANGELOG.md) liste les changements de
  contrat, et un changement incompatible conserve l’ancienne forme fonctionnelle pendant une
  version mineure supplémentaire.

## Contribuer

Les rapports de bogues, correctifs, traductions et contributions à la documentation sont les
bienvenus. [CONTRIBUTING](.github/CONTRIBUTING.md) couvre la configuration (`make dev-init`, puis
`make dev`), les tests et la signature DCO, et [ARCHITECTURE](.github/ARCHITECTURE.md) cartographie
le code. Posez vos questions dans les
[GitHub Discussions](https://github.com/geolens-io/geolens/discussions), signalez les bogues dans
les [Issues](https://github.com/geolens-io/geolens/issues) et les problèmes de sécurité en privé,
comme décrit dans [SECURITY.md](.github/SECURITY.md). La
[feuille de route](https://docs.getgeolens.com/roadmap/) montre ce qui est prévu.

## Licence

GeoLens est publié sous la [licence Apache 2.0](LICENSE). Le nom, le logo et les éléments de
marque de GeoLens ne sont pas couverts par cette licence ; voir [TRADEMARKS.md](TRADEMARKS.md).
L’attribution des données d’exemple figure dans [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md).

Politiques du projet : [éditions](EDITIONS.md) · [support](SUPPORT.md) · [gouvernance](GOVERNANCE.md) · [mainteneurs](MAINTAINERS.md) · [sécurité](.github/SECURITY.md) · [processus de publication](RELEASE.md) · [sorties réseau &amp; réseau isolé](EGRESS.md)
