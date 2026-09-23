-- How accurate is an inferred departure time?
--
-- The feed never states that a train departed. A stop is dropped from a
-- trip's stop_time_update list when the train leaves that station, so the
-- departure is inferred from the disappearance, and the departure TIME is
-- taken from the last prediction observed before it vanished.
--
-- Two sources of error stack up:
--   1. Poll interval. The disappearance is only observed at the next poll,
--      up to 30s after it happened. This biases lag positive.
--   2. Prediction drift. The final prediction may sit either side of the
--      poll that last carried it.
--
-- lag_seconds = last_seen_at - departed_at. Positive means the prediction
-- was already in the past when last published; negative means the stop
-- dropped before its predicted time.
--
-- RESULTS (2026-09-16, full day of 2026-09-15, 12.5M observations):
--
--   76,696 departures.  median +12s,  p05 -51s,  p95 +55s
--
-- So inferred departure times are accurate to roughly +/- 1 minute, well
-- inside the resolution needed for headways measured in minutes. The +12s
-- median is the expected poll-interval bias.
--
-- By trip type:
--
--   type  departures    p05  median   p95
--   0         74,116    -51     +12   +53
--   E          1,623   -110     +14   +93
--   /            654    -45     +12  +417
--   =            247     +4     +30  +122
--   $             56     +3     +48  +671
--
-- The / and $ tails confirm the skip-stop hypothesis independently of the
-- designator: a skipped stop vanishes while its prediction is still minutes
-- in the future and never converged, so lag runs far wider than for normal
-- service. That gives two independent signals for a skip (the designator,
-- and an outlying lag), either of which may catch what the other misses.
--
-- E is mildly wider than type 0 but otherwise normal, which is more
-- evidence it is real service rather than a planning artifact.
--
-- These percentiles are the error bar on every headway derived downstream
-- and belong in the README's data-quality section.

-- ---------------------------------------------------------------------------
-- 1. Overall lag distribution.
-- ---------------------------------------------------------------------------

WITH last_obs AS (
  SELECT DISTINCT ON (trip_id, start_date, stop_id)
         trip_id, start_date, route_id, stop_id, station_id, direction,
         trip_type, is_assigned,
         coalesce(departure_time, arrival_time) AS departed_at,
         fetched_at                             AS last_seen_at
  FROM observations
  ORDER BY trip_id, start_date, stop_id, fetched_at DESC
),
trip_end AS (
  SELECT trip_id, start_date, max(fetched_at) AS trip_last_poll
  FROM observations
  GROUP BY trip_id, start_date
),
departed AS (
  SELECT l.*,
         extract(epoch FROM (l.last_seen_at - l.departed_at)) AS lag_seconds
  FROM last_obs l
  JOIN trip_end t USING (trip_id, start_date)
  -- A stop still listed in the trip's final poll never disappeared; the
  -- observation window ended, not the trip.
  WHERE l.last_seen_at < t.trip_last_poll
    AND l.is_assigned
    AND l.departed_at IS NOT NULL
)
SELECT count(*)                                                         AS departures,
       round(min(lag_seconds))                                          AS min_lag,
       round(percentile_cont(0.05) WITHIN GROUP (ORDER BY lag_seconds)) AS p05,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY lag_seconds)) AS median,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY lag_seconds)) AS p95,
       round(max(lag_seconds))                                          AS max_lag
FROM departed;

-- ---------------------------------------------------------------------------
-- 2. Same, split by trip type.
-- ---------------------------------------------------------------------------

WITH last_obs AS (
  SELECT DISTINCT ON (trip_id, start_date, stop_id)
         trip_id, start_date, stop_id, trip_type, is_assigned,
         coalesce(departure_time, arrival_time) AS departed_at,
         fetched_at                             AS last_seen_at
  FROM observations
  ORDER BY trip_id, start_date, stop_id, fetched_at DESC
),
trip_end AS (
  SELECT trip_id, start_date, max(fetched_at) AS trip_last_poll
  FROM observations
  GROUP BY trip_id, start_date
),
departed AS (
  SELECT l.trip_type,
         extract(epoch FROM (l.last_seen_at - l.departed_at)) AS lag_seconds
  FROM last_obs l
  JOIN trip_end t USING (trip_id, start_date)
  WHERE l.last_seen_at < t.trip_last_poll
    AND l.is_assigned
    AND l.departed_at IS NOT NULL
)
SELECT trip_type,
       count(*)                                                         AS departures,
       round(percentile_cont(0.05) WITHIN GROUP (ORDER BY lag_seconds)) AS p05,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY lag_seconds)) AS median,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY lag_seconds)) AS p95
