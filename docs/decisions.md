# Decisions

Append-only. Newest at the bottom. Each entry: what was decided, what was
rejected, what decided it.

---

## 2026-09-14: Poll every 30 seconds

**Context.** Arrival times are inferred from feed observations, so timestamp
precision is bounded by poll interval. The feed itself refreshes roughly every
30 seconds.

**Decision.** Poll every 30 seconds.

**Rejected:**
- *60 seconds.* Halves storage, but introduces up to a minute of error in every
  inferred arrival, against a median wait measured in single-digit minutes.
- *Faster than 30s.* Gains nothing; the upstream feed does not refresh that often.

**Decided by:** the asymmetry. Sampling can be reduced retroactively, never
increased. Missing history is unrecoverable; storage is the cheaper thing to fix.

---

## 2026-09-14: Gzip raw payloads on write

**Context.** Feed payloads are 130-200KB depending on how many trains are
running. At 30-second polls that is ~2,880 objects/day, retained indefinitely.
Project budget is $5/month total.

**Decision.** Gzip each payload before writing to S3.

**Rejected:**
- *Store uncompressed.* Simpler, cheap in month one, ~200GB by month twelve.
- *Reduce poll frequency to cut volume.* Rejected separately, see above.
- *Skip the raw archive, store parsed rows only.* Arrival-inference logic is the
  least certain part of this project. Discarding raw payloads makes parsing bugs
  unrecoverable.

**Decided by:** cost against a hard budget. Measured ratio is **4.5x**
(132,869 -> 29,214 bytes), better than the 3x assumed. Revised estimate is
~86MB/day, ~2.5GB/month.

**Revisit when:** a second feed is added, roughly doubling volume.

---

## 2026-09-14: Region us-east-2 (Ohio)

**Decision.** All resources in us-east-2.

**Rejected:** *us-east-1.* Marginally more expensive on several line items and
historically the region with the most visible outages.

**Decided by:** cost, plus reliability. Cost of being wrong is low: the raw
archive is immutable and the processing is stateless, so migration would be a
copy, not a coordination problem. The known exception is that an ACM certificate
for a future CloudFront custom domain must live in us-east-1 regardless.

---

## 2026-09-14: Key structure partitioned by UTC date and hour

**Context.** Object keys are written as
`raw/year=YYYY/month=MM/day=DD/hour=HH/<epoch>.pb.gz`.

**Decision.** Partition on UTC. Convert to America/New_York at query time.

**Rejected:**
- *Partition on Eastern time.* Convenient for selecting "yesterday in NYC" by
  prefix, but breaks on DST: the fall-back hour writes two distinct hours into
  one partition, and the spring-forward hour produces an empty partition that
  reads as an outage. Subway service runs through both transitions, so this is
  not hypothetical.

**Decided by:** correctness. Feed timestamps are already Unix epoch, so UTC
storage keeps one time system end to end. Presentation is Eastern everywhere a
human reads a number.

---

## 2026-09-14: Write-only IAM policy scoped to one prefix

**Context.** The local poller needs to write objects and nothing else.

**Decision.** Customer-managed policy granting only `s3:PutObject` on
`arn:aws:s3:::mta-rt-raw-jm3635/raw/*`, attached to a dedicated `mta-rt-poller`
user. The script uses that profile explicitly rather than inheriting the default.

**Rejected:**
- *`AmazonS3FullAccess` managed policy.* Works immediately, grants read and
  delete the script never uses.
- *Adding read access for convenience.* Interactive browsing is a separate need
  and belongs to a separate identity.

**Decided by:** blast radius. Write-only means a compromised poller can add junk
objects; read would mean it can exfiltrate the archive.

---

## 2026-09-14: Static access key for the poller, console-derived credentials for interactive use

**Context.** AWS CLI v2.32+ provides `aws login`, which exchanges an existing
console session for short-lived, auto-rotated credentials. The poller runs
unattended on a 30-second loop.

**Decision.** `aws login` for interactive terminal work. A static access key,
stored under a named `poller` profile, for the script only.

**Rejected:**
- *`aws login` for everything.* Credentials expire and require a browser; an
  unattended loop would break at the first expiry.
- *IAM Roles Anywhere.* The correct answer for long-running non-AWS workloads:
  an X.509 certificate exchanged for temporary credentials, no static key at all.
  Rejected as disproportionate for a key with a two-week expected lifespan.

**Decided by:** proportionality. The static key is a known compromise, scoped
write-only, tagged for deletion.

