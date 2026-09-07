"""Record validation service -- three-tier quality gating."""

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    Record,
    RecordContact,
    RecordKeyword,
)


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: Literal["error", "warning"]


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)


async def validate_record(
    session: AsyncSession,
    record: Record,
    dataset: Dataset | None = None,
) -> ValidationResult:
    """Validate a record for publishing readiness.

    Hard (VAL-01, blocks publish): title, summary, license, spatial_extent,
    CRS, lineage_summary, >=1 contact, >=1 keyword.
    Soft (VAL-02, warnings only): temporal extent, update_frequency,
    quality_statement, attribute descriptions, source_url.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    if not record.title or not record.title.strip():
        errors.append(ValidationIssue("title", "Title is required", "error"))
    if not record.summary or not record.summary.strip():
        errors.append(ValidationIssue("summary", "Summary is required", "error"))
    if not record.license:
        errors.append(ValidationIssue("license", "License is required", "error"))
    if record.spatial_extent is None:
        errors.append(
            ValidationIssue("spatial_extent", "Spatial extent is required", "error")
        )
    if not record.lineage_summary:
        errors.append(
            ValidationIssue("lineage_summary", "Lineage summary is required", "error")
        )

    if dataset and dataset.srid is None:
        errors.append(
            ValidationIssue(
                "srid", "Coordinate reference system (CRS) is required", "error"
            )
        )

    contact_count = await session.scalar(
        select(func.count()).where(RecordContact.record_id == record.id)
    )
    if not contact_count:
        errors.append(
            ValidationIssue("contacts", "At least one contact is required", "error")
        )

    keyword_count = await session.scalar(
        select(func.count()).where(RecordKeyword.record_id == record.id)
    )
    if not keyword_count:
        errors.append(
            ValidationIssue("keywords", "At least one keyword is required", "error")
        )

    if record.temporal_start is None and record.temporal_end is None:
        warnings.append(
            ValidationIssue(
                "temporal_extent", "Temporal extent is recommended", "warning"
            )
        )
    if not record.update_frequency:
        warnings.append(
            ValidationIssue(
                "update_frequency", "Update frequency is recommended", "warning"
            )
        )

    if dataset:
        if not dataset.quality_statement:
            warnings.append(
                ValidationIssue(
                    "quality_statement", "Quality statement is recommended", "warning"
                )
            )
        if not dataset.source_url:
            warnings.append(
                ValidationIssue("source_url", "Source URL is recommended", "warning")
            )

        attr_without_desc = await session.scalar(
            select(func.count()).where(
                AttributeMetadata.dataset_id == dataset.id,
                AttributeMetadata.is_current == True,  # noqa: E712
                AttributeMetadata.description.is_(None),
                AttributeMetadata.semantic_role != "geometry",
            )
        )
        if attr_without_desc and attr_without_desc > 0:
            warnings.append(
                ValidationIssue(
                    "attribute_descriptions",
                    f"{attr_without_desc} attribute(s) missing descriptions",
                    "warning",
                )
            )

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
