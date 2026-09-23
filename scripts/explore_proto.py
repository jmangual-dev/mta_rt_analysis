import gzip
from collections import Counter

import boto3

import gtfs_realtime_NYCT_pb2 as nyct_pb2
from com.google.transit.realtime import gtfs_realtime_pb2

BUCKET = "mta-rt-raw-jm3635"
TARGET = "063100_2..N02R"
s3 = boto3.Session(profile_name="loader").client("s3")

keys = []

# paginator = s3.get_paginator("list_objects_v2")
# for page in paginator.paginate(Bucket=BUCKET, Prefix="raw/"):
#     keys.extend(o["Key"] for o in page.get("Contents", []))

# that trip was seen 12:00-12:27 ET on 9/15, which is hour=16 UTC
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(
    Bucket=BUCKET, Prefix="raw/year=2026/month=09/day=15/hour=16/"
):
    keys.extend(o["Key"] for o in page.get("Contents", []))

keys.sort()
print(f"{len(keys)} objects")

trip_types = Counter()
assigned = Counter()
empty_train_id = 0

# for i, key in enumerate(keys, 1):
#     if i % 200 == 0:
#         print(f"{i}/{len(keys)}", flush=True)

#     body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
#     feed = gtfs_realtime_pb2.FeedMessage()
#     feed.ParseFromString(gzip.decompress(body))

#     for e in feed.entity:
#         if not e.HasField("trip_update"):
#             continue
#         tu = e.trip_update
#         nyct = tu.trip.Extensions[nyct_pb2.nyct_trip_descriptor]
#         assigned[nyct.is_assigned] += 1
#         if nyct.train_id:
#             trip_types[nyct.train_id[0]] += 1
#         else:
#             empty_train_id += 1

# print("trip type designators:", dict(sorted(trip_types.items())))
# print("is_assigned:", dict(assigned))
# print("empty train_id:", empty_train_id)

for key in keys:
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(gzip.decompress(body))

    for e in feed.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        if tu.trip.trip_id != TARGET:
            continue
        nyct = tu.trip.Extensions[nyct_pb2.nyct_trip_descriptor]
        print(
            f"{key.rsplit('/', 1)[-1]:<20} "
            f"assigned={nyct.is_assigned} "
            f"train_id={nyct.train_id!r} "
            f"stops={len(tu.stop_time_update)}"
        )
        break
