-- Distribution of NYCT trip type designators.
--
-- trip_type is the first character of the NYCT train_id extension. The 2012
-- spec documents four values:
--   0  scheduled revenue trip
--   =  reroute
--   /  skip stop
--   $  turn train (shortly lined service)
--
-- Observed values include E, which appears in no MTA documentation, no
-- version of the proto comments, and no third-party implementation checked
-- (including Andrew-Dickinson/nyct-gtfs, which returns train_id raw and
-- quotes the same 2012 docstring). Across ~975k trip observations from two
-- days, E was 1.5% of the feed and 96% of E trips were assigned, i.e. they
-- behave like real service. Stored verbatim pending more data.
--
-- Hypothesis tested and rejected (2026-09-16): that E is specific to a line
-- or branch, prompted by the first E trip observed being a 5 running to
-- Dyre Ave, whose track configuration the spec calls out separately. Over a
-- full day E appears on every route in the feed — 2 (21), 1 (20), 4 (16),
-- 5 (15), 6 (8), 7X (7), 7 (7), 6X (3), 3 (2) — so it is route-independent.
-- Still unexplained.
--
-- Also observed: T, exactly once in ~975k observations. Noise, not modelled.
--
-- Why this matters: =, /, and $ mark service modifications applied to trains
-- already running, so a stop disappearing from one of those trips may be a
-- skip rather than a departure. They are candidates for exclusion from
-- headway calculations.
--
-- trip_type varies WITHIN a trip. Over a full day, 113 distinct trips carry
-- the / designator, but those same trips appear both assigned and
-- unassigned with it, and the per-type trip counts sum past the total. A
-- train running normally can be redesignated mid-run. Detection therefore
-- evaluates trip_type per row, not per trip, exactly as it does is_assigned.

-- Trips by designator.
SELECT trip_type,
       count(DISTINCT trip_id) AS trips
FROM observations
GROUP BY trip_type
ORDER BY trips DESC;

-- Designator against assignment: modified types should be ~always assigned,
-- since a trip that never ran cannot have been rerouted.
SELECT trip_type,
       is_assigned,
       count(DISTINCT trip_id) AS trips
FROM observations
GROUP BY trip_type, is_assigned
ORDER BY trip_type, is_assigned;

-- Designator by route, to test whether any type clusters on a line or
-- branch (E was first seen on a 5 train running to Dyre Ave).
SELECT trip_type,
       route_id,
       count(DISTINCT trip_id) AS trips
FROM observations
WHERE trip_type <> '0'
GROUP BY trip_type, route_id
ORDER BY trip_type, trips DESC;