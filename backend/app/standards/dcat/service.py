"""DCAT 3 JSON-LD serialization for GeoLens records.

Produces plain dict JSON-LD (no rdflib) per project decision.
W3C DCAT 3 Recommendation: https://www.w3.org/TR/vocab-dcat-3/
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import TYPE_CHECKING

logger = structlog.stdlib.get_logger(__name__)


if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        RecordContact,
        RecordDistribution,
    )

_LANG_URI_BASE = "http://publications.europa.eu/resource/authority/language/"

# ISO 639-1 → ISO 639-3 (uppercase) mapping used by the EU Authority Table.
# Covers all languages with ISO 639-1 codes that have entries in the
# EU Publications Office Named Authority Lists.
_LANG_URIS: dict[str, str] = {
    "aa": "AAR",
    "ab": "ABK",
    "af": "AFR",
    "ak": "AKA",
    "am": "AMH",
    "an": "ARG",
    "ar": "ARA",
    "as": "ASM",
    "av": "AVA",
    "ay": "AYM",
    "az": "AZE",
    "ba": "BAK",
    "be": "BEL",
    "bg": "BUL",
    "bh": "BIH",
    "bi": "BIS",
    "bm": "BAM",
    "bn": "BEN",
    "bo": "BOD",
    "br": "BRE",
    "bs": "BOS",
    "ca": "CAT",
    "ce": "CHE",
    "ch": "CHA",
    "co": "COS",
    "cr": "CRE",
    "cs": "CES",
    "cu": "CHU",
    "cv": "CHV",
    "cy": "CYM",
    "da": "DAN",
    "de": "DEU",
    "dv": "DIV",
    "dz": "DZO",
    "ee": "EWE",
    "el": "ELL",
    "en": "ENG",
    "eo": "EPO",
    "es": "SPA",
    "et": "EST",
    "eu": "EUS",
    "fa": "FAS",
    "ff": "FUL",
    "fi": "FIN",
    "fj": "FIJ",
    "fo": "FAO",
    "fr": "FRA",
    "fy": "FRY",
    "ga": "GLE",
    "gd": "GLA",
    "gl": "GLG",
    "gn": "GRN",
    "gu": "GUJ",
    "gv": "GLV",
    "ha": "HAU",
    "he": "HEB",
    "hi": "HIN",
    "ho": "HMO",
    "hr": "HRV",
    "ht": "HAT",
    "hu": "HUN",
    "hy": "HYE",
    "hz": "HER",
    "ia": "INA",
    "id": "IND",
    "ie": "ILE",
    "ig": "IBO",
    "ii": "III",
    "ik": "IPK",
    "io": "IDO",
    "is": "ISL",
    "it": "ITA",
    "iu": "IKU",
    "ja": "JPN",
    "jv": "JAV",
    "ka": "KAT",
    "kg": "KON",
    "ki": "KIK",
    "kj": "KUA",
    "kk": "KAZ",
    "kl": "KAL",
    "km": "KHM",
    "kn": "KAN",
    "ko": "KOR",
    "kr": "KAU",
    "ks": "KAS",
    "ku": "KUR",
    "kv": "KOM",
    "kw": "COR",
    "ky": "KIR",
    "la": "LAT",
    "lb": "LTZ",
    "lg": "LUG",
    "li": "LIM",
    "ln": "LIN",
    "lo": "LAO",
    "lt": "LIT",
    "lu": "LUB",
    "lv": "LAV",
    "mg": "MLG",
    "mh": "MAH",
    "mi": "MRI",
    "mk": "MKD",
    "ml": "MAL",
    "mn": "MON",
    "mr": "MAR",
    "ms": "MSA",
    "mt": "MLT",
    "my": "MYA",
    "na": "NAU",
    "nb": "NOB",
    "nd": "NDE",
    "ne": "NEP",
    "ng": "NDO",
    "nl": "NLD",
    "nn": "NNO",
    "no": "NOR",
    "nr": "NBL",
    "nv": "NAV",
    "ny": "NYA",
    "oc": "OCI",
    "oj": "OJI",
    "om": "ORM",
    "or": "ORI",
    "os": "OSS",
    "pa": "PAN",
    "pi": "PLI",
    "pl": "POL",
    "ps": "PUS",
    "pt": "POR",
    "qu": "QUE",
    "rm": "ROH",
    "rn": "RUN",
    "ro": "RON",
    "ru": "RUS",
    "rw": "KIN",
    "sa": "SAN",
    "sc": "SRD",
    "sd": "SND",
    "se": "SME",
    "sg": "SAG",
    "si": "SIN",
    "sk": "SLK",
    "sl": "SLV",
    "sm": "SMO",
    "sn": "SNA",
    "so": "SOM",
    "sq": "SQI",
    "sr": "SRP",
    "ss": "SSW",
    "st": "SOT",
    "su": "SUN",
    "sv": "SWE",
    "sw": "SWA",
    "ta": "TAM",
    "te": "TEL",
    "tg": "TGK",
    "th": "THA",
    "ti": "TIR",
    "tk": "TUK",
    "tl": "TGL",
    "tn": "TSN",
    "to": "TON",
    "tr": "TUR",
    "ts": "TSO",
    "tt": "TAT",
    "tw": "TWI",
    "ty": "TAH",
    "ug": "UIG",
    "uk": "UKR",
    "ur": "URD",
    "uz": "UZB",
    "ve": "VEN",
    "vi": "VIE",
    "vo": "VOL",
    "wa": "WLN",
    "wo": "WOL",
    "xh": "XHO",
    "yi": "YID",
    "yo": "YOR",
    "za": "ZHA",
    "zh": "ZHO",
    "zu": "ZUL",
}


def _lang_to_uri(code: str | None) -> dict:
    """Map an ISO 639-1 code to an EU vocabulary language URI object."""
    iso3 = _LANG_URIS.get(code or "en", "ENG")
    return {"@id": f"{_LANG_URI_BASE}{iso3}"}


DCAT_CONTEXT = {
    "dcat": "http://www.w3.org/ns/dcat#",
    "dcterms": "http://purl.org/dc/terms/",
    "dqv": "http://www.w3.org/ns/dqv#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "oa": "http://www.w3.org/ns/oa#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "vcard": "http://www.w3.org/2006/vcard/ns#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


def record_to_dcat(
    dataset: Dataset,
    base_url: str,
    *,
    include_context: bool = True,
) -> dict:
    """Serialize a Dataset (with loaded record relationships) to DCAT 3 JSON-LD.

    Args:
        dataset: Dataset ORM object with record relationship eager-loaded.
        base_url: Absolute base URL (e.g. ``http://localhost:8000``).
        include_context: Include ``@context`` in output. Set to False for
            individual entries within a catalog feed to avoid duplication.

    Returns:
        A plain dict suitable for JSON serialization as JSON-LD.
    """
    record = dataset.record
    result: dict = {}

    if include_context:
        result["@context"] = DCAT_CONTEXT

    lang = getattr(record, "language", None) or "en"

    result["@type"] = "dcat:Dataset"
    result["@id"] = f"{base_url}/datasets/{dataset.id}"
    result["dcterms:identifier"] = str(dataset.id)
    result["dcterms:title"] = {"@value": record.title, "@language": lang}

    # Per-record language
    result["dcterms:language"] = _lang_to_uri(lang)

    if record.summary is not None:
        result["dcterms:description"] = {"@value": record.summary, "@language": lang}

    if record.created_at is not None:
        result["dcterms:issued"] = record.created_at.isoformat()

    if record.updated_at is not None:
        result["dcterms:modified"] = record.updated_at.isoformat()

    if record.keywords:
        result["dcat:keyword"] = [kw.keyword for kw in record.keywords]

    # Publisher: use source_organization when available, else "GeoLens"
    publisher_name = record.source_organization or "GeoLens"
    result["dcterms:publisher"] = {"@type": "foaf:Agent", "foaf:name": publisher_name}

    if record.license is not None:
        result["dcterms:license"] = record.license

    if record.lineage_summary is not None:
        result["dcterms:provenance"] = {
            "@value": record.lineage_summary,
            "@language": lang,
        }

    if record.update_frequency is not None:
        result["dcterms:accrualPeriodicity"] = record.update_frequency

    if record.access_constraints is not None:
        result["dcterms:accessRights"] = record.access_constraints

    if dataset.quality_statement is not None:
        result["dqv:hasQualityAnnotation"] = {
            "@type": "dqv:QualityAnnotation",
            "oa:bodyValue": {"@value": dataset.quality_statement, "@language": lang},
        }

    if record.contacts:
        result["dcat:contactPoint"] = [_contact_to_dcat(c) for c in record.contacts]

    if record.distributions:
        result["dcat:distribution"] = [
            _distribution_to_dcat(d, base_url) for d in record.distributions
        ]

    # Temporal extent
    if record.temporal_start or record.temporal_end:
        temporal: dict = {"@type": "dcterms:PeriodOfTime"}
        if record.temporal_start:
            temporal["dcat:startDate"] = record.temporal_start.isoformat()
        if record.temporal_end:
            temporal["dcat:endDate"] = record.temporal_end.isoformat()
        result["dcterms:temporal"] = temporal

    # Spatial extent
    if record.spatial_extent:
        try:
            from geoalchemy2.shape import to_shape

            bounds = to_shape(record.spatial_extent).bounds
            result["dcterms:spatial"] = {
                "@type": "dcterms:Location",
                "dcat:bbox": (
                    f"POLYGON(({bounds[0]} {bounds[1]}, "
                    f"{bounds[0]} {bounds[3]}, "
                    f"{bounds[2]} {bounds[3]}, "
                    f"{bounds[2]} {bounds[1]}, "
                    f"{bounds[0]} {bounds[1]}))"
                ),
            }
        except Exception:  # broad: DCAT bbox serialize — geoalchemy/shapely errors degrade to no-spatial in catalog entry
            logger.debug(
                "DCAT spatial extent serialization failed", record_id=str(record.id)
            )

    # Theme categories
    if record.theme_category:
        result["dcat:theme"] = [
            {
                "@type": "skos:Concept",
                "skos:prefLabel": {"@value": theme, "@language": lang},
            }
            for theme in record.theme_category
        ]

    return {k: v for k, v in result.items() if v is not None}


def _contact_to_dcat(contact: RecordContact) -> dict:
    """Serialize a RecordContact to a vcard:Kind dict."""
    result: dict = {"@type": "vcard:Kind"}
    if contact.name is not None:
        result["vcard:fn"] = contact.name
    if contact.email is not None:
        result["vcard:hasEmail"] = contact.email
    if contact.organization is not None:
        result["vcard:organization-name"] = contact.organization
    if contact.role is not None:
        result["vcard:role"] = contact.role
    return {k: v for k, v in result.items() if v is not None}


def _distribution_to_dcat(dist: RecordDistribution, base_url: str) -> dict:
    """Serialize a RecordDistribution to a dcat:Distribution dict."""
    # Resolve relative URLs to absolute
    url = dist.url
    if url.startswith("/"):
        url = base_url + url

    result: dict = {"@type": "dcat:Distribution"}
    if dist.title is not None:
        result["dcterms:title"] = dist.title
    result["dcat:accessURL"] = url
    if dist.media_type is not None:
        result["dcat:mediaType"] = dist.media_type
    if dist.format is not None:
        result["dcterms:format"] = dist.format
    return {k: v for k, v in result.items() if v is not None}


def catalog_to_dcat(datasets: list[Dataset], base_url: str) -> dict:
    """Serialize a list of visible datasets to a DCAT 3 Catalog JSON-LD dict.

    Args:
        datasets: List of Dataset ORM objects with record relationships loaded.
        base_url: Absolute base URL.

    Returns:
        A DCAT Catalog dict with nested dataset entries (without individual @context).
    """
    return {
        "@context": DCAT_CONTEXT,
        "@type": "dcat:Catalog",
        "@id": f"{base_url}/datasets/dcat",
        "dcterms:title": {"@value": "GeoLens Dataset Catalog", "@language": "en"},
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
            record_to_dcat(ds, base_url, include_context=False) for ds in datasets
        ],
    }
