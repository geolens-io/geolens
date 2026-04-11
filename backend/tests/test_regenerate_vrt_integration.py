"""Integration test for regenerate_vrt task — behavioral anchor for Phase 219.

This test is DELIBERATELY slow and real:
- Generates 2 real GeoTIFFs via rasterio
- Creates real PostGIS rows (Record, Dataset, RasterAsset, VrtGeneration, IngestJob, vrt_source_links)
- Invokes gdalbuildvrt as a subprocess
- Writes the result via a real LocalStorageProvider
- Reads back and asserts on 15 state mutations

Phase 219 extracts 3 helpers from regenerate_vrt. Any drift in behavior will
fail this test — that is the whole point of shipping this phase first.

DO NOT mock subprocess, rasterio, or async_session in this file. Use mocks
ONLY for generate_quicklook (see D-05) and optionally the non-fatal cache
invalidation / embedding deferral calls.
"""

import hashlib
import uuid
from pathlib import Path

import pytest
import rasterio
from sqlalchemy import select, text

# Fixture helpers (D-01: direct cross-test-file import)
from tests.test_raster_ingest import _write_tmp_tif

pytestmark = pytest.mark.asyncio  # strict mode requires explicit marker
