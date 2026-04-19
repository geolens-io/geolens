"""Aggregate API router composition."""

from fastapi import APIRouter

from app.modules.admin.router import router as admin_router
from app.processing.ai.router import router as ai_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.oauth.router import router as oauth_router
from app.modules.auth.router import router as auth_router
from app.modules.catalog.collections.router import router as collections_crud_router
from app.platform.config_ops.router import router as config_ops_router
from app.modules.catalog.datasets.api.router import router as datasets_router
from app.modules.catalog.datasets.api.router_data import router as datasets_data_router
from app.modules.catalog.datasets.api.router_export import (
    router as datasets_export_router,
)
from app.modules.catalog.datasets.api.router_metadata import (
    router as datasets_metadata_router,
)
from app.modules.catalog.datasets.api.router_reupload import (
    router as datasets_reupload_router,
)
from app.modules.catalog.datasets.api.router_vrt import router as datasets_vrt_router
from app.modules.embed_tokens.admin_router import router as embed_tokens_admin_router
from app.modules.embed_tokens.router import router as embed_tokens_router
from app.processing.export.router import router as export_router
from app.modules.catalog.features.router import features_router
from app.processing.ingest.router import router as ingest_router
from app.platform.jobs.router import router as jobs_router
from app.modules.catalog.layers.router import layers_router
from app.modules.catalog.maps.router import router as maps_router
from app.standards.ogc.router import ogc_features_router, ogc_router
from app.modules.catalog.records.router import router as records_router
from app.modules.catalog.search.router import collections_router, search_router
from app.modules.catalog.sources.router import router as services_router
from app.modules.catalog.sources.stac_router import router as stac_import_router
from app.modules.settings.router import router as settings_router
from app.standards.stac.router import stac_router
from app.processing.tiles.router import router as tiles_router


api_router = APIRouter()

# OGC discovery must stay first because it owns the root landing paths.
api_router.include_router(ogc_router)
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(audit_router)
api_router.include_router(ingest_router)

# Export must stay before dataset CRUD because /dcat conflicts with /{dataset_id}.
api_router.include_router(datasets_export_router)
api_router.include_router(datasets_router)
api_router.include_router(datasets_vrt_router)
api_router.include_router(datasets_data_router)
api_router.include_router(datasets_metadata_router)
api_router.include_router(datasets_reupload_router)
api_router.include_router(records_router)
api_router.include_router(features_router)
api_router.include_router(export_router)
api_router.include_router(jobs_router)
api_router.include_router(search_router)
api_router.include_router(collections_router)
api_router.include_router(collections_crud_router)

# Per-dataset OGC Features must stay after /collections/datasets routes.
api_router.include_router(ogc_features_router)

api_router.include_router(maps_router)
api_router.include_router(ai_router)
api_router.include_router(services_router)
api_router.include_router(stac_import_router)
api_router.include_router(layers_router)
api_router.include_router(settings_router)
api_router.include_router(oauth_router)
api_router.include_router(config_ops_router)
api_router.include_router(embed_tokens_router)
api_router.include_router(embed_tokens_admin_router)
api_router.include_router(tiles_router)
api_router.include_router(stac_router)

__all__ = ["api_router"]
