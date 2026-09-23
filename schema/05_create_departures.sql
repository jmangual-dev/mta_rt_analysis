-- One row per train departure from a platform, inferred from a stop
-- disappearing from its trip's stop_time_update list.
--
-- Only assigned trips count (an unassigned trip is published but often
-- never runs). departed_at is the last prediction observed before the stop
-- vanished; last_seen_at is the poll that carried it. The gap between them
-- is bounded at 120s: measured p05/p95 across a full day is -51/+55s, and
-- 3.04% of candidates fall outside +/-120s, split between delayed trains
-- whose predictions froze and trips withdrawn before running.
--
-- trip_type is kept per row rather than filtered here: /, =, and $ mark
-- service modifications and are excluded at query time, not at load time.

CREATE TABLE departures (
    id           bigserial   PRIMARY KEY,
    trip_id      text        NOT NULL,
    start_date   date        NOT NULL,
    route_id     text        NOT NULL,
    stop_id      text        NOT NULL,
    station_id   text        NOT NULL,
    direction    text        NOT NULL,
    trip_type    char(1),
    departed_at  timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    lag_seconds  integer     NOT NULL,
    UNIQUE (trip_id, start_date, stop_id)
);

CREATE INDEX departures_stop_departed
    ON departures (stop_id, departed_at);