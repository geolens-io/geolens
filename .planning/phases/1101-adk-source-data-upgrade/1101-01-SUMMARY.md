# Phase 1101 Summary: ADK Source Data Upgrade

**Status:** Complete
**Requirements closed:** ADK-DATA-01, ADK-DATA-02, ADK-DATA-03, ADK-DATA-04, ADK-DATA-05

## Delivered

- `fetch_aerial.py` now queries TNM NAIP first and writes exact evidence to `.scratch/adk-data/aerial/tnm_naip_query.json`.
- TNM returned `total: 0` for the High Peaks AOI on 2026-05-24; the script used the documented high-fidelity NY orthos fallback.
- The NY orthos fallback now fetches a 4x4 grid of 4096x4096 tiles, producing 16 source tiles and a 64 MB EPSG:3857 aerial COG at `.scratch/adk-data/cogs/adk_high_peaks_ny_orthos_tiled_3857.tif`.
- `fetch_vectors.py` now fetches USGS NHD large-scale flowlines and waterbodies.
- Complete official ADK 46er peak generation now produces 46 features from APA Summits layers 0, 1, and 2.
- `compose_marketing_maps.py` now points at the new tiled aerial source filename and accepts `202 Import queued` from ingest commit before polling.

## Evidence

- TNM NAIP evidence: `.scratch/adk-data/aerial/tnm_naip_query.json` reports `response.total == 0`.
- NHD fetch: 579 flowline features and 96 waterbody features.
- 46er fetch: 46 official peak features.
- Aerial COG: 12271x20539 pixels, `LAYOUT=COG`, `COMPRESSION=YCbCr JPEG`, 64 MB.

## Notes

The user's requested TNM/NAIP source was attempted first. The live TNM API did not publish NAIP GeoTIFF products for this AOI, so the milestone uses the explicit high-fidelity fallback rather than silently retaining the original 3.5 MB aerial.
