"""Validation result schemas for API responses."""

from typing import Literal

from pydantic import BaseModel


class ValidationIssue(BaseModel):
    field: str
    message: str
    severity: Literal["error", "warning"]


class ValidationResultResponse(BaseModel):
    is_valid: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    quality_score: dict | None = None
