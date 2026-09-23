-- A headway is the gap between one train leaving a platform and the next
-- one leaving it. If the 1 departs 96 St southbound at 8:02 and the next
-- one departs at 8:09, the headway is 7 minutes.
--
-- It is the raw material for every rider-facing number this project
-- produces. Nobody waits a "headway" — what a rider experiences is some
-- fraction of one, depending on when they walk onto the platform — but
-- wait time is derived from the distribution of headways, so this is the
-- layer everything sits on.
--
-- Computed with lag(): order departures by time within a platform and
-- route, subtract each from the one before it. Result is in minutes.
--
-- PARTITION BY (stop_id, route_id), not stop_id alone. stop_id is parent
-- station plus direction, NOT platform: 120S (96 St southbound) carries the
-- 1, 2 and 3. Partitioning by stop alone interleaves three services and
-- produces impossible 2-second gaps between trains.
--
-- WHERE trip_type = '0' keeps only ordinary scheduled revenue trips. The
-- /, = and $ designators mark skip-stop, reroute and turn-train service,
-- where a stop vanishing from a trip may be a skip rather than a departure.
--
-- TWO THINGS THIS VIEW DOES NOT HANDLE:
--
-- 1. Collection gaps. lag() spans the whole table, so if the poller was
--    down between two loaded days, the first departure after the gap gets
--    a headway measured against the last one before it. Filter on
--    headway_minutes before computing any statistic; anything over ~60
--    minutes is a gap, not service.
--
-- 2. Origin terminals. At a terminal the train sits before departing, so
--    the prediction stays at its scheduled value and the "observed"
--    departure is really the timetable. Eleven stop/route pairs show this
--    at exactly 100% (101S/1 Van Cortlandt, 142N/1 South Ferry, 901N and
--    902S on the shuttle, and so on), identifiable by departure times
--    landing on :00 or :30 seconds. Terminal headways describe the
--    schedule, not reality.

CREATE VIEW headways AS
SELECT stop_id,
       route_id,
       departed_at,
       extract(epoch FROM (departed_at - lag(departed_at)
         OVER (PARTITION BY stop_id, route_id ORDER BY departed_at))) / 60
         AS headway_minutes
FROM departures
WHERE trip_type = '0';