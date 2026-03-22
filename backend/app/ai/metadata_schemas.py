"""Request/response Pydantic models for AI-assisted metadata generation."""

from pydantic import BaseModel, Field


class MetadataAssistRequest(BaseModel):
    """Request body for metadata AI endpoints."""

    dataset_id: str = Field(
        ..., description="UUID of the dataset to generate metadata for"
    )


class SummaryDraftResponse(BaseModel):
    """AI-generated summary draft for a dataset."""

    draft: str = Field(..., description="AI-generated summary text (2-4 sentences)")


class KeywordSuggestionsResponse(BaseModel):
    """AI-suggested keywords for a dataset."""

    keywords: list[str] = Field(
        ..., description="List of suggested keywords (5-10 lowercase terms)"
    )


class LineageDraftResponse(BaseModel):
    """AI-generated lineage draft for a dataset."""

    draft: str = Field(..., description="AI-generated lineage summary (1-3 sentences)")


class QualityStatementDraftResponse(BaseModel):
    """AI-generated quality statement draft for a dataset."""

    draft: str = Field(
        ..., description="AI-generated quality statement (2-4 sentences)"
    )
