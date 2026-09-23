import gzip
from collections import Counter

import boto3

import gtfs_realtime_NYCT_pb2 as nyct_pb2  # noqa: F401 - registers extensions
from com.google.transit.realtime import gtfs_realtime_pb2

BUCKET = "mta-rt-raw-jm3635"
PREFIX = "raw/year=2026/month=09/day=15/hour=20/"  # 16:00-17:00 ET
TARGETS = {
    "095750_5..S",
    "098600_5..S",
    "097900_5..S",
    "094700_5..S",
    "096500_5..S",
    "096900_5..S",
}

s3 = boto3.Session(profile_name="loader").client("s3")

keys = []
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
    keys.extend(o["Key"] for o in page.get("Contents", []))
keys.sort()
print(f"{len(keys)} objects")

alert_count = 0
alerted_trips = Counter()
target_hits = []

for key in keys:
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(gzip.decompress(body))

    for e in feed.entity:
        if not e.HasField("alert"):
            continue
        alert_count += 1
        text = " ".join(t.text for t in e.alert.header_text.translation)
        for ie in e.alert.informed_entity:
            tid = ie.trip.trip_id
            alerted_trips[tid] += 1
            if tid in TARGETS:
                target_hits.append((key.rsplit("/", 1)[-1], tid, text))

print(f"alert entities: {alert_count}")
print(f"distinct alerted trips: {len(alerted_trips)}")
print("\ntop alerted trips:")
for tid, n in alerted_trips.most_common(10):
    print(f"  {tid:<20} {n}")

print(f"\nhits on the E outlier trips: {len(target_hits)}")
for row in target_hits[:20]:
    print(" ", row)
