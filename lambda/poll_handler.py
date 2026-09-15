"""
Lambda handler: fetch one MTA GTFS-RT snapshot and archive it to S3.

Deliberately dependency-free. urllib is stdlib and boto3 ships with the
Lambda runtime, so this deploys as a single pasted file with no build step.

Invoked once a minute by an EventBridge schedule. Each invocation fetches
twice, 30 seconds apart, because Scheduler's minimum granularity is one
minute and sub-minute offsets are not expressible.
"""

import gzip
import os
import time
import urllib.request
from datetime import datetime, timezone

import boto3

URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs"
BUCKET = os.environ["BUCKET"]
TIMEOUT = 10

# Created at module scope so warm invocations reuse the client and its
# resolved credentials instead of rebuilding both every call.
s3 = boto3.client("s3")


def fetch_and_store():
    with urllib.request.urlopen(URL, timeout=TIMEOUT) as response:
        content = response.read()
    now = datetime.now(timezone.utc)
    key = (
        f"raw/year={now:%Y}/month={now:%m}/day={now:%d}/hour={now:%H}"
        f"/{int(now.timestamp())}.pb.gz"
    )
    body = gzip.compress(content)
    s3.put_object(Bucket=BUCKET, Key=key, Body=body)
    print(f"{key} {len(content)} -> {len(body)}")
    return key


def lambda_handler(event, context):
    first = fetch_and_store()
    time.sleep(30)
    second = fetch_and_store()
    return {"keys": [first, second]}