FROM departed
GROUP BY trip_type
ORDER BY departures DESC;

-- ---------------------------------------------------------------------------
-- 3. Outliers.
--
-- The full-day run produced a min of -2735s and a max of +2348s, both about
-- 45 minutes, which neither the poll interval nor ordinary prediction drift
-- explains. Candidates: trips truncated by a collection-window boundary,
-- assignment reversals (see queries/assignment_reversals.sql), and stalled
-- trains, whose predictions stop updating entirely while the train sits
-- (the spec says to detect this by comparing the VehiclePosition timestamp
-- against the feed header timestamp, ~90s being the suggested threshold).
--
-- Whatever they turn out to be, a lag threshold is likely the right filter
-- before computing headways.
-- ---------------------------------------------------------------------------

WITH last_obs AS (
  SELECT DISTINCT ON (trip_id, start_date, stop_id)
         trip_id, start_date, route_id, stop_id, trip_type, is_assigned,
         coalesce(departure_time, arrival_time) AS departed_at,
         fetched_at                             AS last_seen_at
  FROM observations
  ORDER BY trip_id, start_date, stop_id, fetched_at DESC
),
trip_end AS (
  SELECT trip_id, start_date, max(fetched_at) AS trip_last_poll
  FROM observations
  GROUP BY trip_id, start_date
),
departed AS (
  SELECT l.trip_id, l.route_id, l.stop_id, l.trip_type,
         l.departed_at, l.last_seen_at,
         extract(epoch FROM (l.last_seen_at - l.departed_at)) AS lag_seconds
  FROM last_obs l
  JOIN trip_end t USING (trip_id, start_date)
  WHERE l.last_seen_at < t.trip_last_poll
    AND l.is_assigned
    AND l.departed_at IS NOT NULL
)
SELECT trip_id, route_id, stop_id, trip_type,
       departed_at, last_seen_at, lag_seconds
FROM departed
WHERE abs(lag_seconds) > 600
ORDER BY abs(lag_seconds) DESC
LIMIT 20;

-- ---------------------------------------------------------------------------
-- 4. How much data would a lag threshold discard?
-- ---------------------------------------------------------------------------

WITH last_obs AS (
  SELECT DISTINCT ON (trip_id, start_date, stop_id)
         trip_id, start_date, stop_id, is_assigned,
         coalesce(departure_time, arrival_time) AS departed_at,
         fetched_at                             AS last_seen_at
  FROM observations
  ORDER BY trip_id, start_date, stop_id, fetched_at DESC
),
trip_end AS (
  SELECT trip_id, start_date, max(fetched_at) AS trip_last_poll
  FROM observations
  GROUP BY trip_id, start_date
),
departed AS (
  SELECT extract(epoch FROM (l.last_seen_at - l.departed_at)) AS lag_seconds
  FROM last_obs l
  JOIN trip_end t USING (trip_id, start_date)
  WHERE l.last_seen_at < t.trip_last_poll
    AND l.is_assigned
    AND l.departed_at IS NOT NULL
)
SELECT count(*)                                        AS total,
       count(*) FILTER (WHERE abs(lag_seconds) > 120)  AS beyond_2min,
       count(*) FILTER (WHERE abs(lag_seconds) > 300)  AS beyond_5min,
       count(*) FILTER (WHERE abs(lag_seconds) > 600)  AS beyond_10min,
       round(100.0 * count(*) FILTER (WHERE abs(lag_seconds) > 120)
             / count(*), 2)                            AS pct_beyond_2min
FROM departed;