---
phase: 230
plan: 03
type: execute
wave: 2
depends_on:
  - 230-01
files_modified:
  - backend/app/modules/catalog/maps/service.py
  - backend/app/modules/catalog/search/service.py
autonomous: true
requirements:
  - CATPORT-02
  - CATPORT-03
  - CATPORT-05
must_haves:
  truths:
    - maps service preserves existing user edits for advanced sharing gates
    - maps service obtains RasterAsset through CatalogPort
    - search service obtains RecordEmbedding, has_embeddings, and generate_embedding through CatalogPort
    - Semantic search behavior and SQLAlchemy query composition remain unchanged
---

<objective>
Migrate ORM/query-heavy catalog imports to CatalogPort, including the dirty maps service file.
</objective>

<tasks>
<task type="auto">
  <name>Migrate maps RasterAsset usage</name>
  <files>backend/app/modules/catalog/maps/service.py</files>
  <action>Preserve the existing uncommitted sharing-gate edits. Remove the top-of-file RasterAsset import and use get_catalog_port().raster_asset_orm_class() where SQLAlchemy query composition needs the class.</action>
  <verify>python -m py_compile backend/app/modules/catalog/maps/service.py</verify>
  <done>maps/service.py has no top-of-file app.processing import and advanced sharing edits remain intact.</done>
</task>

<task type="auto">
  <name>Migrate search embedding usage</name>
  <files>backend/app/modules/catalog/search/service.py</files>
  <action>Remove top-of-file embedding imports. Use CatalogPort for has_embeddings(), generate_embedding(), and RecordEmbedding ORM class inside semantic/hybrid search helpers.</action>
  <verify>python -m py_compile backend/app/modules/catalog/search/service.py</verify>
  <done>search/service.py has no top-of-file app.processing import and semantic search still composes the same query.</done>
</task>
</tasks>

<verification>
git grep -n -E '^(from|import) (backend\.)?app\.processing' -- backend/app/modules/catalog/
</verification>

