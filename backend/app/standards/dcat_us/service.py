"""DCAT-US 3.0 serialization for GeoLens records."""

from __future__ import annotations

from datetime import date, datetime, timezone
import re
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        Record,
        RecordContact,
        RecordDistribution,
    )

logger = structlog.stdlib.get_logger(__name__)

DCAT_US_CONTEXT = "https://resources.data.gov/dcat-us/3.0.0"
SERVICE_DISTRIBUTION_TYPES = {"api", "ogcService", "ogc_features", "vector_tiles"}
_EMAIL_PATTERN = re.compile(r"^mailto:[\w_~!$&'()*+,;=:.-]+@[\w.-]+\.[\w.-]+$")


def record_to_dcat_us3(
    dataset: Dataset,
    base_url: str,
    *,
    include_context: bool = True,
    catalog_contact_email: str | None = None,
) -> dict:
    """Serialize a GeoLens dataset to the DCAT-US Schema v3.0 profile."""
    record = dataset.record
    result: dict = {}

    if include_context:
        result["@context"] = DCAT_US_CONTEXT

    result["@id"] = f"{base_url}/datasets/{dataset.id}/dcat-us/3.0"
    result["@type"] = "Dataset"
    result["identifier"] = str(dataset.id)
    result["title"] = record.title

    result["description"] = _required_description(record.title, record.summary)

    result["publisher"] = _organization(record)

    contacts = [_contact_to_dcat_us3(contact) for contact in record.contacts]
    contacts = [contact for contact in contacts if contact is not None]
    if not contacts and catalog_contact_email is not None:
        contacts = [_catalog_contact(catalog_contact_email)]
    if contacts:
        result["contactPoint"] = contacts

    lang = _language_code(getattr(record, "language", None))
    if lang is not None:
        result["language"] = lang

    if record.created_at is not None:
        result["issued"] = _date_value(record.created_at)

    if record.updated_at is not None:
        result["modified"] = _date_value(record.updated_at)

    keywords = [kw.keyword for kw in record.keywords if kw.keyword]
    if keywords:
        result["keyword"] = keywords

    if record.update_frequency is not None:
        result["accrualPeriodicity"] = record.update_frequency

    access_rights = record.access_constraints or record.visibility
    if access_rights is not None:
        result["accessRights"] = access_rights

    if record.usage_constraints is not None:
        # DCAT-US 3.0 schema types `rights` as a list of statements (like
        # `provenance`), not a bare string. Emitting a string previously made a
        # record with usage_constraints fail JSON Schema validation — and under
        # the filter-the-feed posture that silently dropped it from the catalog.
        result["rights"] = [record.usage_constraints]

    if record.lineage_summary is not None:
        result["provenance"] = [record.lineage_summary]

    temporal = _temporal_to_dcat_us3(record)
    if temporal is not None:
        result["temporal"] = [temporal]

    spatial = _spatial_to_dcat_us3(record)
    if spatial is not None:
        result["spatial"] = spatial

    if record.theme_category:
        result["theme"] = [_concept(theme) for theme in record.theme_category]

    if record.distributions:
        result["distribution"] = [
            _distribution_to_dcat_us3(
                distribution,
                base_url,
                publisher=result["publisher"],
                contacts=contacts,
                license_value=record.license,
            )
            for distribution in record.distributions
        ]

    return _strip_empty(result)


def catalog_to_dcat_us3(
    datasets: list[Dataset],
    base_url: str,
    *,
    catalog_contact_email: str | None = None,
) -> dict:
    """Serialize visible datasets to a DCAT-US 3.0 Catalog document.

    Every visible input dataset is emitted. Required descriptions use a
    deterministic title fallback; missing record contacts use the explicitly
    configured catalog role mailbox. Without that mailbox, serialization stays
    truthful and validation reports the unresolved mandatory field.
    """
    now = datetime.now(timezone.utc).isoformat()
    entries = [
        record_to_dcat_us3(
            ds,
            base_url,
            include_context=False,
            catalog_contact_email=catalog_contact_email,
        )
        for ds in datasets
    ]
    publisher = {"@type": "Organization", "name": "GeoLens"}

    result = {
        "@context": DCAT_US_CONTEXT,
        "@id": f"{base_url}/datasets/dcat-us/3.0",
        "@type": "Catalog",
        "identifier": f"{base_url}/datasets/dcat-us/3.0",
        "title": "GeoLens Dataset Catalog",
        "description": "Geospatial dataset catalog managed by GeoLens",
        "issued": now,
        "modified": now,
        "language": "en",
        "publisher": publisher,
        "dataset": entries,
    }
    if catalog_contact_email is not None:
        result["contactPoint"] = [_catalog_contact(catalog_contact_email)]
    return result


