#!/usr/bin/env python3
"""Upload a backup file to S3-compatible storage."""
import os
import sys

import boto3
from botocore.config import Config


def upload_backup(filepath: str) -> str:
    """Upload backup file to S3 and return the S3 URI."""
    endpoint = os.environ.get("S3_ENDPOINT")
    bucket = os.environ["S3_BUCKET"]
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
        s3={"addressing_style": os.environ.get("S3_ADDRESSING_STYLE", "auto")},
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

    client = boto3.client(**kwargs)
    filename = os.path.basename(filepath)
    key = f"backups/{filename}"

    client.upload_file(filepath, bucket, key)
    return f"s3://{bucket}/{key}"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <backup-file>", file=sys.stderr)
        sys.exit(1)
    uri = upload_backup(sys.argv[1])
    print(f"Uploaded: {uri}")
