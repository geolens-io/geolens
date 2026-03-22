Here’s the spec I’d use for GeoLens Metadata Profile v0.1.

The core call still stands: make ISO 19115-1 your canonical metadata model, use ISO 19115-3 only when you need XML interchange, expose catalog records through OGC API - Records, map to DCAT 3 for broader web/data-portal interoperability, and treat STAC as a later profile for raster/EO-style asset catalogs rather than the universal model for everything. FGDC guidance today still points users toward ISO metadata as the preferred direction, while CSDGM remains mainly a legacy compatibility concern.

1) Recommended standards posture for GeoLens

Canonical internal model

ISO 19115-1 for core resource metadata

ISO 19157-1 concepts for quality reporting

ISO 19110 concepts for feature/attribute cataloging

OGC API - Records as the external search/browse API

DCAT 3 as an export/interchange view

STAC as an optional later profile for imagery, rasters, COGs, and spatiotemporal assets

What not to do

Do not make users fill out raw ISO forms.

Do not make STAC your only model unless GeoLens becomes primarily an EO/raster asset platform.

Do not center on FGDC CSDGM unless your sales wedge is legacy federal metadata modernization.

2) Product rule: simple UI, standards-backed model

GeoLens should use a two-layer model:

GeoLens Core Profile
A concise, user-friendly metadata form for normal users.

Standards Mapping Layer
A backend crosswalk that maps GeoLens fields to ISO 19115-1 / OGC API - Records / DCAT 3, with optional STAC export later.

That gives you a product people will actually use, while preserving standards-grade interoperability underneath. FGDC explicitly notes ISO’s broader applicability and flexibility, including fewer mandatory elements and support for more resource types and relationships than older CSDGM workflows.

GeoLens Metadata Profile v0.1
3) Resource types supported in MVP

I would support these resource_type values from the start:

dataset

service

collection

map

Why:

ISO 19115-1 is applicable to datasets and services.

OGC API - Records treats a record as metadata about many kinds of resources, including data collections, APIs, services, processes, styles, and more.

Since GeoLens now has a Maps feature, map should be a first-class catalog resource in your own model, even though it is your product-specific extension.

4) Required fields for every GeoLens record

These should be the minimum required fields.

GeoLens field	Required	Description	Primary source
id	Yes	Stable UUID	Internal
resource_type	Yes	dataset / service / collection / map	Internal
title	Yes	Human-readable name	ISO / DCAT / OGC Records
summary	Yes	1–3 paragraph abstract	ISO / DCAT / OGC Records
owner_org	Yes	Owning organization/team	ISO / DCAT
contact_name	Yes	Responsible party	ISO
contact_email	Yes	Contact method	ISO / DCAT
keywords	Yes	Tags for discovery	ISO / DCAT / OGC Records
spatial_extent_bbox	Yes	West/South/East/North	ISO / DCAT / STAC-compatible concept
temporal_extent_start	No*	Start of vintage or coverage	ISO / DCAT
temporal_extent_end	No*	End of vintage or coverage	ISO / DCAT
crs	Yes for spatial data	EPSG code / CRS identifier	ISO
geometry_type	Yes for vector	Point/Line/Polygon/Mixed	Internal / ISO-aligned
format	Yes	gpkg / shapefile / csv / parquet / pmtiles / tif etc.	DCAT / ISO
distribution_links	Yes	Download/API links	ISO / DCAT
license	Yes	License / use constraints	ISO / DCAT / STAC Collection concept
access_level	Yes	public / restricted / private	Internal
lineage_summary	Yes	Source + process summary	ISO
update_frequency	No but recommended	daily / monthly / annual / irregular	DCAT / ISO-aligned
published_at	Yes	When record became visible	Internal / DCAT
updated_at	Yes	Last metadata update	Internal / DCAT
record_status	Yes	draft / published / deprecated / superseded	Internal

* Temporal extent is mandatory only for time-aware datasets, imagery, feeds, or map products.

5) Strongly recommended fields for datasets

These should be “recommended,” not required, in MVP:

