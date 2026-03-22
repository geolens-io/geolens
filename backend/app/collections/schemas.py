import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.datasets.schemas import DatasetResponse


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


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
    dataset_ids: list[uuid.UUID]


class CollectionDatasetResponse(BaseModel):
    datasets: list[DatasetResponse]
    total: int


class AddDatasetsResponse(BaseModel):
    added: int
