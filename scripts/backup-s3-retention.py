#!/usr/bin/env python3
"""Enforce count-based retention on S3 backup files."""
import os
import sys
from datetime import datetime

import boto3
from botocore.config import Config


def get_s3_client():
    """Create S3 client from environment variables."""
    endpoint = os.environ.get("S3_ENDPOINT")
    region = os.environ.get("S3_REGION", "us-east-1")
    allow_http = os.environ.get("S3_ALLOW_HTTP", "false").lower() == "true"

    endpoint_url = None
    if endpoint:
        if not endpoint.startswith("http"):
            scheme = "http" if allow_http else "https"
            endpoint_url = f"{scheme}://{endpoint}"
        else:
            endpoint_url = endpoint

    config = Config(
        s3={"addressing_style": "path"},
        retries={"max_attempts": 3, "mode": "adaptive"},
    )

    kwargs = {
        "service_name": "s3",
        "region_name": region,
        "config": config,
    }
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if os.environ.get("S3_ACCESS_KEY_ID"):
        kwargs["aws_access_key_id"] = os.environ["S3_ACCESS_KEY_ID"]
    if os.environ.get("S3_SECRET_ACCESS_KEY"):
        kwargs["aws_secret_access_key"] = os.environ["S3_SECRET_ACCESS_KEY"]

    return boto3.client(**kwargs)


def enforce_retention():
    bucket = os.environ["S3_BUCKET"]
    daily_keep = int(os.environ.get("BACKUP_RETENTION_DAILY", "7"))
    weekly_keep = int(os.environ.get("BACKUP_RETENTION_WEEKLY", "4"))

    client = get_s3_client()

    # List all backup objects
    response = client.list_objects_v2(Bucket=bucket, Prefix="backups/")
    if "Contents" not in response:
        return

    # Sort by key descending (newest first -- timestamp in filename)
    objects = sorted(response["Contents"], key=lambda o: o["Key"], reverse=True)

    daily = []
    weekly = []
    for obj in objects:
        key = obj["Key"]
        filename = key.split("/")[-1]
        if not filename.endswith(".dump"):
            continue
        # Extract date: geolens_20260302_020000.dump -> 20260302
        try:
            date_part = filename.split("_")[1]
            dt = datetime.strptime(date_part, "%Y%m%d")
            if dt.weekday() == 6:  # Sunday
                weekly.append(key)
            else:
                daily.append(key)
        except (IndexError, ValueError):
            daily.append(key)  # Unknown format -> treat as daily

    # Delete excess
    deleted = 0
    for key in daily[daily_keep:]:
        client.delete_object(Bucket=bucket, Key=key)
        print(f"Deleted S3 daily backup: {key}")
        deleted += 1

    for key in weekly[weekly_keep:]:
        client.delete_object(Bucket=bucket, Key=key)
        print(f"Deleted S3 weekly backup: {key}")
        deleted += 1

    if deleted:
        print(f"S3 retention: deleted {deleted} old backup(s)")


if __name__ == "__main__":
    enforce_retention()
