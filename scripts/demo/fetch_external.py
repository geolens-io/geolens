#!/usr/bin/env python3
"""Pre-fetch script for GeoLens thematic demo external data sources.

Runs INSIDE the seeder container via run-seeder.sh OR on a developer host
with system GDAL. Outputs to scripts/demo/raw/external/ relative to this
file's parent.

Five data sources (sequential, idempotent):
  1. USGS 3DEP DEM (Grand Canyon AOI)  -> grand_canyon_dem.tif
     Hillshade derivative                -> grand_canyon_hillshade.tif
  2. NYC PLUTO zoning                   -> nyc_pluto_zoning.geojson
     (NYC Building Footprints joined to tabular PLUTO via mappluto_bbl)
  3. Census tract pop-density (4 state) -> pop_density_tracts.geojson
     (TIGER cb_2024_us_tract_500k + ACS 2023 5-year B01003/B19013)
  4. USGS earthquakes M5+ (5y window)   -> usgs_quakes_m5.geojson
  5. NIFC WFIGS Interagency Perimeters  -> nifc_fires_2020_2024.geojson
     (10 western states, 2020-2024)

External services depended on (no auth required for any):
  - prd-tnm.s3.amazonaws.com (USGS 3DEP S3 bucket)
  - data.cityofnewyork.us (Socrata: 5zhs-2jue, 64uk-42ks)
  - www2.census.gov (TIGER cb_2024_us_tract_500k)
  - api.census.gov (ACS 2023 5-year, < 500 queries/IP/day)
  - earthquake.usgs.gov (FDSN events)
  - services3.arcgis.com (NIFC WFIGS_Interagency_Perimeters)

Idempotency: each fetcher checks `already_present(path)` before doing any
network or GDAL work; re-running after deleting a single file refreshes only
that file.

Manual usage on developer host (requires system GDAL):
    python3 scripts/demo/fetch_external.py
    python3 scripts/demo/fetch_external.py --only usgs_quakes_m5

Run inside the seeder container (preferred — GDAL guaranteed):
    docker compose -f docker-compose.demo.yml run --rm seeder
    (run-seeder.sh invokes this script before the orchestrator launches.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

OUT_DIR = Path(__file__).parent / "raw" / "external"
USER_AGENT = "GeoLens-Demo-Seeder/1.0"
HTTP_TIMEOUT = 600.0  # large for DEM tile fetches and NIFC pagination

logger = logging.getLogger("fetch-external")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def already_present(path: Path, min_bytes: int = 1024) -> bool:
    """Idempotency check matching run-seeder.sh's existing convention.

    Returns True iff the path exists and is at least min_bytes in size.
    """
    return path.exists() and path.stat().st_size >= min_bytes


def run_gdal(cmd: list[str]) -> None:
    """Invoke a GDAL CLI tool via subprocess. Raises CalledProcessError on non-zero exit."""
    logger.info("RUN: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# 1. Grand Canyon DEM + hillshade (USGS 3DEP)
# ---------------------------------------------------------------------------

async def fetch_grand_canyon_dem(client: httpx.AsyncClient) -> None:
    """Crop the 1/3 arc-second 3DEP VRT to the Grand Canyon AOI, then derive
    a multidirectional hillshade via gdaldem.

    Two outputs:
      grand_canyon_dem.tif       Float32 elevation (m), COG/DEFLATE
      grand_canyon_hillshade.tif uint8 grayscale, COG/DEFLATE

    The fixture stacks them: DEM at lower opacity below, hillshade at mid
    opacity on top (per RESEARCH.md pitfall H — Float32 + uint8 cannot be
    VRT-mosaicked).
    """
    out_dem = OUT_DIR / "grand_canyon_dem.tif"
    out_hs = OUT_DIR / "grand_canyon_hillshade.tif"
    if already_present(out_dem) and already_present(out_hs):
        logger.info("Grand Canyon DEM + hillshade already present, skipping")
        return

    vrt = (
        "/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/"
        "13/TIFF/USGS_Seamless_DEM_13.vrt"
    )
    # gdal_translate -projwin requires bounds in (ulx, uly, lrx, lry) order
    # = (west, north, east, south). For the Grand Canyon AOI:
    #   west=-113.0, north=37.0, east=-111.5, south=36.0
    run_gdal([
        "gdal_translate",
        "-of", "COG",
        "-co", "COMPRESS=DEFLATE",
        "-projwin", "-113.0", "37.0", "-111.5", "36.0",
        vrt,
        str(out_dem),
    ])
    # Multidirectional hillshade. -s 111120 converts degree units to meters at
    # the equator (roughly correct at 36N). -z 1.5 exaggerates relief for
    # visual punch.
    run_gdal([
        "gdaldem", "hillshade",
        "-z", "1.5",
        "-s", "111120",
        "-multidirectional",
        "-of", "COG",
        "-co", "COMPRESS=DEFLATE",
        str(out_dem),
        str(out_hs),
    ])


# ---------------------------------------------------------------------------
# 2. NYC PLUTO zoning (Building Footprints + tabular PLUTO join)
# ---------------------------------------------------------------------------

async def fetch_nyc_pluto_zoning(client: httpx.AsyncClient) -> None:
    """Pull NYC Building Footprints (5zhs-2jue) and tabular PLUTO (64uk-42ks)
    via Socrata, then join on mappluto_bbl <-> bbl in Python.

    The single canonical PLUTO Shapefile export endpoint
    (`/api/geospatial/64uk-42ks?method=export&format=Shapefile`) is broken
    (HTTP 500) and direct nyc.gov MapPLUTO links 404 — see RESEARCH.md
    pitfall B for the substitution rationale.

    Output: nyc_pluto_zoning.geojson (final). Intermediate temp files
    (nyc_buildings.geojson, nyc_pluto_tabular.json) are written to the same
    output dir but are gitignored.
    """
    out_final = OUT_DIR / "nyc_pluto_zoning.geojson"
    if already_present(out_final):
        logger.info("nyc_pluto_zoning.geojson already present, skipping")
        return

    out_buildings = OUT_DIR / "nyc_buildings.geojson"
    out_pluto = OUT_DIR / "nyc_pluto_tabular.json"

    # 1) Buildings — Manhattan + Brooklyn waterfront bbox.
    # within_box(field, ymax, xmin, ymin, xmax) per Socrata SoQL.
    buildings_url = (
        "https://data.cityofnewyork.us/resource/5zhs-2jue.geojson"
        "?$where=within_box(the_geom,40.80,-74.05,40.68,-73.90)"
        "&$limit=50000"
    )
    logger.info("Fetching NYC building footprints (Manhattan+Brooklyn waterfront)...")
    r = await client.get(buildings_url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    buildings_fc = r.json()
    out_buildings.write_text(json.dumps(buildings_fc))
    logger.info("  %d buildings", len(buildings_fc.get("features", [])))

    # 2) Tabular PLUTO — Manhattan (MN) + Brooklyn (BK) only.
    pluto_url = (
        "https://data.cityofnewyork.us/resource/64uk-42ks.json"
        "?$select=bbl,landuse,zonedist1,numfloors"
        "&$where=borough%20IN%20('MN','BK')"
        "&$limit=50000"
    )
    logger.info("Fetching tabular PLUTO (MN+BK)...")
    r = await client.get(pluto_url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    pluto_rows = r.json()
    out_pluto.write_text(json.dumps(pluto_rows))
    logger.info("  %d PLUTO rows", len(pluto_rows))

    # 3) Join in Python. mappluto_bbl is on the building feature properties;
    # bbl is the primary key in tabular PLUTO. Both arrive as strings.
    pluto_by_bbl: dict[str, dict] = {}
    for row in pluto_rows:
        bbl = row.get("bbl")
        if not bbl:
            continue
        pluto_by_bbl[str(bbl)] = {
            "landuse": row.get("landuse"),
            "zonedist1": row.get("zonedist1"),
            "numfloors": row.get("numfloors"),
        }

    # height_roof on the buildings feed is in feet (per NYC Open Data
    # documentation). Convert to meters for fill-extrusion-height. Some
    # records have null/missing height_roof — leave height as None and let
    # the paint expression use 0 fallback.
    joined_features = []
    for feat in buildings_fc.get("features", []):
        props = feat.setdefault("properties", {})
        bbl_raw = props.get("mappluto_bbl") or props.get("bbl")
        bbl_key = str(bbl_raw) if bbl_raw is not None else ""
        joined = pluto_by_bbl.get(bbl_key, {})
        props["landuse"] = joined.get("landuse")
        props["zonedist1"] = joined.get("zonedist1")
        props["numfloors"] = joined.get("numfloors")

        height_roof = props.get("height_roof")
        try:
            height_ft = float(height_roof) if height_roof is not None else 0.0
        except (TypeError, ValueError):
            height_ft = 0.0
        # Feet -> meters
        props["height"] = round(height_ft * 0.3048, 2) if height_ft > 0 else 0.0

        joined_features.append(feat)

    out_fc = {"type": "FeatureCollection", "features": joined_features}
    out_final.write_text(json.dumps(out_fc))
    logger.info("Wrote %s with %d features", out_final.name, len(joined_features))


# ---------------------------------------------------------------------------
# 3. 4-state population density tracts (TIGER + ACS)
# ---------------------------------------------------------------------------

async def fetch_pop_density_tracts(client: httpx.AsyncClient) -> None:
    """Combine TIGER cb_2024_us_tract_500k for CA+TX+NY+FL with ACS 2023
    5-year B01003 (population) and B19013 (median household income) into a
    single GeoJSON with computed _pop, _mhi, _density properties.

    Sentinel handling: ACS encodes "no data" as -666666666 etc. Negative
    values and zero population are treated as None so paint expressions can
    `coalesce` to a fallback color.
    """
    out_final = OUT_DIR / "pop_density_tracts.geojson"
    if already_present(out_final):
        logger.info("pop_density_tracts.geojson already present, skipping")
        return

    # 1) Download TIGER zip.
    out_zip = OUT_DIR / "cb_2024_us_tract_500k.zip"
    if not already_present(out_zip):
        zip_url = (
            "https://www2.census.gov/geo/tiger/GENZ2024/shp/"
            "cb_2024_us_tract_500k.zip"
        )
        logger.info("Downloading TIGER cb_2024_us_tract_500k.zip (~58 MB)...")
        async with client.stream("GET", zip_url, timeout=HTTP_TIMEOUT) as resp:
            resp.raise_for_status()
            with out_zip.open("wb") as fh:
                async for chunk in resp.aiter_bytes():
                    fh.write(chunk)

    # 2) Filter + reproject to GeoJSON via ogr2ogr. Try /vsizip first; if it
    # fails, fall back to unzipping then running ogr2ogr against the .shp.
    out_tracts = OUT_DIR / "tracts_4state.geojson"
    if not already_present(out_tracts):
        vsizip_path = f"/vsizip/{out_zip}"
        try:
            run_gdal([
                "ogr2ogr",
                "-f", "GeoJSON",
                "-where", "STATEFP IN ('06','48','36','12')",
                "-t_srs", "EPSG:4326",
                str(out_tracts),
                vsizip_path,
            ])
        except subprocess.CalledProcessError:
            logger.warning("ogr2ogr against /vsizip failed, falling back to extract+run")
            extract_dir = OUT_DIR / "cb_2024_us_tract_500k_extracted"
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(out_zip) as zf:
                zf.extractall(extract_dir)
            shp_files = list(extract_dir.glob("*.shp"))
            if not shp_files:
                raise RuntimeError(
                    f"No .shp file found in {extract_dir} after extraction"
                )
            run_gdal([
                "ogr2ogr",
                "-f", "GeoJSON",
                "-where", "STATEFP IN ('06','48','36','12')",
                "-t_srs", "EPSG:4326",
                str(out_tracts),
                str(shp_files[0]),
            ])

    # 3) Pull ACS rows for the 4 states.
    acs_url = (
        "https://api.census.gov/data/2023/acs/acs5"
        "?get=NAME,B01003_001E,B19013_001E"
        "&for=tract:*"
        "&in=state:06,48,36,12"
    )
    logger.info("Fetching ACS 2023 5-year (B01003 pop, B19013 MHI) for CA+TX+NY+FL...")
    r = await client.get(acs_url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    acs_rows = r.json()
    if not acs_rows or len(acs_rows) < 2:
        raise RuntimeError(f"ACS returned no data rows: {acs_rows!r}")

    header = acs_rows[0]
    idx_pop = header.index("B01003_001E")
    idx_mhi = header.index("B19013_001E")
    idx_state = header.index("state")
    idx_county = header.index("county")
    idx_tract = header.index("tract")

    acs_by_geoid: dict[str, dict] = {}
    for row in acs_rows[1:]:
        geoid = f"{row[idx_state]}{row[idx_county]}{row[idx_tract]}"
        # Population: int if positive, else None.
        try:
            pop = int(row[idx_pop])
            pop_clean = pop if pop > 0 else None
        except (TypeError, ValueError):
            pop_clean = None
        # MHI: int if positive (filters -666666666 sentinel), else None.
        try:
            mhi = int(row[idx_mhi])
            mhi_clean = mhi if mhi > 0 else None
        except (TypeError, ValueError):
            mhi_clean = None
        acs_by_geoid[geoid] = {"pop": pop_clean, "mhi": mhi_clean}

    logger.info("ACS dict built: %d tracts", len(acs_by_geoid))

    # 4) Read tracts geojson, join, compute density.
    tracts_fc = json.loads(out_tracts.read_text())
    n_with_pop = 0
    for feat in tracts_fc.get("features", []):
        props = feat.setdefault("properties", {})
        geoid = props.get("GEOID")
        rec = acs_by_geoid.get(str(geoid)) if geoid else None
        if rec:
            props["_pop"] = rec["pop"]
            props["_mhi"] = rec["mhi"]
        else:
            props["_pop"] = None
            props["_mhi"] = None

        aland = props.get("ALAND")
        try:
            aland_sqkm = float(aland) / 1_000_000.0 if aland else 0.0
        except (TypeError, ValueError):
            aland_sqkm = 0.0
        if props.get("_pop") and aland_sqkm > 0:
            props["_density"] = round(props["_pop"] / aland_sqkm, 2)
            n_with_pop += 1
        else:
            props["_density"] = None

    out_final.write_text(json.dumps(tracts_fc))
    logger.info(
        "Wrote %s with %d features (%d with computed density)",
        out_final.name, len(tracts_fc.get("features", [])), n_with_pop,
    )


# ---------------------------------------------------------------------------
# 4. USGS earthquakes M5+ (5-year window, hardcoded for stability)
# ---------------------------------------------------------------------------

async def fetch_usgs_quakes(client: httpx.AsyncClient) -> None:
    """Single-shot pull of the FDSN earthquake catalog. ~9000 features for
    M5+ over a fixed 5-year window — well under the maxAllowed=20000 limit.

    Window is hardcoded (2021-05-08 to 2026-05-08) for snapshot stability;
    the orchestrator's snapshot_date tracks the matching anchor.
    """
    out = OUT_DIR / "usgs_quakes_m5.geojson"
    if already_present(out):
        logger.info("usgs_quakes_m5.geojson already present, skipping")
        return

    url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    params = {
        "format": "geojson",
        "minmagnitude": 5,
        "starttime": "2021-05-08",
        "endtime": "2026-05-08",
    }
    logger.info("Fetching USGS FDSN earthquakes M5+ 2021-05-08 -> 2026-05-08...")
    r = await client.get(url, params=params, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    fc = r.json()

    # Flatten depth from coords[2] (km) into properties.depth_km so paint
    # expressions can reference it via ["get", "depth_km"].
    for feat in fc.get("features", []):
        coords = feat.get("geometry", {}).get("coordinates") or []
        depth_km = coords[2] if len(coords) > 2 else 0
        feat.setdefault("properties", {})["depth_km"] = depth_km

    out.write_text(json.dumps(fc))
    logger.info("Wrote %s with %d features", out.name, len(fc.get("features", [])))


# ---------------------------------------------------------------------------
# 5. NIFC WFIGS Interagency Perimeters (2020-2024, 10 western states)
# ---------------------------------------------------------------------------

async def fetch_nifc_fires(client: httpx.AsyncClient) -> None:
    """Paginated pull from WFIGS_Interagency_Perimeters (NOT _Current — that
    only has in-season fires per RESEARCH.md pitfall C).

    Filter: 10 western states using attr_POOState IN ('US-CA',...) plus
    attr_FireDiscoveryDateTime in [2020-01-01, 2025-01-01).

    maxRecordCount=2000; expected count ~12k features so 6-7 pages.
    Loop until properties.exceededTransferLimit is falsy.
    """
    out = OUT_DIR / "nifc_fires_2020_2024.geojson"
    if already_present(out):
        logger.info("nifc_fires_2020_2024.geojson already present, skipping")
        return

    base = (
        "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
        "WFIGS_Interagency_Perimeters/FeatureServer/0/query"
    )
    where = (
        "attr_FireDiscoveryDateTime >= timestamp '2020-01-01 00:00:00' AND "
        "attr_FireDiscoveryDateTime <  timestamp '2025-01-01 00:00:00' AND "
        "attr_POOState IN ("
        "'US-CA','US-OR','US-WA','US-ID','US-NV','US-AZ','US-UT','US-MT','US-CO','US-NM'"
        ")"
    )
    all_features: list[dict] = []
    offset = 0
    page = 0
    while True:
        params = {
            "where": where,
            "outFields": "*",
            "f": "geojson",
            "resultRecordCount": 2000,
            "resultOffset": offset,
        }
        logger.info("NIFC page %d (offset=%d)...", page, offset)
        r = await client.get(base, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        fc = r.json()
        page_features = fc.get("features", []) or []
        all_features.extend(page_features)
        exceeded = fc.get("properties", {}).get("exceededTransferLimit")
        if not exceeded:
            break
        offset += 2000
        page += 1
        # Defensive guard so a server-side bug can't loop forever.
        if page > 50:
            logger.warning("NIFC pagination exceeded 50 pages, breaking")
            break

    # Derive fire_year from attr_FireDiscoveryDateTime (epoch ms) for
    # paint-expression access.
    for feat in all_features:
        props = feat.setdefault("properties", {})
        ts = props.get("attr_FireDiscoveryDateTime")
        if ts:
            try:
                props["fire_year"] = datetime.fromtimestamp(
                    int(ts) / 1000, tz=timezone.utc
                ).year
            except (TypeError, ValueError, OSError):
                props["fire_year"] = None
        else:
            props["fire_year"] = None

    out_fc = {"type": "FeatureCollection", "features": all_features}
    out.write_text(json.dumps(out_fc))
    logger.info("Wrote %s with %d features", out.name, len(all_features))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

# Ordered list keeps argparse --only choices stable across runs.
FETCHERS: list[tuple[str, callable]] = [
    ("grand_canyon_dem", fetch_grand_canyon_dem),
    ("nyc_pluto_zoning", fetch_nyc_pluto_zoning),
    ("pop_density_tracts", fetch_pop_density_tracts),
    ("usgs_quakes_m5", fetch_usgs_quakes),
    ("nifc_fires_2020_2024", fetch_nifc_fires),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pre-fetch external data for the GeoLens thematic demo. "
            "Idempotent — skips files already present with non-zero size."
        ),
    )
    parser.add_argument(
        "--only",
        choices=[name for name, _ in FETCHERS],
        help="Run only the named fetcher (instead of all 5).",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.only:
        selected = [(n, fn) for n, fn in FETCHERS if n == args.only]
    else:
        selected = list(FETCHERS)

    failures: list[str] = []
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        for name, fetcher in selected:
            try:
                await fetcher(client)
                print(f"  {name}: ok")
            except Exception as exc:  # noqa: BLE001 — wrap-and-continue is intentional
                logger.exception("Failed %s", name)
                failures.append(name)
                print(f"  {name}: FAILED ({exc})")

    if failures:
        print(
            f"WARNING: {len(failures)} fetch(es) failed: {failures}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
