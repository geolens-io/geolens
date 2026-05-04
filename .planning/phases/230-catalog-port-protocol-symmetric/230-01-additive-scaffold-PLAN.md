---
phase: 230
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/core/catalog_port.py
  - backend/app/platform/extensions/defaults.py
  - backend/app/platform/extensions/__init__.py
autonomous: true
requirements:
  - CATPORT-01
  - CATPORT-05
must_haves:
  truths:
    - CatalogPort Protocol exists in backend/app/core/catalog_port.py
    - DefaultCatalogPort delegates to app.processing.* only through deferred imports inside method bodies
    - get_catalog_port() returns DefaultCatalogPort when no overlay registered
    - No catalog call sites are migrated in this plan
---

<objective>
Add the symmetric CatalogPort scaffold that catalog modules will use to reach processing-owned helpers, schemas, ORM classes, and task dispatchers without module-load imports.
</objective>

<context>
@.planning/phases/230-catalog-port-protocol-symmetric/230-CONTEXT.md
@.planning/phases/230-catalog-port-protocol-symmetric/230-RESEARCH.md
@backend/app/core/processing_port.py
@backend/app/platform/extensions/defaults.py
@backend/app/platform/extensions/__init__.py
</context>

<tasks>
<task type="auto">
  <name>Create CatalogPort Protocol</name>
  <files>backend/app/core/catalog_port.py</files>
  <action>Add a runtime-checkable Protocol with narrow methods and ORM/schema class accessors required by the current catalog import inventory. Keep core free of app.processing imports; use Any and forward-reference comments where concrete processing types live outside core.</action>
  <verify>python -m py_compile backend/app/core/catalog_port.py</verify>
  <done>CatalogPort imports without pulling processing modules into core.</done>
</task>

<task type="auto">
  <name>Add DefaultCatalogPort</name>
  <files>backend/app/platform/extensions/defaults.py</files>
  <action>Append DefaultCatalogPort methods that delegate to app.processing.* using deferred imports inside method bodies only. Return ORM/schema classes where callers need SQLAlchemy or FastAPI concrete classes.</action>
  <verify>python -m py_compile backend/app/platform/extensions/defaults.py</verify>
  <done>DefaultCatalogPort is instantiable and has no module-level app.processing imports.</done>
</task>

<task type="auto">
  <name>Add get_catalog_port accessor</name>
  <files>backend/app/platform/extensions/__init__.py</files>
  <action>Import DefaultCatalogPort, add TYPE_CHECKING import for CatalogPort, and expose a single-slot get_catalog_port() using registry key "catalog_port".</action>
  <verify>python -m py_compile backend/app/platform/extensions/__init__.py</verify>
  <done>get_catalog_port() returns DefaultCatalogPort when no overlay is registered.</done>
</task>
</tasks>

<verification>
python -m py_compile backend/app/core/catalog_port.py backend/app/platform/extensions/defaults.py backend/app/platform/extensions/__init__.py
</verification>

