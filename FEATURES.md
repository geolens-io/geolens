# GeoLens Features

GeoLens is an on-premises spatial data catalog that lets teams search, preview, and share geospatial datasets from a single browser interface. Built on PostGIS and deployed with Docker Compose, it combines full-text and semantic search, interactive map visualization, OGC-compliant APIs, and an AI assistant into a self-hosted platform for GIS analysts, data engineers, and IT administrators.

## Search and Discovery

Full-text search with pgvector semantic matching surfaces relevant datasets by meaning, not just keywords. Faceted filters narrow results by record type, keywords, coordinate reference system, source organization, and temporal extent. Type toggle badges with live counts let users switch between vector, raster, VRT, and collection results instantly. Search ranking boosts, saved searches, and related dataset discovery round out the experience. The catalog conforms to OGC API Records Part 1.

## Data Ingestion

Upload Shapefiles, GeoJSON, GeoPackage, CSV, and Excel files or import from WFS and ArcGIS Feature Service endpoints (with authentication support). Raster files are auto-converted to Cloud-Optimized GeoTIFFs, and compatible rasters can be combined into VRT mosaics. Non-spatial tables (CSV/XLSX) are supported as first-class catalog records. Every import shows a pre-upload preview with schema, CRS, and sample rows. Re-uploading a dataset presents a schema diff and performs an atomic swap, preserving version history. A Natural Earth seed script provides instant demo data.

## Map Visualization

Vector datasets render as tiles via PostGIS ST_AsMVT; raster and VRT layers serve through Titiler. Feature popups display attribute data on click. Administrators configure basemap presets (including custom XYZ/TMS URLs) with automatic dark/light theme switching. Zoom-to-extent and configurable default map center and zoom round out the viewing experience.

## Map Builder

Create and save interactive maps with drag-and-drop layer ordering, per-layer opacity, and layer rename. Style vector layers with fill, stroke, and circle symbology using a color picker, or apply data-driven categorical and graduated styles with Brewer color ramps. Add attribute labels with font, color, and halo controls. Build visual layer filters without writing code. Raster and VRT layers are fully supported. Copy or fork any map with lineage tracking, toggle legend visibility per layer, and resize the sidebar to suit your workflow.

## AI Assistant

Generate maps from a natural-language prompt or refine existing maps through conversational chat. Mention layers with @ and use slash commands for common operations. The assistant handles style changes, filters, labels, and adding or removing layers. Text-to-SQL spatial queries produce ephemeral result layers for ad-hoc analysis. Multiple LLM providers are supported (Anthropic, OpenAI-compatible endpoints for Ollama, Groq, and Together). Administrators can enable or disable AI features globally.

## Layer Editing

Create empty layers by geometry type, then draw points, lines, polygons, rectangles, circles, or freehand shapes directly on the map. Move features, edit vertices, or delete geometries. Edit attribute values and modify the layer schema by adding or removing columns. Vertex snapping and undo support keep editing efficient.

## Standards and Interoperability

OGC API Records Part 1 for catalog discovery. OGC API Features with bbox and property filtering, paginated GeoJSON responses, and CQL2 filtering (text and JSON encodings). STAC 1.1 export produces catalog, item, collection, and search endpoints. DCAT metadata and queryables/schema introspection endpoints are included.

## Collections and Organization

Group datasets into flat, multi-membership collections. Browse collections with cards and search, each with a landing page. A publication lifecycle (draft, ready, internal, published) controls visibility. Foreign key relationships are auto-detected, surfacing related records in a dedicated panel.

## Export and Sharing

Export datasets as GeoJSON, Shapefile, GeoPackage, or CSV; download rasters as COGs. Create secure share links with expiration dates. Embed interactive map viewers on external sites with domain restrictions.

## Administration

Manage users with an approval workflow and role-based access control (viewer, editor, admin) with granular per-role permission toggles. Issue and revoke API keys. Configure OAuth/OIDC providers (Google, Microsoft, generic) with PKCE and group-to-role mapping. Review audit logs with full change history. Export and import configuration with dry-run diff preview. Monitor storage, background jobs, and infrastructure health from the admin dashboard.

## Security

JWT authentication with refresh token rotation. Magic byte file validation and zip bomb detection on upload. SSRF protection on service imports. Signed tile URLs. SQL sandbox with AST validation for AI queries. Rate limiting, Prometheus metrics, and Trivy CI scanning. Automated S3 backups with retention policies and a Valkey/Redis circuit breaker for cache resilience.

## Deployment

A single `docker compose up` launches six services: database (PostGIS), migration runner, API, background worker, Titiler (raster tiles), and frontend. Storage is provider-agnostic (local filesystem or S3 with presigned uploads). Caching supports in-memory or Redis backends. The frontend offers dark and light themes, i18n support, route-based code splitting, and WCAG AA accessibility (touch targets, keyboard navigation, screen reader landmarks). Structured JSON logging with correlation IDs provides production observability.
