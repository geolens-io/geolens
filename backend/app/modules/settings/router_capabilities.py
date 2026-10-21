"""Discovery document for desktop and script clients."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.edition import get_edition
from app.core.identity import Identity
from app.core.persistent_config import (
    PASSWORD_LOGIN_ENABLED,
    get_cached_global_rate_limit,
    get_cached_login_rate_limit,
)
from app.modules.auth.dependencies import get_optional_user
from app.modules.auth.oauth.sign_in_methods import list_sign_in_methods
from app.modules.auth.permissions import get_user_effective_permissions
from app.modules.quota.service import remaining_dataset_quota
from app.modules.settings.basemaps import list_public_basemaps
from app.modules.settings.router_public import get_feature_flags
from app.modules.settings.schemas import FeatureFlagsResponse
from app.platform.extensions import get_workflow_extension
from app.platform.request_credential import api_key_credential
from app.processing.ingest.schemas import UploadConfigResponse
from app.processing.ingest.upload_limits import (
    build_upload_config,
    manifest_publishable_extensions,
)

router = APIRouter(tags=["Admin"])

PUBLISH_CONTRACT = 1


class CapabilitiesServer(BaseModel):
    version: str = Field(description="Running GeoLens version.")
    edition: str = Field(description="Edition the server runs.")


class CapabilitiesAuth(BaseModel):
    password_login_enabled: bool = Field(
        description="Whether username and password sign-in is on."
    )
    methods: list[str] = Field(
        description="Sign-in methods on offer: `password` plus each enabled provider type."
    )


class CapabilitiesUpload(BaseModel):
    max_file_size_bytes: int = Field(description="Largest accepted upload, in bytes.")
    allowed_extensions: list[str] = Field(
        description="Extensions a publish manifest can carry, a subset of the upload allowlist."
    )
    presigned: bool = Field(description="Whether direct-to-S3 uploads are enabled.")


class CapabilitiesBasemap(BaseModel):
    id: str = Field(description="Basemap identifier to use in a map document.")
    name: str = Field(description="Display name.")


class CapabilitiesRateLimits(BaseModel):
    global_per_second: int = Field(description="Requests per second per client IP.")
    login_per_minute: int = Field(description="Login attempts per minute.")


class CapabilitiesKey(BaseModel):
    scope: str = Field(description="Scope of the API key making the request.")
    expires_at: datetime | None = Field(
        description="When the key stops working, or null if it does not expire."
    )


class CapabilitiesMe(BaseModel):
    username: str = Field(description="Signed-in account.")
    permissions: list[str] = Field(description="Capabilities the account holds.")
    key: CapabilitiesKey | None = Field(
        description="Present only when the request authenticated with an API key."
    )
    remaining_dataset_quota: int | None = Field(
        description="Datasets the account can still create, or null when uncapped."
    )


class CapabilitiesResponse(BaseModel):
    server: CapabilitiesServer
    publish_contract: int = Field(
        description="Version of the publish contract the server speaks."
    )
    auth: CapabilitiesAuth
    upload: CapabilitiesUpload | None = Field(
        description="Upload limits. Present only with credentials."
    )
    basemaps: list[CapabilitiesBasemap] = Field(
        description="Enabled basemaps whose provider key, if any, is configured."
    )
    flags: FeatureFlagsResponse
    status_order: list[str] = Field(
        description="Dataset workflow statuses, from first to last."
    )
    rate_limits: CapabilitiesRateLimits
    me: CapabilitiesMe | None = Field(
        description="The caller's account. Present only with credentials."
    )


async def _basemaps(db: AsyncSession) -> list[CapabilitiesBasemap]:
    return [
        CapabilitiesBasemap(id=b.id, name=b.label)
        for b in await list_public_basemaps(db)
        if b.enabled
    ]


async def _auth(db: AsyncSession) -> CapabilitiesAuth:
    return CapabilitiesAuth(
        password_login_enabled=await PASSWORD_LOGIN_ENABLED.get(db),
        methods=await list_sign_in_methods(db),
    )


def _upload(limits: UploadConfigResponse) -> CapabilitiesUpload:
    return CapabilitiesUpload(
        max_file_size_bytes=limits.max_file_size_bytes,
        allowed_extensions=manifest_publishable_extensions(limits.allowed_extensions),
        presigned=limits.presigned_uploads,
    )


async def _me(
    db: AsyncSession, user: Identity, limits: UploadConfigResponse
) -> CapabilitiesMe:
    credential = api_key_credential(db)
    permissions = await get_user_effective_permissions(db, user)
    return CapabilitiesMe(
        username=user.username,
        permissions=sorted(cap for cap, granted in permissions.items() if granted),
        key=(
            CapabilitiesKey(scope=credential.scope, expires_at=credential.expires_at)
            if credential is not None
            else None
        ),
        remaining_dataset_quota=limits.remaining_dataset_quota,
    )


@router.get(
    "/capabilities", response_model=CapabilitiesResponse, include_in_schema=False
)
@router.get("/capabilities/", response_model=CapabilitiesResponse)
async def get_capabilities(
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> CapabilitiesResponse:
    """Describe what this server offers, for a client's first call.

    Anonymous callers get the server, sign-in, basemap, workflow and rate-limit
    facts. A caller with credentials also gets `upload` and `me`.
    """
    limits = (
        await build_upload_config(db, await remaining_dataset_quota(db, user.id))
        if user is not None
        else None
    )
    return CapabilitiesResponse(
        server=CapabilitiesServer(
            version=request.app.version, edition=get_edition().edition
        ),
        publish_contract=PUBLISH_CONTRACT,
        auth=await _auth(db),
        upload=_upload(limits) if limits is not None else None,
        basemaps=await _basemaps(db),
        flags=await get_feature_flags(db),
        status_order=list(get_workflow_extension().status_order()),
        rate_limits=CapabilitiesRateLimits(
            global_per_second=get_cached_global_rate_limit(),
            login_per_minute=get_cached_login_rate_limit(),
        ),
        me=await _me(db, user, limits) if user is not None and limits else None,
    )
