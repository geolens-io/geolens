import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.catalog.datasets.domain.schemas import DatasetResponse


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class CollectionSummary(BaseModel):
    id: uuid.UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class CollectionResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    dataset_count: int
    extent_bbox: list[float] | None = None
    temporal_start: date | None = None
    temporal_end: date | None = None

    model_config = ConfigDict(from_attributes=True)


class CollectionListResponse(BaseModel):
    collections: list[CollectionResponse]
    total: int


class CollectionAddDatasetsRequest(BaseModel):
    dataset_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class CollectionDatasetResponse(BaseModel):
    datasets: list[DatasetResponse]
    total: int


class AddDatasetsResponse(BaseModel):
    added: int
