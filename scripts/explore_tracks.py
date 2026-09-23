import gzip
from collections import Counter

import boto3

import gtfs_realtime_NYCT_pb2 as nyct_pb2
from com.google.transit.realtime import gtfs_realtime_pb2

BUCKET = "mta-rt-raw-jm3635"
PREFIX = "raw/year=2026/month=09/day=15/hour=20/"
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

populated = Counter()
mismatches = Counter()
target_rows = []

for key in keys:
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(gzip.decompress(body))

    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        tid = tu.trip.trip_id
        nyct_trip = tu.trip.Extensions[nyct_pb2.nyct_trip_descriptor]
        ttype = nyct_trip.train_id[0] if nyct_trip.train_id else None

        for stu in tu.stop_time_update:
            ext = stu.Extensions[nyct_pb2.nyct_stop_time_update]
            sched = ext.scheduled_track or None
            actual = ext.actual_track or None

            populated[(sched is not None, actual is not None)] += 1
            if sched and actual and sched != actual:
                mismatches[ttype] += 1

            if tid in TARGETS and stu.stop_id in ("420S", "423S"):
                target_rows.append(
                    (key.rsplit("/", 1)[-1], tid, stu.stop_id, sched, actual)
                )

print("(scheduled_present, actual_present):", dict(populated))
print("mismatches by trip_type:", dict(mismatches))
print(f"\nE outlier trips at 420S/423S: {len(target_rows)} rows")
for row in target_rows[:25]:
    print(" ", row)