def dcat_us3_fallback_fields(
    dataset: Dataset,
    catalog_contact_email: str | None = None,
) -> tuple[str, ...]:
    """Return required fields supplied by deterministic profile fallbacks."""
    fields: list[str] = []
    if not _has_text(dataset.record.summary):
        fields.append("description")
    has_record_contact = any(
        _contact_to_dcat_us3(contact) is not None for contact in dataset.record.contacts
    )
    if not has_record_contact and catalog_contact_email is not None:
        fields.append("contactPoint")
    return tuple(fields)


def _organization(record: Record) -> dict:
    name = record.source_organization or record.owner_org or "GeoLens"
    return {"@type": "Organization", "name": name.strip() or "GeoLens"}


def _catalog_contact(contact_email: str) -> dict:
    """Build a neutral non-personal contact for the catalog operator.

    DCAT-US requires both a formatted name and mail address. When record-level
    contact metadata is absent, the operator-configured role mailbox keeps the
    fallback explicit without claiming that the mailbox belongs to a dataset's
    source publisher.
    """
    return {
        "@type": "Kind",
        "fn": "Catalog metadata contact",
        "hasEmail": _mailto(contact_email),
    }


def _contact_to_dcat_us3(contact: RecordContact) -> dict | None:
    if contact.email is None:
        return None

    name = contact.name or contact.organization
    email = _mailto(contact.email.strip())
    if not _has_text(name) or _EMAIL_PATTERN.fullmatch(email) is None:
        return None

    result: dict = {
        "@type": "Kind",
        "fn": name.strip(),
        "hasEmail": email,
    }
    if contact.organization is not None:
        result["organization-name"] = contact.organization
    if contact.phone is not None:
        result["tel"] = contact.phone
    if contact.role is not None:
        result["title"] = contact.role
    return _strip_empty(result)


def _required_description(title: str, summary: str | None) -> str:
    if _has_text(summary):
        return summary.strip()
    return title.strip() or "Untitled dataset"


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _distribution_to_dcat_us3(
    distribution: RecordDistribution,
    base_url: str,
    *,
    publisher: dict,
    contacts: list[dict],
    license_value: str | None,
) -> dict:
    url = _absolute_url(distribution.url, base_url)
    result: dict = {
        "@type": "Distribution",
        "accessURL": url,
    }

    if distribution.title is not None:
        result["title"] = distribution.title
    if distribution.description is not None:
        result["description"] = distribution.description
    if distribution.distribution_type == "download":
        result["downloadURL"] = url
    if distribution.format is not None:
        result["format"] = distribution.format
    if distribution.media_type is not None:
        result["mediaType"] = distribution.media_type
    if license_value is not None:
        result["license"] = license_value

    if distribution.distribution_type in SERVICE_DISTRIBUTION_TYPES and contacts:
        result["accessService"] = [
            {
                "@type": "DataService",
                "title": distribution.title or "GeoLens data service",
                "endpointURL": [url],
                "publisher": publisher,
                "contactPoint": contacts,
            }
        ]

    return _strip_empty(result)


def _temporal_to_dcat_us3(record: Record) -> dict | None:
    if record.temporal_start is None and record.temporal_end is None:
        return None

    result: dict = {"@type": "PeriodOfTime"}
    if record.temporal_start is not None:
        result["startDate"] = record.temporal_start.isoformat()
    if record.temporal_end is not None:
        result["endDate"] = record.temporal_end.isoformat()
    return result


def _spatial_to_dcat_us3(record: Record) -> dict | None:
    if record.spatial_extent is None:
        return None

    try:
        from geoalchemy2.shape import to_shape

        min_x, min_y, max_x, max_y = to_shape(record.spatial_extent).bounds
    except Exception:  # broad: DCAT-US bbox serialize degrades to absent spatial
        logger.debug(
            "DCAT-US spatial extent serialization failed", record_id=str(record.id)
        )
        return None

    return {
        "@type": "Location",
        "bbox": (
            f"POLYGON(({min_x} {min_y}, "
            f"{min_x} {max_y}, "
            f"{max_x} {max_y}, "
            f"{max_x} {min_y}, "
            f"{min_x} {min_y}))"
        ),
    }


def _concept(value: str) -> dict:
    return {"@type": "Concept", "prefLabel": value}


def _language_code(value: str | None) -> str | None:
    if value is None:
        return "en"
    code = value.replace("_", "-").split("-", maxsplit=1)[0].strip().lower()
    if len(code) == 2:
        return code
    return None


def _date_value(value: date | datetime) -> str:
    return value.isoformat()


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


def _strip_empty(value: dict) -> dict:
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != [] and item != {}
    }
