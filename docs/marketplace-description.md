# AWS Marketplace Product Description

## GeoLens -- Self-Hosted Geospatial Data Catalog

Find any dataset in your catalog in seconds. GeoLens is a self-hosted, database-first geospatial data catalog that gives GIS teams and data engineers a single place to store, search, preview, and share spatial data -- all within your own infrastructure.

Upload datasets in any common format (Shapefile, GeoJSON, GeoPackage, CSV, GeoTIFF, XLSX) and GeoLens automatically ingests them into PostGIS with spatial indexing, metadata extraction, and coordinate system detection. Full-text and semantic search let users discover datasets by name, description, or natural language queries. Every dataset gets an interactive map preview powered by built-in vector tile serving, so users can visually verify data before downloading.

GeoLens includes AI-assisted map building that turns natural language prompts into styled, multi-layer maps. Built-in OGC API compliance (Features and Tiles) lets external tools connect directly to your catalog. Secure sharing with embed tokens and domain locking makes it safe to publish interactive maps to external audiences. When users need data out, multi-format export supports GeoJSON, Shapefile, GeoPackage, and CSV.

**Key capabilities:**

- PostGIS-native storage with automatic spatial indexing
- Full-text and semantic search across dataset metadata
- Interactive map preview with vector tile serving
- AI-assisted map building from natural language
- OGC API compliance (Features, Tiles)
- Secure sharing with embed tokens and domain locking
- Multi-format export (GeoJSON, Shapefile, GeoPackage, CSV)
- Role-based access control with admin panel

**Deployment:** Runs on a single EC2 instance via the included AMI. Launch, configure a few environment variables, and your catalog is ready. No external dependencies beyond the instance itself.

**Your data stays in your infrastructure.** Unlike SaaS platforms, GeoLens runs entirely within your AWS account. Data never leaves your VPC.
