<p align="center">
  <img src="frontend/public/app-icon-dark.png" alt="GeoLens-Logo: eine Lupe über einem Globus mit Fadenkreuzmarkierungen" width="96">
</p>

<h1 align="center">GeoLens</h1>

<p align="center">
  <b>Ein selbst gehosteter Geodatenkatalog und Karteneditor, der festhält, woher jeder Datensatz stammt.</b>
</p>

<p align="center">
  <a href="https://demo.getgeolens.com"><b>Live-Demo</b></a> ·
  <a href="#installation">Installation</a> ·
  <a href="https://docs.getgeolens.com">Dokumentation</a> ·
  <a href="#daten-von-überall-nutzen">QGIS oder Code anbinden</a> ·
  <a href="https://github.com/geolens-io/geolens/discussions">Discussions</a>
</p>

<div align="center">

[English](README.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [简体中文](README.zh.md)

[![Latest release](https://img.shields.io/github/v/release/geolens-io/geolens?style=flat-square&label=release)](https://github.com/geolens-io/geolens/releases/latest)
[![CI status](https://img.shields.io/github/actions/workflow/status/geolens-io/geolens/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/geolens-io/geolens/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-2563eb?style=flat-square)](LICENSE)

</div>

<p align="center">
  <a href="https://demo.getgeolens.com/maps">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-manhattan-3d-hero-dark.jpg">
      <img src=".github/assets/geolens-manhattan-3d-hero.jpg" alt="Der GeoLens-Karteneditor zeigt Manhattans Gebäude, bis zu ihren vermessenen Dachhöhen extrudiert und nach Bauzeit eingefärbt, dazu das U-Bahn-Netz, die Ebenenliste und eine Legende" width="100%">
    </picture>
  </a>
  <br>
  <sub>Manhattans Gebäude in ihren vermessenen Dachhöhen, nach Bauzeit eingefärbt, mit dem U-Bahn-Netz. <a href="https://demo.getgeolens.com/maps">Die Karten der Demo ansehen</a>.</sub>
</p>

Geodaten liegen oft an vielen Orten zugleich: auf Dateifreigaben, in PostGIS-Datenbanken, in
ArcGIS- und WFS-Diensten, in STAC-Katalogen. GeoLens führt sie in einem durchsuchbaren Katalog
zusammen und hält fest, woher jeder Datensatz stammt und ob seine Quelle noch aktuell ist. Im
Browser erstellen und teilen Nutzer Karten aus diesem Katalog, während QGIS, Skripte und
KI-Agenten dieselben Daten über OGC API und STAC lesen. GeoLens läuft mit Docker Compose auf Ihren
eigenen Servern, sendet keine Telemetrie und steht unter der Apache-2.0-Lizenz.

Die [Demo](https://demo.getgeolens.com) braucht keine Installation. Katalog und Karten lassen sich
ohne Konto durchsuchen; mit einer Anmeldung über Google, GitHub oder Microsoft können Sie den
Karteneditor ausprobieren (Demodaten können jederzeit gelöscht werden).

## So greift alles ineinander

```mermaid
flowchart LR
    subgraph IN ["Daten einbringen"]
      F["Dateien<br/>GeoPackage · Shapefile · GeoParquet<br/>GeoTIFF · COPC · 3D Tiles"]
      DB["Vorhandene PostGIS-Tabellen"]
      SVC["Dienste<br/>ArcGIS · WFS · OGC API Features"]
      ST["Entfernte STAC-Assets"]
    end
    subgraph GL ["GeoLens"]
      CAT["Katalog<br/>Suche · Metadaten · Herkunft"]
      MB["Karteneditor<br/>Stile · 3D · Analyse · Teilen"]
      STD["Offene APIs<br/>OGC API · STAC · DCAT · Kacheln"]
    end
    subgraph OUT ["Überall nutzen"]
      WEB["Browser und Einbettungen"]
      GIS["QGIS · ArcGIS · CesiumJS"]
      CODE["curl · Python · TypeScript · DuckDB"]
      AG["KI-Agenten über MCP"]
    end
    F & DB & SVC & ST --> CAT
    CAT --> MB --> WEB
    CAT --> STD --> GIS & CODE & AG
```

## Ein Katalog für verstreute Daten

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-catalog-search-dark.png">
    <img src=".github/assets/geolens-catalog-search.png" alt="GeoLens-Katalogsuche nach „where storms hit the coast“ mit sechs Hurrikan- und Küstendatensätzen samt Vorschaubildern, Herkunfts- und Aktualitätsmarkierungen, daneben Filter für Typ, Schlüsselwort, Collection, Ort und Datum" width="100%">
  </picture>
  <br>
  <sub>Suche nach Bedeutung: „where storms hit the coast“ findet Hurrikanbahnen, Sturmkorridore und Ebenen zur Küstenexposition, jeweils mit Angabe ihrer Herkunft.</sub>
</p>

- **Dateien hochladen.** Shapefile, GeoPackage, GeoJSON, GeoParquet, FlatGeobuf, KML/KMZ, gezippte
  File Geodatabase, CSV und Excel. GeoTIFFs werden zu Cloud-Optimized GeoTIFFs, und viele Raster
  lassen sich zu einem VRT-Mosaik zusammenfassen. 3D-Tiles-Tilesets und COPC-Punktwolken werden
  für CesiumJS, QGIS und Potree bereitgestellt.
- **Vorhandenes registrieren.** Tabellen, die bereits in der PostGIS-Datenbank von GeoLens liegen,
  werden direkt bereitgestellt. WFS, ArcGIS FeatureServer und MapServer sowie OGC-API-Features-Layer
  werden importiert und bei Bedarf aktualisiert. Entfernte STAC-Assets werden referenziert, ohne
  sie zu kopieren.
- **Neue Daten zeichnen** Sie im Browser, wenn es sie noch nirgends gibt.
- **Wiederfinden.** Die unscharfe Suche funktioniert sofort, die Suche nach Bedeutung kommt hinzu,
  sobald Sie einen Embedding-Anbieter konfigurieren. Filtern Sie nach Typ, Ort und Zeit, fassen
  Sie Datensätze zu Collections zusammen, bearbeiten Sie typisierte Metadaten und stellen Sie
  frühere Versionen wieder her.

## Wissen, woher jeder Datensatz stammt

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-provenance-dark.png">
    <img src=".github/assets/geolens-provenance.png" alt="Der Reiter „Quelle“ des Datensatzes USGS Earthquakes: aus dem USGS-ArcGIS-Dienst in eine eigene Kopie importiert, mit den Zeiten der letzten Aktualisierung und Prüfung, der Feature-Anzahl und den Markierungen Verfügbar, Aktuell und Keine Änderung" width="100%">
  </picture>
  <br>
  <sub>Erdbeben, aus dem USGS-Dienst importiert. GeoLens behält eine eigene Kopie und zeigt, wann es die Quelle zuletzt aktualisiert und geprüft hat und ob sie verfügbar, aktuell und unverändert ist.</sub>
</p>

Jeder Datensatz hält fest, wie er in den Katalog gelangt ist: aus welcher Datei, Tabelle, welchem
Dienst oder STAC-Element er stammt und wann er zuletzt aktualisiert wurde. Legen Sie fest, wie oft
ein Datensatz aktualisiert werden soll, und GeoLens markiert ihn als aktuell, fällig oder
überfällig. Bei Diensten und STAC-Quellen prüft es außerdem, ob die Quelle noch antwortet, und
meldet Schemaänderungen auf der Quellseite, bevor sie Ihre Karten erreichen. Fällt ein Dienst
weg, funktioniert der importierte Datensatz mit der Kopie von GeoLens weiter.

## Karten erstellen und teilen

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-matterhorn-terrain-dark.jpg">
    <img src=".github/assets/geolens-matterhorn-terrain.jpg" alt="Der GeoLens-Karteneditor stellt das Matterhorn als 3D-Gelände aus swissALTI3D-Lidar dar, mit beschrifteten Gipfeln, Kletterrouten, der Ebenenliste und einer Legende" width="100%">
  </picture>
  <br>
  <sub>Das Matterhorn als 3D-Gelände aus swissALTI3D-Lidar, mit Gipfeln und Kletterrouten aus OpenStreetMap.</sub>
</p>

- **Ebenen und Stile.** Punkt-, Symbol-, Heatmap-, Cluster-, Linien-, Pfeil-, Flächen-,
  3D-Extrusions-, Raster- und Schummerungsebenen mit datengesteuerten Stilen, Beschriftungen,
  Symbolen, Mustern, Filtern und Popups. Das Gelände stammt aus Ihren eigenen Höhenmodellen.
- **Analyse.** Puffer, Zentroid, Zuschneiden, Auflösen, räumliche Verknüpfung, Auswahl nach Lage,
  Messen und Verschneiden. Die meisten Operationen zeigen zuerst eine Vorschau auf der Karte, und
  jedes Ergebnis wird als neuer Datensatz gespeichert, im Editor oder über die CLI.
- **Teilen.** Öffentliche Links zeigen in Slack, Teams und sozialen Netzwerken Titel und Bild der
  jeweiligen Karte als Vorschau. Karten lassen sich mit privaten Einbettungstokens in andere
  Websites einbetten.
- **Alltagswerkzeuge.** Zeichnen, Legende, Messen, Kartenverlauf und Tastenkürzel, auf Englisch,
  Spanisch, Französisch, Deutsch oder in vereinfachtem Chinesisch, mit hellem und dunklem Design.

## Daten von überall nutzen

Jeder Vektordatensatz ist eine OGC-API-Features-Collection, der Katalog selbst ist OGC API Records
und STAC, und jede Ebene hat eine Kachel-URL. Probieren Sie es gegen die Demo aus, ohne
Installation und ohne Konto (der zweite Befehl nutzt `jq`):

```sh
# Search the catalog (OGC API Records)
curl "https://demo.getgeolens.com/api/collections/datasets/items?q=volcanic%20eruptions"

# Read the top match with a CQL2 filter (OGC API Features): eruptions of VEI 6 or larger
ID=$(curl -s "https://demo.getgeolens.com/api/collections/datasets/items?q=volcanic%20eruptions&limit=1" | jq -r '.features[0].id')
curl -G "https://demo.getgeolens.com/api/collections/$ID/items" \
  --data-urlencode "filter=vei >= 6" -d limit=3
```

Fügen Sie in QGIS `https://demo.getgeolens.com/api/` als WFS-/OGC-API-Features-Verbindung hinzu,
dann erscheinen die öffentlichen Datensätze als Ebenen; die
[QGIS-Anleitung](https://docs.getgeolens.com/guides/api/qgis/) beschreibt die Schritte.

<p align="center">
  <img src=".github/assets/geolens-qgis.png" alt="QGIS 4 mit der GeoLens-Demo als OGC-API-Features-Verbindung: Das Browser-Bedienfeld listet die Collections der Demo, und aktuelle Erdbeben, bedeutende Vulkanausbrüche, Plattengrenzen und Länder aus der Demo sind als Ebenen auf einer Weltkarte geladen" width="100%">
  <br>
  <sub>QGIS liest den Demokatalog über OGC API Features, ohne Plugin: aktuelle Erdbeben, Vulkanausbrüche und Plattengrenzen, alle von GeoLens bereitgestellt.</sub>
</p>

| Standard | Wo | Nutzbar mit |
|---|---|---|
| OGC API Features, mit CQL2-Filterung und Queryables | `/api/collections/{id}/items` | QGIS, ArcGIS, GDAL/OGR und andere OGC-API-Clients |
| OGC API Records | `/api/collections/datasets/items` | Katalogsuche aus anderen Portalen und Werkzeugen |
| STAC API 1.0 | `/api/stac/` | STAC-Clients wie pystac-client und STAC Browser |
| DCAT 3, DCAT-US 3.0 und GeoDCAT-AP als JSON-LD | `/api/datasets/dcat/`, `/api/datasets/dcat-us/3.0/`, `/api/datasets/geodcat-ap/` | Harvesting in nationale und EU-Open-Data-Portale |
| Vektorkacheln und COG-Rasterkacheln | eine Kachel-URL an jeder Ebene | MapLibre, OpenLayers, Leaflet |
| 3D Tiles und COPC | die Seite jedes 3D-Datensatzes | CesiumJS, QGIS, Potree |

Vektorkacheln lassen unterhalb von Zoomstufe 10 Attributspalten weg; hängen Sie
`cols=<column>,<column>` an eine Kachel-URL an, um bestimmte Spalten auf jeder Zoomstufe zu
behalten. Daten verlassen GeoLens als GeoJSON, Shapefile, GeoPackage, CSV oder FlatGeobuf mit
optionaler Umprojektion, als GeoParquet, als PMTiles-Archive für statisches Hosting oder als
Cloud-Optimized GeoTIFF.

Für Skripte und Automatisierung gibt es die `geolens`-CLI, die Dateien veröffentlicht und
Katalogmanifeste anwendet, aus der OpenAPI-Spezifikation erzeugte Python- und TypeScript-SDKs sowie
einen rein lesenden MCP-Server, mit dem KI-Agenten den Katalog durchsuchen und Features abfragen.
Die [Beispielgalerie](https://geolens-io.github.io/geolens-examples/) enthält lauffähigen Code für
MapLibre, Leaflet, OpenLayers, das ArcGIS Maps SDK, QGIS und DuckDB. Ihre rein lesenden Beispiele
laufen gegen die Demo, und die CI führt sie dort jede Woche erneut aus.

## KI, nur wenn Sie wollen

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/geolens-ask-ai-dark.png">
    <img src=".github/assets/geolens-ask-ai.png" alt="Der Bereich „KI fragen“ zum Datensatz Major Hurricane Tracks beantwortet „How many of these hurricanes made landfall?“ mit 119 von 202, einer Zähltabelle mit zwei Zeilen, einem Hinweis, wie die Spalte zum Landfall gelesen wurde, und der Schaltfläche „Im Editor öffnen“" width="100%">
  </picture>
  <br>
  <sub>„How many of these hurricanes made landfall?“ liefert die Zahl, eine Tabelle und die Annahme hinter der Antwort, dazu eine Schaltfläche, die das Ergebnis im Karteneditor öffnet.</sub>
</p>

GeoLens kann Fragen zu einem Datensatz beantworten, Karten anhand von Anfragen in normaler Sprache
bearbeiten, Metadaten entwerfen und in natürlicher Sprache suchen. Es funktioniert mit jedem
OpenAI-kompatiblen Endpunkt, auch mit einem lokalen Modellserver wie Ollama, oder mit Claude über
Anthropic, Microsoft Foundry, Amazon Bedrock oder Google Vertex AI. Alles bleibt ausgeschaltet,
bis ein Administrator einen Anbieter konfiguriert, und jeder Arbeitsablauf funktioniert auch ohne.

## Installation

Sie brauchen Docker Engine 24+ und Docker Compose v2. Eine frische Installation startet sechs
Container mit etwa 1,3 GB Arbeitsspeicher, auf linux/amd64 oder linux/arm64.

```sh
curl -fsSL https://getgeolens.com/install.sh | sh    # clone, generate secrets, start the stack
cd geolens
grep '^GEOLENS_ADMIN_PASSWORD=' .env                  # the generated admin password
```

Öffnen Sie dann http://localhost:8080 und melden Sie sich als `admin` an. Der Installer klont
GeoLens nach `./geolens`, schreibt `.env` mit erzeugten Geheimnissen und einem zufälligen
Admin-Passwort, lädt die vorgefertigten Images und startet den Stack in etwa einer Minute. Um das
Skript vor der Ausführung zu prüfen, laden Sie `install.sh` und `SHA256SUMS` aus demselben
[Release](https://github.com/geolens-io/geolens/releases) herunter und führen Sie
`sha256sum -c SHA256SUMS` aus (unter macOS `shasum -a 256 -c SHA256SUMS`).

Weitere Wege:

- **Aus dem Quellcode:** Klonen Sie das Repository und führen Sie `bash scripts/install.sh` aus.
  Das baut alle Images lokal und dauert beim ersten Mal 5-10 Minuten.
- **Vorgefertigte Images:** `ghcr.io/geolens-io/geolens-api` und `ghcr.io/geolens-io/geolens-frontend`.
  Das Tag `latest` verweist auf die neueste stabile Version.
- **Produktion:** Die [Installationsanleitung](https://docs.getgeolens.com/guides/quickstart/install/)
  behandelt Produktionseinstellungen und Fehlerbehebung, und es gibt Anleitungen für
  [verwaltete Cloud-Dienste](https://docs.getgeolens.com/guides/quickstart/cloud-deployment/).
  Docker Compose ist der unterstützte Weg; ein experimentelles, von der Community gepflegtes
  Helm-Chart liegt in
  [geolens-deployments](https://github.com/geolens-io/geolens-deployments).

Eine externe Datenbank muss PostgreSQL 15+ mit PostGIS, pgvector 0.5+, pg_trgm und unaccent sein.
Nach der Installation laufen Sicherungen standardmäßig täglich und wöchentlich, optional mit
externen Kopien auf S3. Für ein Upgrade führen Sie `./scripts/upgrade.sh` im Installationsverzeichnis
aus: Das Skript sichert die Datenbank, lädt die neuen Images und migriert hinter einer
Zustandsprüfung; [UPGRADING.md](UPGRADING.md) beschreibt die Rollback-Schritte. Die Admin-Seiten
zeigen Zustand, Nutzung, Jobs und das Audit-Log, und Prometheus-Metriken, Alarmregeln und ein
Grafana-Dashboard liegen im Repository. [RUNBOOK.md](RUNBOOK.md) behandelt Sicherungen,
Wiederherstellung, Monitoring und Störungsreaktion, und die
[Konfigurationsreferenz](https://docs.getgeolens.com/guides/quickstart/configuration/) listet
jede Einstellung auf.

## Ihr erster Datensatz

Veröffentlichen Sie die Beispieldatei von der Kommandozeile und lesen Sie sie dann so zurück, wie
es jeder OGC-API-Features-Client täte:

```sh
pip install geolens-cli                               # needs Python 3.11+
geolens login http://localhost:8080/api               # your admin username and password
geolens publish examples/manifests/first-catalog/city-parks.geojson --name "City Parks"
export GEOLENS_API_KEY="paste-your-api-key-here"      # create one on your Settings page
curl -H "X-Api-Key: $GEOLENS_API_KEY" \
  "http://localhost:8080/api/collections/<dataset-id>/items?limit=5"
```

`geolens publish` gibt die URL des neuen Datensatzes aus, die auf seine ID endet. Für einen
ganzen Katalog beschreiben Sie die Quellen in einem Manifest `geolens.yaml` und führen
`geolens apply` aus; [`examples/manifests/`](examples/manifests/) enthält Vorlagen, und die
[CLI-Anleitung](https://docs.getgeolens.com/guides/cli/) beschreibt das Schema.

So laden Sie die Karten und Datensätze der Demo in Ihre eigene Installation (das lädt öffentliche
offene Daten herunter):

```sh
pip install httpx
python scripts/seed-showcase.py --username admin \
  --password "$(grep '^GEOLENS_ADMIN_PASSWORD=' .env | cut -d= -f2-)"
```

Die [API-Referenz](https://docs.getgeolens.com/guides/api/) und die
[SDK-Anleitungen](https://docs.getgeolens.com/guides/sdk/) gehen weiter.

## Datenschutz von Grund auf

- **Keine Telemetrie.** Abgesehen von den Standard-Basiskartenkacheln und den entfernten Diensten
  und STAC-Quellen, die Ihre Nutzer selbst registrieren, stellt GeoLens nur für Funktionen
  ausgehende Verbindungen her, die ein Administrator aktiviert. [EGRESS.md](EGRESS.md) listet
  jede davon auf und erklärt den Betrieb ohne Internetzugang.
- **Ihre Daten bleiben auch ohne GeoLens lesbar.** Vektordatensätze sind gewöhnliche
  PostGIS-Tabellen in einem Schema `data` Ihrer Datenbank, Raster sind Cloud-Optimized GeoTIFFs in
  Ihrem eigenen Speicher (lokaler Datenträger, S3/MinIO oder Azure Blob), und der gesamte Katalog
  lässt sich über OGC API, STAC und DCAT exportieren.
- **Zugriffskontrolle.** Lokale Konten oder Anmeldung per OAuth 2.0/OIDC (Google, Microsoft, GitHub
  oder ein generischer Anbieter), Rollen, Berechtigungen je Datensatz, API-Schlüssel je Benutzer
  und ein Audit-Log administrativer Aktionen. Die Selbstregistrierung ist standardmäßig
  deaktiviert.
- **Dauerhaft frei.** Alles in diesem Repository steht unter Apache 2.0, und hier veröffentlichte
  Funktionen bleiben frei. [EDITIONS.md](EDITIONS.md) beschreibt den optionalen bezahlten Support
  und die Erweiterungen.

## Bekannte Einschränkungen

- Eine PostgreSQL-Instanz, ohne integrierte Hochverfügbarkeit oder Clusterbildung.
- Eine Organisation pro Bereitstellung.
- Die Geländedarstellung setzt Höhenwerte in Metern voraus; andere vertikale Einheiten erscheinen
  überhöht.
- Die Endpunkte für OGC API, STAC und Kacheln folgen ihren Spezifikationen, aber die eigene
  REST-API von GeoLens kann sich zwischen Minor-Versionen noch ändern. Der
  [CHANGELOG](CHANGELOG.md) listet Vertragsänderungen auf, und bei einer inkompatiblen Änderung
  bleibt die alte Form mindestens eine weitere Minor-Version funktionsfähig.

## Mitwirken

Fehlerberichte, Korrekturen, Übersetzungen und Dokumentation sind willkommen.
[CONTRIBUTING](.github/CONTRIBUTING.md) erklärt die Entwicklungsumgebung (`make dev-init`, dann
`make dev`), die Tests, die jede Änderung braucht, und das DCO-Sign-off für Commits.
[ARCHITECTURE](.github/ARCHITECTURE.md) zeigt die Dienste und den Code, und die
[Roadmap](https://docs.getgeolens.com/roadmap/) zeigt, was geplant ist.

Fragen und Ideen gehören in die [GitHub Discussions](https://github.com/geolens-io/geolens/discussions),
Fehler in die [Issues](https://github.com/geolens-io/geolens/issues), und [SUPPORT.md](SUPPORT.md)
nennt weitere Anlaufstellen. Melden Sie Sicherheitsprobleme privat, wie in
[SECURITY.md](.github/SECURITY.md) beschrieben.

## Lizenz

GeoLens steht unter der [Apache License 2.0](LICENSE). Name, Logo und Markenmaterialien von
GeoLens fallen nicht unter diese Lizenz; siehe [TRADEMARKS.md](TRADEMARKS.md). Quellenangaben zu
Beispieldaten stehen in [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md).

Projektrichtlinien: [Editionen](EDITIONS.md) · [Governance](GOVERNANCE.md) · [Maintainer](MAINTAINERS.md) · [Sicherheit](.github/SECURITY.md) · [Release-Prozess](RELEASE.md) · [ausgehender Datenverkehr &amp; Air-Gap](EGRESS.md)
