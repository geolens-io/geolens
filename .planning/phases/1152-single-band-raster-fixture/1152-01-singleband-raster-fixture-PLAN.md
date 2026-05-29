---
phase: 1152-single-band-raster-fixture
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/seed-natural-earth.py
autonomous: true
requirements: [TESTDATA-01]

must_haves:
  truths:
    - "Running scripts/seed-natural-earth.py ingests a single-band uint8 raster fixture (GRAY_50M_SR) into the catalog"
    - "The ingested fixture is classified is_dem=false (NOT routed through algorithm=terrainrgb), so the stretch/colormap UI applies to it"
    - "Re-running the seed script skips the fixture — no duplicate dataset is created"
    - "Existing Natural Earth vector seed behavior is unchanged"
  artifacts:
    - path: "scripts/seed-natural-earth.py"
      provides: "ingest_raster_fixture() function + raster fixture manifest entry + call wired into main() after the vector loop"
      contains: "ingest_raster_fixture"
  key_links:
    - from: "scripts/seed-natural-earth.py:main"
      to: "ingest_raster_fixture"
      via: "post-vector-loop call before create_collections, gated on the existing source_filename idempotency map"
      pattern: "ingest_raster_fixture\\("
    - from: "ingest_raster_fixture"
      to: "/api/ingest/upload"
      via: ".tif/.zip upload triggers server-side raster auto-detection (_stamp_raster_metadata)"
      pattern: "ingest/upload"
---

<objective>
Add a non-DEM single-band uint8 raster fixture to `scripts/seed-natural-earth.py` so the v1034 colormap/stretch UI (phases 1154/1155) can be verified against real single-band raster data instead of a DEM that silently bypasses all stretch/colormap logic.

Purpose: TESTDATA-01 is a hard precondition for the rest of v1034. Without a real `is_dem=false` single-band raster in the catalog, the "verify colormap/stretch UI" acceptance criteria in later phases would appear to pass (HTTP 200 tiles) while actually exercising nothing — the DEM `algorithm=terrainrgb` guard skips stretch/colormap entirely.

Output: an extended seed script with an idempotent `ingest_raster_fixture()` function, plus a documented, executed verification that the ingested fixture is single-band (`band_count==1` via API) AND `is_dem=false` (via direct DB check) AND idempotent (re-run creates no duplicate).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1152-single-band-raster-fixture/1152-CONTEXT.md
@.planning/research/PITFALLS.md
@.planning/research/STACK.md
@.planning/research/ARCHITECTURE.md

<interfaces>
Contracts the executor needs. Extracted from the live codebase — no exploration needed.

DEM-misclassification heuristic this fixture MUST avoid tripping — backend/app/processing/raster/cog.py:85:
    is_dem_candidate = src.count == 1 and _is_float_dtype(src.dtypes[0])
GRAY_50M_SR is single-band uint8 -> _is_float_dtype("uint8") is False -> is_dem_candidate=False. Safe.

is_dem column (authoritative) — backend/app/processing/raster/models.py:
  :24  __tablename__ = "raster_assets", schema "catalog"
  :72  is_dem: Mapped[bool] (NOT NULL, server_default "false")
  Joined to catalog.datasets via dataset_id.
  NOTE: is_dem is NOT exposed on the dataset detail API (RasterMetadata has no is_dem field) — verify via DB.

band_count IS exposed via the dataset detail API:
  GET /api/datasets/{id} -> DatasetResponse.raster (RasterMetadata).band_count : int | null

Existing seed-script idempotency pattern (REUSE — do not invent a new one):
  fetch_existing_datasets() returns dict[source_filename -> dataset_id]  (seed-natural-earth.py:345)
  main() builds `existing = await fetch_existing_datasets(...)` at ~line 1090
  process_one() skips when `filename in existing`  (line 978)

Existing three-step ingest used by vectors — the SAME flow works for rasters; the server discriminates
raster vs vector by file extension (.tif/.tiff/.vrt) in _stamp_raster_metadata, NOT by commit body shape:
  POST /api/ingest/upload  files={"file": (name, bytes, mime)}  -> {"job_id"}
  POST /api/ingest/preview/{job_id}
  POST /api/ingest/commit/{job_id}  json={"title", "visibility"}    # rasters do NOT need srid_override (CRS embedded)
  await poll_job(client, base_url, api_key, job_id)  -> result dict with "status" and "dataset_id"