**Revisit when:** the Lambda lands. Its execution role removes the need for a
stored key entirely, and this key gets deleted.

---

## 2026-09-14: Let failed polls fail

**Context.** The fetch can fail when the upstream feed is unavailable.

**Decision.** Catch, log to `poll.log`, continue. No retry, no queue.

**Rejected:**
- *Retry with backoff.* Adds complexity for no gain: a retried fetch returns a
  different snapshot, not the one that was missed.
- *Dead letter queue.* Not applicable yet (no Lambda), and would not recover the
  data either. Feed polling is genuinely lossy on failure.

**Decided by:** the nature of the data. A missed poll is one sample in ~2,880
daily and barely moves an inferred arrival time. The value of catching failures
is knowing the rate, not recovering the payload. A 10-second request timeout is
in place so a hung connection cannot stack up processes.

**Revisit when:** the Lambda lands. A DLQ then provides observability, which is
what the README's failure count will actually be reporting.

## 2026-09-15: Schema constraints verified against real data, not assumed

**Context.** The observations schema declares several `NOT NULL` columns and a
`char(1)`-width direction. All of those are assumptions about feed behavior.

**Decision.** Before writing the DDL, ran a throwaway script (`explore_feed.py`)
over every object collected so far: 1,847 payloads, 7.45M stop observations,
207,725 vehicle entities.

Results:
- `route_id` missing: 0 → safe as `NOT NULL`
- `stop_id` lengths: all 4 characters → clean `[:-1]` / `[-1]` split
- direction suffixes: only `N` and `S` → single character holds
- vehicle `stop_id`, `current_stop_sequence`, `timestamp` missing: 0 each
- unparseable objects: 0 → archive is sound
- routes present: 1, 2, 3, 4, 5, 6, 6X, 7, 7X, GS

**Decided by:** cost of being wrong. A `NOT NULL` that turns out to be false
fails at load time on data that cannot be re-fetched.

**Carried forward:** `6X` and `7X` are express variants. A rider at a
local-only stop is not served by an express that passes through, so headway
logic must decide explicitly whether express counts. Not yet resolved.

---

## 2026-09-15: stop_id stored verbatim, station and direction derived

**Decision.** Keep `stop_id` exactly as the feed gives it (`111N`), and add
`station_id` and `direction` as derived columns alongside.

**Rejected:**
- *Store only the split columns.* Loses fidelity to the source; if the split
  assumption is ever wrong, the original value is unrecoverable.
- *Store only `stop_id`.* Every query would parse the string, and the natural
  grouping (station + direction) would be implicit rather than indexable.

**Decided by:** the derived columns cost almost nothing, and keeping the raw
value means a wrong parsing assumption is fixable by reloading rather than
by re-collecting.

---

## 2026-09-15: Timestamps as timestamptz, not epoch integers

**Decision.** All time columns are `timestamptz`. Feed epochs are converted at
load time.

**Rejected:** *Store raw `bigint` epochs.* Faithful to the source and avoids a
conversion, but pushes timezone handling into every query forever. Postgres
handles `AT TIME ZONE 'America/New_York'` and DST correctly; hand-rolled epoch
math does not.

**Decided by:** this is the boundary where UTC storage meets Eastern
presentation (see 2026-09-14 partitioning entry). Converting once at the
boundary is the whole point of having a boundary.

---

## 2026-09-15: Unique constraint makes loads idempotent

**Context.** The loader will be interrupted, re-run after parsing fixes, and
pointed at overlapping prefixes. Without protection, every re-run duplicates
rows and silently corrupts downstream headway math.

**Decision.** `UNIQUE (fetched_at, trip_id, start_date, stop_id)` on
observations, `UNIQUE (fetched_at, trip_id, start_date)` on vehicles, with
`ON CONFLICT DO NOTHING` on insert. `fetched_at` is parsed from the S3 object
key rather than taken from the clock, so a reload reproduces identical rows.
One transaction per object, so an interruption always leaves a clean boundary.

**Rejected:**
- *Track processed keys in a separate table.* More moving parts, and still
  wrong if a run dies between insert and bookkeeping.
- *Truncate and reload.* Fine now, impossible once the table holds months.

**Verified:** loaded `hour=16` (120 objects, 692,152 rows), re-ran the same
prefix, row count unchanged at 692,152. Second run inserted zero.

---

## 2026-09-15: source_key column on every row

**Decision.** Every observation and vehicle row records the S3 key it was
parsed from.

