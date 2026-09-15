-- current_status is NULL when the feed omits it (~38% of entities).
-- Absent almost certainly means IN_TRANSIT_TO, which is the proto3
-- default and therefore not serialized. Recorded as NULL rather than
-- coerced to 2, since that is an interpretation.

CREATE TABLE vehicles (
    id                    bigserial PRIMARY KEY,
    fetched_at            timestamptz NOT NULL,
    feed_timestamp        timestamptz NOT NULL,
    vehicle_timestamp     timestamptz NOT NULL,
    trip_id               text        NOT NULL,
    start_date            date        NOT NULL,
    route_id              text        NOT NULL,
    stop_id               text,
    station_id            text,
    direction             text,
    current_stop_sequence integer     NOT NULL,
    current_status        integer,
    source_key            text        NOT NULL,
    UNIQUE (fetched_at, trip_id, start_date)
);