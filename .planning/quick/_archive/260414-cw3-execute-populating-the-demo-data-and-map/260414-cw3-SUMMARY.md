# Quick Task 260414-cw3: Execute populating the demo data and maps — Summary

**Completed:** 2026-04-14
**Status:** Done

## What was done

1. **Fixed QualityDetail schema bug** — `backend/app/datasets/schemas.py` had `le=1.0` constraints on quality score fields but `compute_quality_score()` returns values in the 0-100 range. Also, `geometry_validity` and `crs_defined` are `None` for table records but the schema didn't allow `None`. Both issues caused 500 errors on all dataset GET/PATCH endpoints.

2. **Ran the demo seeder** via `docker compose -f docker-compose.yml -f docker-compose.demo.yml run --rm --no-deps seeder`. First run ingested all 23 datasets across 3 themes. Second run (after API fix) applied all 8 map fixtures.

## Results

- **23 demo datasets** ingested across 3 themes (all skipped on re-run — idempotent)
- **3 themed collections** created: Planet Earth (9 datasets), How the World Lives (4 datasets), Lines on the Map (10 datasets)
- **8 map fixtures** applied: Earth as Seen from Space, Global Bathymetry, GDP per Capita PPP 2023, Population at a Glance, Conflict Events 2024, The World's Disputed Places, One Territory Multiple Official Maps, Refugees by Country of Origin 2023

## Bug fix

**File:** `backend/app/datasets/schemas.py`

`QualityDetail` field constraints changed:
- All fields: `le=1.0` → `le=100.0` (quality scores are percentages, not fractions)
- `geometry_validity`, `crs_defined`: `float` → `float | None` (N/A for table records)

## Notes

- The 307 redirects on `POST .../collections/{id}/datasets` (without trailing slash) are harmless — httpx follows the redirect. The seeder code has the trailing slash but the logs show the redirect path.
- The demo overlay (`docker-compose.demo.yml`) recreates the API in production mode. Use `--no-deps` to avoid disrupting the dev API.
