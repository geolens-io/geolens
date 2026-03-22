import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    dataset_id: uuid.UUID | None
    source_filename: str | None
    error_message: str | None
    warning_message: str | None = None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