**Rejected:** *Rely on `fetched_at` alone.* It is derived from the key, so it
identifies the payload indirectly, but it cannot be used to delete and reload
a specific object without string reconstruction.

**Decided by:** reprocessing. Fixing a parsing bug means
`DELETE WHERE source_key = ...` then re-running that object. Also gives a
coverage audit: `SELECT DISTINCT source_key` diffed against the bucket listing
shows exactly which payloads have been loaded.

**Cost:** ~60 bytes per row against a table taking ~12M rows/day. Accepted.

---

## 2026-09-15: Store vehicle position entities

**Context.** Each poll contains two entity types: `trip_update` (predictions,
~5,800 stop rows per poll) and `vehicle` (positions, ~160 rows per poll).
Vehicles are ~3% the volume of observations.

**Decision.** Store both, in separate tables.

**Rejected:**
- *Discard vehicles.* They are not needed to compute headways directly.
- *Merge into one table.* Different shape (one row per trip vs one row per
  stop per trip) and different purpose.

**Decided by:** observations are what the arrival inference is built on;
vehicles are independent evidence of where a train actually is. Having a
second, differently-derived signal is what makes the inference checkable
rather than merely plausible. This turned out to matter the same day — see the
arrival-detection entry below.

`current_status` is stored as the raw enum integer, and as NULL when the feed
omits it (~38% of entities). Absent is almost certainly `IN_TRANSIT_TO`, the
proto3 default and therefore not serialized, but recording NULL keeps that an
interpretation for the query layer rather than a fact written into the table.

---

## 2026-09-15: Loader is batch and decoupled from the poller

**Decision.** `poll.py` runs continuously and only archives bytes. `load.py`
is a separate batch job, run manually against an arbitrary S3 prefix.

**Rejected:**
- *Parse and insert inside the poller.* One fewer moving part, but couples the
  thing that cannot afford to fail to the thing most likely to have bugs, and
  makes reprocessing impossible.
- *Continuous loader.* Slower development loop; nothing gains from it while
  parsing logic is still changing.

**Decided by:** the source determines the schedule. Ingest must be real-time
because the feed is ephemeral. Parsing can be batch because the archive is
durable. The same split shows up in the IAM policies: the poller can only
`PutObject`, the loader can only `GetObject` and `ListBucket`, and neither can
do the other's job.

**Revisit when:** parsing stabilizes. Lambda's 15-minute limit makes it a poor
host for backfills, so a scheduled hourly Lambda plus a manual backfill path,
or a scheduled container, are the likely options. Not resolved.

---

## 2026-09-15: Arrival detection requires a corroborating vehicle entity

**Context.** The feed never states that a train arrived. Stops drop off the
front of a trip's `stop_time_update` list as the train passes them, so the
obvious inference is: a stop disappearing from a trip means an arrival.

**That inference is wrong, and the data shows it.** Trip `063100_2..N02R`
appeared in 55 consecutive polls (12:00:12 to 12:27:13) with all 48 of its
stops present in every single one. The list never shrank by one entry. Its
first stop was scheduled for 10:33, 87 minutes before the window observed. It
had no vehicle entity in any poll. Then it vanished from the feed entirely.

This is a scheduled trip that never ran. Naive disappearance logic would have
recorded **48 simultaneous arrivals for a train that did not exist**. Roughly
100 of ~260 trips per poll have predictions but no vehicle position, so this
is not an edge case.

**Decision.** An arrival is recorded only when the stop disappears from the
trip's list *and* the trip has a corroborating vehicle entity. Arrival time is
the last observed prediction for that stop before disappearance.

**Rejected:**
- *Disappearance alone.* Produces phantom arrivals at the scale shown above.
- *Prediction convergence alone* (last prediction within ~60s of `fetched_at`).
  Better, but a never-started trip's predictions do not converge — they freeze
  at their scheduled values and then vanish, and a frozen past-tense value
  looks exactly like an arrival.
- *Trusting the GTFS-RT `schedule_relationship` field.* Worth reading, but MTA
  populates it inconsistently; not a basis for the primary rule.

**Decided by:** the bug hides the thing being measured. Cancellations are
service unreliability, and converting them into on-time arrivals makes the p90
look best precisely when service is worst.

**Open question for next session:** verify the inverse. Do trips that
demonstrably ran (stop list shrank over time) have vehicle entities in most or
all of their polls? If running trips also have coverage gaps, the rule needs a
threshold rather than a binary test.