-- Materialize departures from observations.
--
-- Run after loading observations; safe to re-run (ON CONFLICT DO NOTHING).
--   psql mta_rt -f queries/insert_departures.sql
--
-- The feed never states that a train departed. A stop is dropped from a
-- trip's stop_time_update list when the train leaves that station, so a
-- departure is inferred from the disappearance, and the departure TIME is
-- the last prediction observed before it vanished.
--
-- Four conditions, each established against real data (see docs/decisions.md):
--
--   1. is_assigned must be true AT THAT POLL. An unassigned trip is
--      published up to 30 minutes ahead and frequently never runs
--      (063100_2..N02R: 55 polls, all 48 stops, no vehicle, never moved).
--      Assignment is evaluated per row, not per trip, because 82.78% of
--      trips flip during their life.
--
--   2. The stop must not still be present in the trip's final poll.
--      Otherwise the observation window ended, not the trip.
--
--   3. |lag| <= 120s. Measured p05/p95 is -51/+55s; 3.04% of candidates
--      fall outside +/-120s, and those split cleanly into two causes:
--      delayed trains whose predictions froze (positive lag, and these
--      carry Alert entities), and trips withdrawn before running (negative
--      lag, no alerts). Neither is normal service.
--
--   4. A departure time must exist. departure_time is preferred, falling
--      back to arrival_time: the spec supplies departure at the origin
--      terminal, arrival at the destination, and transit times between.
--
-- NOT filtered here: trip_type. The /, =, and $ designators mark service
-- modifications (skip stop, reroute, turn train) applied to trains already
-- running, and a stop vanishing from one of those may be a skip rather than
-- a departure. They are stored and excluded at query time instead, because
-- a trip can be redesignated mid-run and its earlier departures are real.
--
-- KNOWN GAP: 3.8% of trips reverse assignment (true -> false), and in at
-- least one observed case a departed stop REAPPEARED in the trip's list
-- when its route was reset (074250_2..S02R, 48 -> 47 -> 48 stops). This
-- script takes the last observation of each stop, so a reappearance means
-- the stop looks present at the end and condition 2 excludes it. That is
-- the conservative outcome (a real departure is dropped rather than a
-- phantom recorded), but it is not deliberate handling. Revisit.

INSERT INTO departures (
    trip_id, start_date, route_id, stop_id, station_id, direction,
    trip_type, departed_at, last_seen_at, lag_seconds
)
WITH last_obs AS (
    -- The final observation of each stop within each trip.
    SELECT DISTINCT ON (trip_id, start_date, stop_id)
           trip_id,
           start_date,
           route_id,
           stop_id,
           station_id,
           direction,
           trip_type,
           is_assigned,
           coalesce(departure_time, arrival_time) AS departed_at,
           fetched_at                             AS last_seen_at
    FROM observations
    ORDER BY trip_id, start_date, stop_id, fetched_at DESC
),
trip_end AS (
    SELECT trip_id,
           start_date,
           max(fetched_at) AS trip_last_poll
    FROM observations
    GROUP BY trip_id, start_date
)
SELECT l.trip_id,
       l.start_date,
       l.route_id,
       l.stop_id,
       l.station_id,
       l.direction,
       l.trip_type,
       l.departed_at,
       l.last_seen_at,
       round(extract(epoch FROM (l.last_seen_at - l.departed_at)))::integer
FROM last_obs l
JOIN trip_end t USING (trip_id, start_date)
WHERE l.is_assigned                                    -- condition 1
  AND l.last_seen_at < t.trip_last_poll                -- condition 2
  AND l.departed_at IS NOT NULL                        -- condition 4
  AND abs(extract(epoch FROM (l.last_seen_at - l.departed_at))) <= 120
ON CONFLICT DO NOTHING;