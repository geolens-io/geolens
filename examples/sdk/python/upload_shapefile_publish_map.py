#!/usr/bin/env python3
"""Upload a zipped Shapefile with the GeoLens SDK client and publish a map.

Expected output:
  dataset_id=<uuid>
  map_id=<uuid>
  share_url=/m/<token>

Environment:
  GEOLENS_BASE_URL defaults to http://localhost:8080/api
  GEOLENS_TOKEN or GEOLENS_API_KEY authenticates the request
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from geolens import GeolensClient


def build_client(base_url: str) -> GeolensClient:
    bearer_token = os.environ.get("GEOLENS_TOKEN")
    api_key = os.environ.get("GEOLENS_API_KEY")
    if bearer_token:
        return GeolensClient(base_url=base_url, bearer_token=bearer_token)
    if api_key:
        return GeolensClient(base_url=base_url, api_key=api_key)
    raise SystemExit("Set GEOLENS_TOKEN or GEOLENS_API_KEY before running this example.")


def request_json(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected JSON object, got {type(data).__name__}")
    return data


def wait_for_ingest(http: httpx.Client, job_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = request_json(http.get(f"/jobs/{job_id}"))
        if status["status"] == "complete":
            return status
        if status["status"] == "failed":
            raise RuntimeError(status.get("error_message") or f"Ingest job {job_id} failed")
        time.sleep(3)
    raise TimeoutError(f"Ingest job {job_id} did not complete within {timeout_seconds}s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("shapefile_zip", type=Path, help="Path to a zipped Shapefile")
    parser.add_argument("--title", default="SDK uploaded Shapefile")
    parser.add_argument("--summary", default="Uploaded through examples/sdk/python/upload_shapefile_publish_map.py")
    parser.add_argument("--map-name", default="SDK Shapefile Map")
    parser.add_argument("--base-url", default=os.environ.get("GEOLENS_BASE_URL", "http://localhost:8080/api"))
    parser.add_argument("--layer-name", default=None, help="Optional layer name for multi-layer archives")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    if not args.shapefile_zip.is_file():
        raise SystemExit(f"File not found: {args.shapefile_zip}")

    sdk = build_client(args.base_url)
    http = sdk.client.get_httpx_client()

    with args.shapefile_zip.open("rb") as source:
        upload = request_json(
            http.post(
                "/ingest/upload",
                files={"file": (args.shapefile_zip.name, source, "application/zip")},
            )
        )
    job_id = upload["job_id"]

    preview = request_json(http.post(f"/ingest/preview/{job_id}"))
    commit_body: dict[str, Any] = {
        "title": args.title,
        "summary": args.summary,
        "visibility": "public",
    }
    if args.layer_name:
        commit_body["layer_name"] = args.layer_name
    elif preview.get("layer_name"):
        commit_body["layer_name"] = preview["layer_name"]

    request_json(http.post(f"/ingest/commit/{job_id}", json=commit_body))
    completed = wait_for_ingest(http, job_id, args.timeout_seconds)
    dataset_id = completed["dataset_id"]
    if not dataset_id:
        raise RuntimeError(f"Ingest job {job_id} completed without a dataset_id")

    created_map = request_json(
        http.post(
            "/maps/",
            json={
                "name": args.map_name,
                "description": f"Published map for {args.title}",
            },
        )
    )
    map_id = created_map["id"]

    request_json(
        http.post(
            f"/maps/{map_id}/layers/",
            json={
                "dataset_id": dataset_id,
                "display_name": args.title,
                "sort_order": 0,
                "visible": True,
                "opacity": 1.0,
            },
        )
    )
    request_json(http.put(f"/maps/{map_id}", json={"visibility": "public"}))
    share = request_json(http.post(f"/maps/{map_id}/share/", json={}))

    print(f"dataset_id={dataset_id}")
    print(f"map_id={map_id}")
    print(f"share_url={share.get('share_url')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
