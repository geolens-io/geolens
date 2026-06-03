from pydantic import BaseModel


class ServiceHealth(BaseModel):
    status: str
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    providers: dict[str, ServiceHealth]
