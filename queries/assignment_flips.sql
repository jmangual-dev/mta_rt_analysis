-- Poll-by-poll timeline for trips whose is_assigned reverses (true -> false).
--
-- Drill-down, not a routine check. Output is one row per trip per poll and
-- runs to tens of thousands of rows over a full day. Use
-- queries/assignment_rates.sql for the rate; use this to understand a
-- specific case. Redirect to a file: psql mta_rt -f ... > reversals.txt
--
-- Finding (2026-09-16, one hour of 2026-09-15): 3 of 595 trips reversed,
-- and none of the three was a single-poll blip. All were sustained:
--   074250_2..S02R  assigned 12:01, departed a stop at 12:04 (48 -> 47
--                   stops), unassigned at 12:10 AND THE STOP LIST RETURNED
--                   TO 48.
--   074950_3..S06R  assigned ~5 min, never moved, reverted to unassigned.
--   075750_3..S06R  assigned ~8 min, never moved, reverted to unassigned.
--
-- The first case is the one that matters for departure detection: a stop
-- that has disappeared can REAPPEAR when a trip's assignment is withdrawn
-- and its route is reset to the full plan. Detection therefore cannot treat
-- a single disappearance as final. Require the stop to stay absent (or take
-- the trip's last poll as authoritative) before recording a departure.
--
-- Operationally this reads as a work program being revoked: the spec
-- describes trains at a terminal being assigned or moved to storage, and
-- this is that in reverse.

SELECT trip_id,
       fetched_at,
       is_assigned,
       count(*) AS stops
FROM observations
WHERE trip_id IN (
  SELECT trip_id
  FROM observations
  GROUP BY trip_id
  HAVING count(DISTINCT is_assigned) > 1
     AND max(fetched_at) FILTER (WHERE NOT is_assigned)
       > min(fetched_at) FILTER (WHERE is_assigned)
)
GROUP BY trip_id, fetched_at, is_assigned
ORDER BY trip_id, fetched_at;