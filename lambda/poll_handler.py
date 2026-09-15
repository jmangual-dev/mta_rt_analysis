"""
Lambda handler: fetch one MTA GTFS-RT snapshot and archive it to S3.

Deliberately dependency-free. urllib is stdlib and boto3 ships with the
Lambda runtime, so this deploys as a single pasted file with no build step.

Invoked twice a minute by two EventBridge schedules offset 30 seconds apart.
Each invocation is independent; neither waits on the other.
"""

import gzip
import os
import urllib.request
from datetime import datetime, timezone

import boto3

URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs"
BUCKET = os.environ["BUCKET"]
TIMEOUT = 10

# Created at module scope so warm invocations reuse the client and its
# resolved credentials instead of rebuilding both every call.
s3 = boto3.client("s3")


def lambda_handler(event, context):
    with urllib.request.urlopen(URL, timeout=TIMEOUT) as response:
        content = response.read()

    now = datetime.now(timezone.utc)
    key = (
        f"raw/year={now:%Y}/month={now:%m}/day={now:%d}/hour={now:%H}"
        f"/{int(now.timestamp())}.pb.gz"
    )
    body = gzip.compress(content)

    s3.put_object(Bucket=BUCKET, Key=key, Body=body)

    # print goes to CloudWatch Logs automatically; no logging config needed.
    print(f"{key} {len(content)} -> {len(body)}")

    return {"key": key, "raw_bytes": len(content), "gz_bytes": len(body)}