GeoLens field	Why it matters
feature_count	Fast fit-for-use signal
attribute_schema	Human + machine-readable field list
primary_geometry_column	Needed for downstream APIs/analysis
original_filename	Provenance
source_system	Provenance / trust
source_url	Lineage / citation
data_vintage_start / data_vintage_end	Better than one vague “date”
scale_or_resolution	Essential for map fitness
place_names_covered	Great for search relevance
theme_category	Easier navigation and faceting
quality_statement	Human-readable quality note
quality_score	Product convenience field, not standards truth
usage_constraints	Clarifies internal restrictions
sensitivity_classification	Enterprise need
retention_policy	Governance
supersedes_record_id	Lifecycle tracking
version	Versioned metadata + data
preview_config	Saved preview defaults
6) Auto-extracted fields vs user-authored fields

This matters a lot for UX.

Auto-extract during ingest

geometry type

CRS / SRID

bbox / extent

feature count

raster dimensions / band count

file format

column names and types

null rates / distinct counts / sample values

estimated scale/resolution where feasible

checksum / fingerprint

upload time

detected language

detected place names from attributes where confidence is high

User-authored or user-reviewed

title

summary

owner / steward

contact

keywords

license

lineage summary

update frequency

sensitivity / access classification

quality statement

thematic categorization

Hybrid / AI-assisted

summary draft

keyword suggestions

inferred topic/theme

candidate lineage summary

candidate place coverage

candidate quality flags

That hybrid approach matches the standards reality: ISO quality and lineage are important, but the product should prefill what is objectively derivable and ask humans to confirm the interpretive parts. ISO 19157-1 is about describing quality components and reporting quality, not magically inventing minimum quality thresholds for you.

7) Feature/attribute metadata: use ISO 19110 ideas

Your attribute_schema should not just be raw column names. For each field, store:

name

title

description

data_type

nullable

units

domain_type (free_text, coded_value, range, foreign_key)

allowed_values or code list

example_values

is_identifier

is_time_field

is_geometry_related

semantic_role (name, status, classification, measure, etc.)

This is where ISO 19110 helps. It is specifically about feature cataloguing and feature types, which is very relevant for a PostGIS-native catalog that wants good schema understanding, search, and AI assistance.

8) GeoLens Core JSON shape

This is the internal normalized record I would use:

{
  "id": "uuid",
  "resource_type": "dataset",
  "title": "NHD Lakes and Reservoirs",
  "summary": "Polygon features representing lakes and reservoirs...",
  "record_status": "published",
  "owner_org": "USGS",
  "contacts": [
    {
      "role": "pointOfContact",
      "name": "Data Steward",
      "email": "steward@example.org"
    }
  ],
  "keywords": ["hydrography", "lakes", "surface water", "North America"],
  "theme_category": ["inlandWaters"],
  "spatial": {
    "bbox": [-168.0, 5.0, -52.0, 83.0],
    "crs": "EPSG:4326",
    "place_names_covered": ["North America", "United States", "Canada"]
  },
  "temporal": {
    "vintage_start": "2024-01-01",
    "vintage_end": "2024-12-31",
    "update_frequency": "annual"
  },
  "data_characteristics": {
    "geometry_type": "Polygon",
    "feature_count": 128493,
    "format": "GeoPackage",
    "scale_or_resolution": "1:24,000"
  },
  "lineage": {
    "source_system": "USGS NHD",
    "source_url": "https://example.org",
    "lineage_summary": "Derived from NHD polygon hydrography..."
  },
  "quality": {
    "quality_statement": "Suitable for regional analysis; not surveyed for cadastral use.",
    "quality_score": 0.84,
    "validation_flags": ["missing_vertical_accuracy"]
  },
  "governance": {
    "license": "Public Domain",
    "usage_constraints": null,
    "access_level": "public",
    "sensitivity_classification": "low"
  },
  "distribution": [
    {
      "type": "download",
      "format": "GeoPackage",
      "url": "https://..."
    },
    {
      "type": "ogc_features",
      "format": "OGC API - Features",
      "url": "https://..."
    }
  ],
  "schema": {
    "attributes": []
  },
  "provenance": {
    "version": "2026.02",
    "checksum": "sha256:...",
    "published_at": "2026-02-28T12:00:00Z",
    "updated_at": "2026-02-28T12:00:00Z"
  }
}
9) GeoLens field groups in the UI

Do not show users a 60-field standards form. Use these tabs/sections:

Overview

title

summary

keywords

owner

status

Coverage

map extent

CRS

temporal coverage

place coverage

