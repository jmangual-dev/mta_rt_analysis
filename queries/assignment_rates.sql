-- How often does a trip's is_assigned value change, and in which direction?
--
-- MTA assigns a trip to a physical train at its origin terminal. The
-- expectation from the spec and from third-party implementations is that
-- assignment is one-way and sticky: once assigned, a trip stays assigned
-- until it reaches its terminal.
--
-- That expectation is mostly but not entirely true. Run this to size both
-- the flip rate and the reversal rate. Reversals are the interesting ones:
-- see queries/assignment_reversals.sql for their timelines.
--
-- Departure detection evaluates is_assigned per row rather than per trip,
-- so a one-way flip needs no special handling.

-- Trips whose is_assigned changes at least once.
SELECT count(*) FILTER (WHERE flips)                                AS flipping,
       count(*)                                                     AS total_trips,
       round(100.0 * count(*) FILTER (WHERE flips) / count(*), 2)   AS pct
FROM (
  SELECT trip_id, count(DISTINCT is_assigned) > 1 AS flips
  FROM observations
  GROUP BY trip_id
) t;

-- Of all trips, how many go assigned -> unassigned (the unexpected direction)?
SELECT count(*) AS reversals
FROM (
  SELECT trip_id
  FROM observations
  GROUP BY trip_id
  HAVING count(DISTINCT is_assigned) > 1
     AND max(fetched_at) FILTER (WHERE NOT is_assigned)
       > min(fetched_at) FILTER (WHERE is_assigned)
) t;