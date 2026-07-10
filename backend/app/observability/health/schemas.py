from pydantic import BaseModel


class ServiceHealth(BaseModel):
    status: str
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    # fix(#441): version + build commit make a deployment verifiable over HTTP.
    # Production disables the interactive docs, which were the only surface
    # that reported the running version. `build` is None outside release
    # images (the publish workflow stamps it via GEOLENS_BUILD_SHA).
    version: str
    build: str | None = None
    providers: dict[str, ServiceHealth]