Helpers to reuse verbatim: download_or_load_cache(), download_dataset(), poll_job(), fetch_existing_datasets().
The .zip OR a bare .tif is accepted by the upload route (ingest/router.py:97-98) — upload the .zip, do not extract.

Fixture source (locked by research — STACK.md §5):
  URL:      https://naciscdn.org/naturalearth/50m/raster/GRAY_50M_SR.zip
  License:  public domain (Natural Earth terms-of-use)
  Contents: GRAY_50M_SR.tif — single-band grayscale uint8, EPSG:4326, ~18 MB zip
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add idempotent ingest_raster_fixture() to the seed script and wire it into main()</name>
  <files>scripts/seed-natural-earth.py</files>
  <read_first>
    - scripts/seed-natural-earth.py (the whole file — you are extending it; reuse download_or_load_cache, poll_job, fetch_existing_datasets, the three-step ingest pattern in ingest_dataset(), and the main() structure)
    - backend/app/processing/raster/cog.py (lines 1-130 — understand the `is_dem_candidate = src.count == 1 and _is_float_dtype(...)` heuristic at line 85 and `_FLOAT_DTYPES` at line 11, so it is clear WHY GRAY_50M_SR uint8 is safe and a float fixture would not be)
    - backend/tests/test_seed_natural_earth_reconciliation.py (lines 1-80 — the existing test loads the script via importlib spec_from_file_location as `seed_natural_earth`; keep new top-level functions importable and side-effect-free at module load)
  </read_first>
  <action>
    Add a raster fixture manifest constant and a new `ingest_raster_fixture()` coroutine, then call it from `main()` after the vector TaskGroup completes and before `create_collections(...)`.

    1. Add a module-level constant near the vector DATASETS manifest:
       `RASTER_FIXTURE = {"stem": "GRAY_50M_SR", "filename": "GRAY_50M_SR.zip", "url": "https://naciscdn.org/naturalearth/50m/raster/GRAY_50M_SR.zip", "name": "Natural Earth Shaded Relief (1:50m)", "tags": ["raster", "shaded-relief", "natural-earth", "grayscale"]}`.
       Add an inline comment citing the public-domain license (Natural Earth terms-of-use) and stating the band is single-band uint8 so `is_dem_candidate` is False (closes PITFALLS Pitfall 2 + Pitfall 9). This is the GRAY_50M_SR option from research — chosen over a synthetic GDAL COG because it needs no GDAL-on-PATH dependency in the seed environment, reuses the existing NACIS CDN + `download_or_load_cache` retry/cache path, is confirmed public-domain, and is confirmed single-band uint8 (so it cannot trip the DEM heuristic).

    2. Define `async def ingest_raster_fixture(client, base_url, api_key, existing_by_filename, cache_dir) -> dict:`
       - Idempotency FIRST (reuse the existing `source_filename` map — PITFALLS Pitfall 8): if `RASTER_FIXTURE["filename"] in existing_by_filename`, print a "Skipping (already imported)" line and return `{"stem": "GRAY_50M_SR", "status": "skipped", "dataset_id": existing_by_filename[RASTER_FIXTURE["filename"]]}` WITHOUT downloading or uploading.
       - Otherwise download via the EXISTING `download_or_load_cache(client, url, stem, cache_dir)` helper (gets retry + cache for free; upload the .zip directly — do NOT extract it).
       - Ingest via the EXISTING three-step flow exactly as `ingest_dataset()` does: `POST /api/ingest/upload` with `files={"file": (RASTER_FIXTURE["filename"], data, "image/tiff")}`; `POST /api/ingest/preview/{job_id}`; `POST /api/ingest/commit/{job_id}` with json `{"title": RASTER_FIXTURE["name"], "visibility": "public"}` — do NOT send `srid_override` (the GeoTIFF carries EPSG:4326; raster commit does not need it per ARCHITECTURE.md §Feature 3). Then `await poll_job(...)`.
       - On `result["status"] == "failed"`, return `{"stem": "GRAY_50M_SR", "status": "failed", "error": result.get("error_message", "unknown")}` — do NOT raise (mirror process_one's per-dataset isolation so a fixture failure never cancels the vector run).
       - On success return `{"stem": "GRAY_50M_SR", "status": "succeeded", "dataset_id": result.get("dataset_id")}`. Apply the manifest tags via the same post-ingest `/api/records/{record_id}/keywords/` block ingest_dataset uses (best-effort; 409 is fine) — keep it best-effort and non-fatal.

    3. Wire into `main()`: after the vector `async with asyncio.TaskGroup()` loop closes and after the summary/reconciliation, but before `create_collections(...)`, add a clearly-printed "--- Raster Fixture ---" section that awaits `ingest_raster_fixture(client, base_url, api_key, existing, cache_dir)` and appends its result to the `results` list so the existing summary counters and collection grouping see it. A failed fixture result already carries `status="failed"` and will count in `failed`, preserving the existing `failed > 0` exit-code rule — do not add new exit-code logic.

    Do NOT modify the vector DATASETS manifest, generate_name/generate_tags, process_one, or any existing vector ingest behavior. Do NOT add a pytest-time download. Do NOT use a float dtype or a synthetic float raster.
  </action>
  <verify>
    <automated>python -c "import importlib.util,pathlib; s=importlib.util.spec_from_file_location('seed_natural_earth', pathlib.Path('scripts/seed-natural-earth.py')); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert hasattr(m,'ingest_raster_fixture'); assert m.RASTER_FIXTURE['filename']=='GRAY_50M_SR.zip'; assert 'naciscdn.org' in m.RASTER_FIXTURE['url']; print('OK')"</automated>
  </verify>
  <acceptance_criteria>
    - `scripts/seed-natural-earth.py` imports cleanly via importlib spec (no module-load side effects) and exposes a top-level `ingest_raster_fixture` coroutine and a `RASTER_FIXTURE` dict whose `url` points at the NACIS CDN GRAY_50M_SR zip.
    - `ingest_raster_fixture` returns a `{"status": "skipped", ...}` dict (without any HTTP upload) when `RASTER_FIXTURE["filename"]` is already present in the passed `existing_by_filename` map.
    - The commit call sends `{"title", "visibility"}` only (no `srid_override`) and uses MIME `image/tiff` on upload.
    - `main()` calls `ingest_raster_fixture(...)` exactly once, after the vector loop and before `create_collections(...)`, appending its result to `results`.
    - `git diff` shows zero changes to the vector `DATASETS` manifest, `generate_name`, `generate_tags`, `process_one`, or the existing `ingest_dataset` vector flow.
  </acceptance_criteria>
  <done>
    The seed script has an idempotent raster-fixture ingest path wired into main(); the importlib smoke check passes; no vector behavior changed.
  </done>
</task>

<task type="auto">
  <name>Task 2: Run the seed against the dev stack and verify single-band + is_dem=false + idempotency</name>
  <files>scripts/seed-natural-earth.py</files>
  <read_first>
    - scripts/seed-natural-earth.py (the section you just added — confirm the printed fixture-section output and the result-dict keys you will grep for)
    - .planning/research/PITFALLS.md (the "Looks Done But Isn't" checklist + Pitfall 2 + Pitfall 8 — these are the exact acceptance gates)
    - docker-compose.yml (lines 106-121 — the `db` service; verify is_dem via `docker compose exec db psql` so no host DB creds are needed)
  </read_first>
  <action>
    Bring up the stack if not already running (`docker compose up -d`), then run the seed against the live dev API and assert the three gates. Use the admin login path the script already supports (`--username admin --password admin`, or the GEOLENS_ADMIN_* env vars). The seed script needs `httpx` on the runner — install it (or run under the backend venv) first.

    1. First run — ingest the fixture: `python scripts/seed-natural-earth.py --username admin --password admin`. The vector loop is idempotent and skips already-seeded data; the fixture is the new work. Capture the printed "--- Raster Fixture ---" section; confirm it reports succeeded (or skipped if a prior run already ingested it).

    2. Assert single-band via the API (RasterMetadata.band_count): list datasets, find the one whose `source_filename == "GRAY_50M_SR.zip"`, GET `/api/datasets/{id}`, and assert `response.raster.band_count == 1`. (band_count is the API-exposed single-band proof; is_dem is not on the API so it is checked in step 3.)

    3. Assert `is_dem=false` (the authoritative DEM-trap gate — PITFALLS Pitfall 2) via direct DB query, joining raster_assets to datasets by source_filename so no dataset_id needs hardcoding:
       `docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT ra.is_dem FROM catalog.raster_assets ra JOIN catalog.datasets d ON d.id = ra.dataset_id WHERE d.source_filename = 'GRAY_50M_SR.zip';"`
       (POSTGRES_USER/POSTGRES_DB come from the env / .env.) The result MUST be exactly `f`. If it returns `t`, STOP — the fixture was misclassified as a DEM (the v1034 critical trap) and is unusable.

    4. Idempotency re-run (PITFALLS Pitfall 8): run `python scripts/seed-natural-earth.py --username admin --password admin` a SECOND time and assert (a) the fixture section prints "Skipping ... (already imported)" and (b) the catalog has exactly one dataset for the fixture:
       `docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM catalog.datasets WHERE source_filename = 'GRAY_50M_SR.zip';"` returns `1`.

    Record the resolved fixture dataset_id, the band_count value, the is_dem value, and the duplicate-count in the SUMMARY so phases 1154/1155 can reference the fixture directly.
  </action>
  <verify>
    <automated>docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT (count(*) = 1 AND bool_or(NOT ra.is_dem)) FROM catalog.datasets d JOIN catalog.raster_assets ra ON ra.dataset_id = d.id WHERE d.source_filename = 'GRAY_50M_SR.zip';" | grep -qx t && echo "PASS: exactly 1 fixture row AND is_dem=false"</automated>
  </verify>
  <acceptance_criteria>
    - After running the seed, the catalog contains exactly one dataset with `source_filename = 'GRAY_50M_SR.zip'`.
    - `GET /api/datasets/{fixture_id}` returns `raster.band_count == 1` (single-band proof via API).
    - `SELECT ra.is_dem FROM catalog.raster_assets ra JOIN catalog.datasets d ON d.id = ra.dataset_id WHERE d.source_filename = 'GRAY_50M_SR.zip'` returns `f` (is_dem=false — the DEM trap is NOT tripped).
    - A second seed run prints the fixture "Skipping (already imported)" line and leaves the fixture dataset count at exactly 1 (no duplicate).
    - The resolved fixture dataset_id, band_count, is_dem, and duplicate-count are recorded in the SUMMARY.
  </acceptance_criteria>
  <done>
    The seed has ingested a single-band uint8 raster fixture verified is_dem=false and idempotent; the fixture dataset_id is recorded for downstream phases.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| seed runner -> GeoLens API | Operator-run script authenticates via admin login + minted bootstrap key; uploads a public-domain fixture |
| GeoLens API -> NACIS CDN | Server never fetches; the seed runner downloads the fixture from the public NACIS CDN (HTTPS) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1152-01 | Tampering | Fixture downloaded from naciscdn.org | accept | Public-domain Natural Earth asset over HTTPS; reuses the same CDN already trusted by the existing vector seed path. No new trust surface. |
| T-1152-02 | Spoofing | Admin credentials passed to the seed script | accept | Same admin-login + temporary-bootstrap-key flow the existing vector seed already uses; key is deleted on exit. No new auth surface. |
| T-1152-SC | Tampering | npm/pip/cargo installs | n/a | No package installs introduced. `httpx` (already a script dependency) is the only runtime requirement; no new dependency added. No legitimacy gate required. |
</threat_model>

<verification>
- Task 1 importlib smoke check passes (`ingest_raster_fixture` + `RASTER_FIXTURE` present, module loads clean).
- Task 2 combined DB gate passes: exactly one `GRAY_50M_SR.zip` dataset AND `is_dem=false`.
- API check: `GET /api/datasets/{fixture_id}.raster.band_count == 1`.
- Idempotency: second seed run prints "Skipping (already imported)" and dataset count stays 1.
- `git diff scripts/seed-natural-earth.py` confirms vector seed paths untouched.
</verification>

<success_criteria>
A non-DEM single-band uint8 raster fixture (GRAY_50M_SR) is seeded idempotently via `scripts/seed-natural-earth.py`, is verified `band_count==1` (API) and `is_dem=false` (DB), and re-running the seed creates no duplicate — satisfying TESTDATA-01 as the precondition for v1034 phases 1154/1155 colormap/stretch verification.
</success_criteria>

<output>
Create `.planning/phases/1152-single-band-raster-fixture/1152-01-SUMMARY.md` when done. Record the resolved fixture dataset_id, band_count, is_dem value, and duplicate-count for downstream phases.
</output>
