"""
Load raw GTFS-RT payloads from S3 into Postgres.

Usage:
    python load.py raw/year=2026/month=09/day=15/hour=16/
    python load.py raw/year=2026/month=09/day=15/

Idempotent: re-running over the same prefix inserts nothing new, so an
interrupted run can simply be repeated.
"""

import gzip
import sys
from datetime import datetime, timezone

import boto3
import psycopg
from google.transit import gtfs_realtime_pb2

BUCKET = "mta-rt-raw-jm3635"
DSN = "dbname=mta_rt"

OBS_SQL = """
    INSERT INTO observations
        (fetched_at, feed_timestamp, trip_id, start_date, route_id,
         stop_id, station_id, direction, arrival_time, departure_time,
         source_key)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""

VEH_SQL = """
    INSERT INTO vehicles
        (fetched_at, feed_timestamp, vehicle_timestamp, trip_id, start_date,
         route_id, stop_id, station_id, direction, current_stop_sequence,
         current_status, source_key)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
"""


def ts(epoch):
    """Unix epoch to aware datetime. Zero and None both mean absent."""
    return datetime.fromtimestamp(epoch, timezone.utc) if epoch else None


def fetched_at_from_key(key):
    """Capture time is encoded in the object name: .../<epoch>.pb.gz"""
    epoch = int(key.rsplit("/", 1)[-1].split(".")[0])
    return datetime.fromtimestamp(epoch, timezone.utc)


def service_date(s):
    """Feed gives start_date as 'YYYYMMDD'."""
    return datetime.strptime(s, "%Y%m%d").date()


def split_stop(stop_id):
    """'111N' -> ('111', 'N'). Verified 4 chars with N/S suffix across
    7.4M observations, but guard anyway rather than corrupt a row."""
    if len(stop_id) < 2 or stop_id[-1] not in ("N", "S"):
        return stop_id, None
    return stop_id[:-1], stop_id[-1]


def parse(body, key):
    """Decode one payload into (observation rows, vehicle rows)."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(gzip.decompress(body))

    fetched = fetched_at_from_key(key)
    feed_ts = ts(feed.header.timestamp)

    obs_rows = []
    veh_rows = []

    for entity in feed.entity:
        if entity.HasField("vehicle"):
            v = entity.vehicle
            stop_id = v.stop_id if v.HasField("stop_id") else None
            station, direction = split_stop(stop_id) if stop_id else (None, None)
            veh_rows.append((
                fetched,
                feed_ts,
                ts(v.timestamp),
                v.trip.trip_id,
                service_date(v.trip.start_date),
                v.trip.route_id,
                stop_id,
                station,
                direction,
                v.current_stop_sequence,
                v.current_status if v.HasField("current_status") else None,
                key,
            ))
            continue

        if not entity.HasField("trip_update"):
            continue

        tu = entity.trip_update
        trip_id = tu.trip.trip_id
        start = service_date(tu.trip.start_date)
        route = tu.trip.route_id

        for stu in tu.stop_time_update:
            station, direction = split_stop(stu.stop_id)
            obs_rows.append((
                fetched,
                feed_ts,
                trip_id,
                start,
                route,
                stu.stop_id,
                station,
                direction,
                ts(stu.arrival.time) if stu.HasField("arrival") else None,
                ts(stu.departure.time) if stu.HasField("departure") else None,
                key,
            ))

    return obs_rows, veh_rows


def main(prefix):
    s3 = boto3.Session(profile_name="loader").client("s3")

    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    keys.sort()

    if not keys:
        print(f"no objects under {prefix}")
        return

    print(f"{len(keys)} objects under {prefix}")

    total_obs = total_veh = skipped = 0

    with psycopg.connect(DSN) as conn:
        for i, key in enumerate(keys, 1):
            try:
                body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
                obs_rows, veh_rows = parse(body, key)
            except Exception as exc:
                skipped += 1
                print(f"skip {key}: {exc}", flush=True)
                continue

            # One transaction per object, so an interrupted run always
            # leaves a clean object boundary to resume from.
            with conn.cursor() as cur:
                cur.executemany(OBS_SQL, obs_rows)
                cur.executemany(VEH_SQL, veh_rows)
            conn.commit()

            total_obs += len(obs_rows)
            total_veh += len(veh_rows)

            if i % 50 == 0:
                print(f"{i}/{len(keys)}  obs={total_obs}  veh={total_veh}",
                      flush=True)

    print(f"done: {total_obs} observations, {total_veh} vehicles, "
          f"{skipped} objects skipped")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python load.py <s3-prefix>")
    main(sys.argv[1])