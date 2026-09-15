import gzip
from collections import Counter

import boto3
from google.transit import gtfs_realtime_pb2

BUCKET = "mta-rt-raw-jm3635"
s3 = boto3.Session(profile_name="loader").client("s3")

# collect all keys
keys = []
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=BUCKET, Prefix="raw/"):
    keys.extend(o["Key"] for o in page.get("Contents", []))

keys.sort()
print(f"{len(keys)} objects")

routes, dirs, lengths = Counter(), Counter(), Counter()
trips, stops = set(), set()
missing_route = 0
bad = 0

status = Counter()
v_missing_status = 0
v_missing_stop = 0
v_missing_seq = 0
v_missing_ts = 0
vehicle_count = 0

for i, key in enumerate(keys, 1):
    if i % 100 == 0:
        print(f"{i}/{len(keys)}", flush=True)

    try:
        body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(gzip.decompress(body))
    except Exception as ex:
        bad += 1
        print(f"skip {key}: {ex}", flush=True)
        continue

    for e in feed.entity:
        if e.HasField("vehicle"):
            v = e.vehicle
            vehicle_count += 1
            if v.HasField("current_status"):
                status[v.current_status] += 1
            else:
                v_missing_status += 1
            if not v.HasField("stop_id"):
                v_missing_stop += 1
            if not v.HasField("current_stop_sequence"):
                v_missing_seq += 1
            if not v.HasField("timestamp"):
                v_missing_ts += 1
            continue
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        trips.add((tu.trip.trip_id, tu.trip.start_date))
        if tu.trip.HasField("route_id"):
            routes[tu.trip.route_id] += 1
        else:
            missing_route += 1
        for stu in tu.stop_time_update:
            stops.add(stu.stop_id)
            dirs[stu.stop_id[-1]] += 1
            lengths[len(stu.stop_id)] += 1

print("routes:", dict(sorted(routes.items())))
print("missing route_id:", missing_route)
print("direction suffixes:", dict(dirs))
print("stop_id lengths:", dict(lengths))
print("distinct trips:", len(trips))
print("distinct stops:", len(stops))
print("bad_objects:", bad)
print("vehicle entities:", vehicle_count)
print("current_status values:", dict(status))
print(
    "missing status/stop/seq/ts:",
    v_missing_status,
    v_missing_stop,
    v_missing_seq,
    v_missing_ts,
)