Structure

geometry type

feature count

fields / schema

format

Source & Quality

lineage summary

source org / URL

update frequency

quality statement

validation warnings

Access & Sharing

license

visibility

restrictions

API and download links

Advanced / Standards

full ISO-aligned fields

XML export

DCAT export

future STAC profile toggle

That keeps the product usable while still supporting standards exports.

10) Validation rules for MVP

I would implement three validation levels.

A. Hard validation

Record cannot be published unless:

title present

summary present

at least one contact

at least one keyword

license/access fields present

spatial bbox present for spatial data

CRS present for spatial data

at least one distribution/API link or internal access path

lineage summary present

B. Soft validation

Record can publish, but gets warnings:

no temporal extent

no update frequency

no quality statement

no place names

attribute descriptions missing

no source URL

no version identifier

C. Quality scoring

Use a weighted completeness score, but keep it transparent:

discovery completeness: 30%

spatial/temporal completeness: 20%

governance completeness: 20%

lineage completeness: 15%

quality completeness: 15%

Important: your quality_score should be a GeoLens convenience score, not a claim of formal ISO data quality conformance. ISO 19157-1 is about reporting and structuring quality information; your score is a product heuristic layered on top.

11) Standards crosswalk
GeoLens → ISO 19115-1

Best-fit mapping:

title → citation/title

summary → abstract

keywords → descriptive keywords

contacts → responsible party

bbox / temporal extent → extent

crs → reference system info

distribution_links → distribution / transfer options

lineage_summary → lineage

license / constraints → resource constraints

update_frequency → maintenance information

resource_type → hierarchy level / resource scope

GeoLens → ISO 19157-1

quality_statement

validation_flags

specific quality measures and reports later

conformance notes

known limitations

GeoLens → ISO 19110

schema.attributes[*]

feature-type descriptions

code lists / domains

semantic classification of fields

GeoLens → OGC API - Records

record title, description, keywords, links, extents, contacts, identifiers, and resource links exposed through record endpoints and searchable collections. OGC API - Records Part 1 is explicitly designed for browsing/searching one or more record collections on the web.

GeoLens → DCAT 3

record → dcat:Dataset or dcat:DataService

downloads/APIs → distributions

publisher/contact/license/themes/keywords

temporal/spatial coverage

version / issued / modified dates
DCAT 3 is meant to improve interoperability across web-published catalogs and federated search.

GeoLens → STAC later

Only for raster/EO/time-aware asset catalogs:

record → STAC Collection

items/assets for scenes/files/tiles

bbox/time/license/providers/summaries

asset links to COGs, thumbnails, derived assets
STAC is intentionally flexible and extensible, and centers Items, Catalogs, Collections, and an API search interface.

12) Database implementation guidance for GeoLens

For your current GeoLens database direction, I would add or normalize these metadata tables:

catalog.metadata_records

Canonical top-level record.

Core columns:

id

resource_type

title

summary

owner_org

record_status

license

access_level

published_at

updated_at

search_vector

bbox

time_start

time_end

crs

lineage_summary

quality_statement

quality_score

standards_profile (geolens-core-v1)

source_dataset_id nullable

catalog.metadata_contacts

record_id

role

name

email

organization

catalog.metadata_keywords

record_id

keyword

scheme nullable

catalog.metadata_distributions

record_id

distribution_type

format

url

media_type

is_primary

catalog.metadata_attributes

record_id

field_name

title

description

data_type

units

domain_json

semantic_role

example_values_json

catalog.metadata_quality_measures

record_id

measure_name

measure_value

measure_unit

method

scope

reported_at

catalog.metadata_exports

record_id

export_format (iso19115-3-xml, dcat-jsonld, later stac-json)

rendered_payload

schema_version

generated_at

This keeps your internal schema stable while allowing multiple outward standards views.

13) MVP export targets

For MVP, I would ship exactly these exports:

GeoLens JSON as the canonical internal/public app representation

OGC API - Records JSON for catalog discovery

DCAT 3 JSON-LD for federation/open-data compatibility

ISO 19115-3 XML only if a buyer explicitly needs standards XML exchange

I would defer STAC export until you add serious raster/imagery support. That is because STAC is centered on Items, Collections, assets, and time/spatial search, which is powerful but more specialized than your current general-purpose GIS catalog need.