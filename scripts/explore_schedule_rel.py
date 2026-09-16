import gzip
from collections import Counter

import boto3
from google.transit import gtfs_realtime_pb2

BUCKET = "mta-rt-raw-jm3635"
s3 = boto3.Session(profile_name="loader").client("s3")

keys = []
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=BUCKET, Prefix="raw/"):
    keys.extend(o["Key"] for o in page.get("Contents", []))
keys.sort()
print(f"{len(keys)} objects")

stop_rel = Counter()
trip_rel = Counter()

for i, key in enumerate(keys, 1):
    if i % 200 == 0:
        print(f"{i}/{len(keys)}", flush=True)

    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(gzip.decompress(body))

    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        trip_rel[tu.trip.schedule_relationship] += 1
        for stu in tu.stop_time_update:
            stop_rel[stu.schedule_relationship] += 1

print("trip schedule_relationship:", dict(trip_rel))
print("stop schedule_relationship:", dict(stop_rel))
