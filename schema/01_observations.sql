-- One row per stop prediction per poll. Append-only; never updated.
-- Unique key makes reloading the same S3 object a no-op, so partial
-- runs can be re-run safely.
-- stop_id is kept verbatim from the feed ("111N"); station_id and
-- direction are derived for querying.

CREATE TABLE observations (
    id              bigserial PRIMARY KEY,
    fetched_at      timestamptz NOT NULL,
    feed_timestamp  timestamptz NOT NULL,
    trip_id         text        NOT NULL,
    start_date      date        NOT NULL,
    route_id        text        NOT NULL,
    stop_id         text        NOT NULL,
    station_id      text        NOT NULL,
    direction       text        NOT NULL,
    arrival_time    timestamptz,
    departure_time  timestamptz,
    source_key      text        NOT NULL,
    UNIQUE (fetched_at, trip_id, start_date, stop_id)
);
