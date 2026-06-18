"""GeoDCAT-AP 2.0.0 JSON-LD serialization for GeoLens records.

GeoDCAT-AP is the geospatial profile of DCAT-AP (EU / INSPIRE). It extends
DCAT 3 with the geospatial and ISO 19115 / 19139 metadata GeoLens already
stores. This serializer produces plain-dict JSON-LD (no rdflib) consistent
with the W3C DCAT 3 serializer in ``app.standards.dcat.service`` — it reuses
that module's namespace context and language-URI mapping rather than
re-deriving model access.

References:
  - GeoDCAT-AP 2.0.0: https://semiceu.github.io/GeoDCAT-AP/releases/2.0.0/
  - ISO 19115 CI_RoleCode → DCAT-AP agent-role mapping (GeoDCAT-AP §responsible party)
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.standards.dcat.service import (
    DCAT_CONTEXT,
    _lang_to_uri,
)

logger = structlog.stdlib.get_logger(__name__)

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        Record,
        RecordContact,
        RecordDistribution,
    )

# GeoDCAT-AP extends the DCAT 3 context with the geospatial / EU namespaces it
# relies on (GeoSPARQL for geometry/CRS, ADMS for status, locn, prov, geodcat
# for the responsible-party role vocabulary).
GEODCAT_AP_CONTEXT: dict[str, str] = {
    **DCAT_CONTEXT,
    "adms": "http://www.w3.org/ns/adms#",
    "gsp": "http://www.opengis.net/ont/geosparql#",
    "locn": "http://www.w3.org/ns/locn#",
    "prov": "http://www.w3.org/ns/prov#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "geodcat": "http://data.europa.eu/930/",
}

# OGC EPSG CRS URI base — GeoDCAT-AP recommends referencing the reference
# system via an HTTP URI (here the OGC EPSG register).
_OGC_CRS_URI_BASE = "http://www.opengis.net/def/crs/EPSG/0/"

# ISO 19115 CI_RoleCode → the DCAT-AP / GeoDCAT-AP property used to attach the
# responsible party. GeoDCAT-AP maps a handful of roles to first-class DCAT-AP
# properties and the remainder to the ``geodcat:`` role vocabulary. Roles not
# listed here still surface as a generic ``dcat:contactPoint``.
_ROLE_TO_PROPERTY: dict[str, str] = {
    "pointOfContact": "dcat:contactPoint",
    "publisher": "dcterms:publisher",
    "author": "dcterms:creator",
    "originator": "dcterms:creator",
    "owner": "geodcat:custodian",
    "custodian": "geodcat:custodian",
    "distributor": "geodcat:distributor",
    "principalInvestigator": "geodcat:principalInvestigator",
    "processor": "geodcat:processor",
    "resourceProvider": "geodcat:resourceProvider",
    "user": "geodcat:user",
    "rightsHolder": "dcterms:rightsHolder",
    "contributor": "dcterms:contributor",
}

SERVICE_DISTRIBUTION_TYPES = {"api", "ogcService", "ogc_features", "vector_tiles"}


def record_to_geodcat_ap(
    dataset: Dataset,
    base_url: str,
    *,
    include_context: bool = True,
) -> dict:
    """Serialize a GeoLens dataset to GeoDCAT-AP 2.0.0 JSON-LD.

    Args:
        dataset: Dataset ORM object with the ``record`` relationship and its
            keywords/contacts/distributions eager-loaded.
        base_url: Absolute base URL (e.g. ``http://localhost:8000``).
        include_context: Include ``@context``. Set to False for entries nested
            inside a catalog feed to avoid duplicating the context.

    Returns:
        A plain dict suitable for JSON serialization as JSON-LD.
    """
    record = dataset.record
    result: dict = {}

    if include_context:
        result["@context"] = GEODCAT_AP_CONTEXT

    lang = getattr(record, "language", None) or "en"

    result["@type"] = "dcat:Dataset"
    result["@id"] = f"{base_url}/datasets/{dataset.id}"
    result["dcterms:identifier"] = str(dataset.id)
    result["dcterms:title"] = {"@value": record.title, "@language": lang}
    result["dcterms:language"] = _lang_to_uri(lang)

    if record.summary is not None:
        result["dcterms:description"] = {"@value": record.summary, "@language": lang}

    if record.created_at is not None:
        result["dcterms:issued"] = record.created_at.isoformat()

    if record.updated_at is not None:
        result["dcterms:modified"] = record.updated_at.isoformat()

    if record.keywords:
        result["dcat:keyword"] = [kw.keyword for kw in record.keywords if kw.keyword]

    # Publisher: prefer source_organization, then owner_org, else GeoLens.
    publisher_name = record.source_organization or record.owner_org or "GeoLens"
    result["dcterms:publisher"] = {"@type": "foaf:Agent", "foaf:name": publisher_name}

    if record.license is not None:
        result["dcterms:license"] = record.license

    # Lineage → provenance (GeoDCAT-AP: dcterms:provenance / prov:Activity).
    if record.lineage_summary is not None:
        result["dcterms:provenance"] = {
            "@type": "dcterms:ProvenanceStatement",
            "rdfs:label": {"@value": record.lineage_summary, "@language": lang},
        }

    # Maintenance / update frequency (ISO MD_MaintenanceFrequencyCode).
    if record.update_frequency is not None:
        result["dcterms:accrualPeriodicity"] = record.update_frequency

    # Constraints. GeoDCAT-AP maps ISO access/use constraints to
    # dcterms:accessRights and dcterms:rights respectively (free text here).
    if record.access_constraints is not None:
        result["dcterms:accessRights"] = {
            "@type": "dcterms:RightsStatement",
            "rdfs:label": record.access_constraints,
        }
    if record.usage_constraints is not None:
        result["dcterms:rights"] = {
            "@type": "dcterms:RightsStatement",
            "rdfs:label": record.usage_constraints,
        }

    # Reference system / CRS → dcterms:conformsTo with an OGC EPSG URI.
    crs_uri = _crs_uri(dataset)
    if crs_uri is not None:
        result["dcterms:conformsTo"] = {"@id": crs_uri}

    # Responsible parties by CI_RoleCode (does NOT fabricate missing contacts).
    _apply_responsible_parties(result, record.contacts)

    if record.distributions:
        result["dcat:distribution"] = [
            _distribution_to_geodcat_ap(d, base_url, record=record)
            for d in record.distributions
        ]

    # Temporal extent.
    if record.temporal_start or record.temporal_end:
        temporal: dict = {"@type": "dcterms:PeriodOfTime"}
        if record.temporal_start:
            temporal["dcat:startDate"] = record.temporal_start.isoformat()
        if record.temporal_end:
            temporal["dcat:endDate"] = record.temporal_end.isoformat()
        result["dcterms:temporal"] = temporal

    # Spatial extent → dcterms:Location with a GeoSPARQL WKT geometry, the
    # GeoDCAT-AP-recommended carrier for the bounding geometry.
    spatial = _spatial_to_geodcat_ap(record)
    if spatial is not None:
        result["dcterms:spatial"] = spatial

    # Theme categories (ISO topic categories) → dcat:theme skos:Concept.
    if record.theme_category:
        result["dcat:theme"] = [
            {
                "@type": "skos:Concept",
                "skos:prefLabel": {"@value": theme, "@language": lang},
            }
            for theme in record.theme_category
        ]

    return {k: v for k, v in result.items() if v is not None}


def catalog_to_geodcat_ap(datasets: list[Dataset], base_url: str) -> dict:
    """Serialize a list of visible datasets to a GeoDCAT-AP Catalog JSON-LD dict.

    Args:
        datasets: Dataset ORM objects with record relationships loaded.
        base_url: Absolute base URL.

    Returns:
        A GeoDCAT-AP Catalog dict with nested dataset entries (no per-entry
        ``@context``).
    """
    return {
        "@context": GEODCAT_AP_CONTEXT,
        "@type": "dcat:Catalog",
        "@id": f"{base_url}/datasets/geodcat-ap",
        "dcterms:title": {
            "@value": "GeoLens Dataset Catalog",
            "@language": "en",
        },
        "dcterms:description": {
            "@value": "Geospatial dataset catalog managed by GeoLens",
            "@language": "en",
        },
        "dcterms:issued": datetime.now(timezone.utc).isoformat(),
        "dcterms:language": {
            "@id": "http://publications.europa.eu/resource/authority/language/ENG"
        },
        "dcterms:publisher": {
            "@type": "foaf:Agent",
            "foaf:name": "GeoLens",
        },
        "dcat:dataset": [
            record_to_geodcat_ap(ds, base_url, include_context=False) for ds in datasets
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_responsible_parties(result: dict, contacts: list[RecordContact]) -> None:
    """Attach contacts to result keyed by their CI_RoleCode → DCAT-AP property.

    Multiple contacts with the same target property are collected into a list.
    Does not fabricate contact metadata: a contact with neither name nor
    organization is skipped entirely.
    """
    grouped: dict[str, list[dict]] = {}
    for contact in contacts:
        agent = _agent_from_contact(contact)
        if agent is None:
            continue
        prop = _ROLE_TO_PROPERTY.get(contact.role or "", "dcat:contactPoint")
        grouped.setdefault(prop, []).append(agent)

    for prop, agents in grouped.items():
        if prop == "dcat:contactPoint":
            result[prop] = [_to_vcard(a) for a in agents]
        else:
            result[prop] = agents if len(agents) > 1 else agents[0]


def _agent_from_contact(contact: RecordContact) -> dict | None:
    """Build a foaf:Agent dict, or None when there is nothing to serialize."""
    name = contact.name or contact.organization
    if name is None:
        return None
    agent: dict = {"@type": "foaf:Agent", "foaf:name": name}
    if contact.email is not None:
        agent["foaf:mbox"] = _mailto(contact.email)
    if contact.organization is not None and contact.organization != name:
        agent["foaf:member"] = contact.organization
    return agent


def _to_vcard(agent: dict) -> dict:
    """Render a foaf:Agent dict as a vcard:Kind for dcat:contactPoint."""
    vcard: dict = {"@type": "vcard:Kind", "vcard:fn": agent["foaf:name"]}
    if "foaf:mbox" in agent:
        vcard["vcard:hasEmail"] = agent["foaf:mbox"]
    if "foaf:member" in agent:
        vcard["vcard:organization-name"] = agent["foaf:member"]
    return vcard


def _distribution_to_geodcat_ap(
    dist: RecordDistribution,
    base_url: str,
    *,
    record: Record,
) -> dict:
    """Serialize a RecordDistribution to a dcat:Distribution dict."""
    url = _absolute_url(dist.url, base_url)
    result: dict = {"@type": "dcat:Distribution", "dcat:accessURL": {"@id": url}}

    if dist.title is not None:
        result["dcterms:title"] = dist.title
    if dist.description is not None:
        result["dcterms:description"] = dist.description
    if dist.distribution_type == "download":
        result["dcat:downloadURL"] = {"@id": url}
    if dist.media_type is not None:
        result["dcat:mediaType"] = dist.media_type
    if dist.format is not None:
        result["dcterms:format"] = dist.format
    if record.license is not None:
        result["dcterms:license"] = {"@id": record.license}

    if dist.distribution_type in SERVICE_DISTRIBUTION_TYPES:
        result["dcat:accessService"] = {
            "@type": "dcat:DataService",
            "dcterms:title": dist.title or "GeoLens data service",
            "dcat:endpointURL": {"@id": url},
        }

    return {k: v for k, v in result.items() if v is not None}


def _spatial_to_geodcat_ap(record: Record) -> dict | None:
    """Serialize the spatial extent as a dcterms:Location with GeoSPARQL WKT."""
    if record.spatial_extent is None:
        return None
    try:
        from geoalchemy2.shape import to_shape

        min_x, min_y, max_x, max_y = to_shape(record.spatial_extent).bounds
    except Exception:  # broad: geoalchemy/shapely errors degrade to no spatial
        logger.debug(
            "GeoDCAT-AP spatial extent serialization failed",
            record_id=str(record.id),
        )
        return None

    wkt = (
        f"POLYGON(({min_x} {min_y}, "
        f"{min_x} {max_y}, "
        f"{max_x} {max_y}, "
        f"{max_x} {min_y}, "
        f"{min_x} {min_y}))"
    )
    return {
        "@type": "dcterms:Location",
        "dcat:bbox": {
            "@type": "gsp:wktLiteral",
            "@value": f"<http://www.opengis.net/def/crs/OGC/1.3/CRS84> {wkt}",
        },
    }


def _crs_uri(dataset: Dataset) -> str | None:
    """Build an OGC EPSG CRS URI from the dataset SRID, if present."""
    srid = dataset.srid or dataset.original_srid
    if srid is None:
        return None
    return f"{_OGC_CRS_URI_BASE}{srid}"


def _mailto(value: str) -> str:
    if value.startswith("mailto:"):
        return value
    return f"mailto:{value}"


def _absolute_url(value: str, base_url: str) -> str:
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"{base_url}{value}"
    return f"{base_url}/{value}"
