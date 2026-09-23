# GTFS static

Reference data from MTA's static GTFS feed, downloaded from
https://www.mta.info/developers on 2026-09-16.

**Schedule period: 2026-05-26 to 2026-10-31.** Expires at the end of that
range. MTA updates this feed a few times a year with no announcement, so
check the `calendar.txt` dates before trusting anything derived from it.

## Why it is committed rather than fetched

The realtime feed is ephemeral and archived to S3 because a missed poll is
unrecoverable. This is the opposite: it changes a handful of times a year,
MTA publishes it at a stable URL, and having it in git means the exact
version any query ran against is visible in the diff.

## What is here

| File | Why |
|---|---|
| `stops.txt` | Station names and the parent-station hierarchy |
| `routes.txt` | Route metadata |
| `calendar.txt` | Which service runs on which weekday, and the period |
| `calendar_dates.txt` | Holiday exceptions to the above |

Not committed: `stop_times.txt` (several million rows), `trips.txt`,
`shapes.txt`, and the rest of the zip. Add them if a question needs them.

## stops.txt

The reason this exists. The realtime feed's `stop_id` is parent station plus
direction (`120S` = 96 St, southbound), **not platform**. Stop 120S is served
by the 1, 2 and 3 — 186, 118 and 129 departures respectively on 2026-09-15 —
so headways computed without partitioning by route interleave three services
and produce 2-second gaps between trains.

Partitioning by `(stop_id, route_id)` fixes the arithmetic but not the
underlying question: at a station where routes use different physical
platforms, a rider on the local platform cannot board an express, so a
combined headway would overstate their service. Where routes share a
platform, combining them is exactly right. The realtime feed does not
distinguish the two cases; `parent_station` and `location_type` here are the
only available handle on it.

`location_type` 1 marks a parent station, 0 marks a platform.

## calendar.txt and calendar_dates.txt

Day type is not the same as day of week. `calendar_dates.txt` shows
2026-09-07 (Labor Day) with `Weekday` service removed and `Sunday` service
added — a Monday running Sunday service. Grouping by `EXTRACT(dow)` would
put it in the weekday bucket and skew the average.

The `-H-` service IDs split the period at 2026-09-07/08, which is summer
versus school-year service levels rather than anything holiday-specific
despite the letter.

**Not currently an issue:** collection began 2026-09-14, after the last
holiday in this period. It becomes one the first time the window spans
Thanksgiving, by which point this feed will have expired anyway.

## Refreshing

Download the zip, extract the four files above, and update the dates in this
README. Check whether `stop_id` values changed before reloading, since
`departures.stop_id` references them.