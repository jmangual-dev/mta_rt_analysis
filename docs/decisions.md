# Decisions

Append-only. Newest at the bottom. Each entry: what was decided, what was
rejected, what decided it. Corrections to earlier entries are made in place
and listed in an Errata entry, so the log stays honest about its own edits.

Written with AI assistance (Claude) as a thinking partner and drafting aid.
Every finding here was checked against collected data before anything was
built on it; where an initial assumption turned out to be wrong, the entry
says so. Project overview is in the [README](../README.md).

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

---

## 2026-09-15: Poller moved to Lambda, ahead of schedule

**Context.** The poller ran locally under `caffeinate -s`, which held cleanly
overnight (1,702 objects, zero failures, no sleep gaps). But the machine is a
laptop. Working away from home means going offline, and every poll attempted
offline is data permanently lost — a failed fetch cannot be recovered later,
because a retried fetch returns a different snapshot.

**Decision.** Migrate the poller to Lambda now rather than in week two.

**Decided by:** the local host's failure mode is tied to where I am, not to
anything about the workload. Deferring the migration meant accumulating
collection gaps for no reason.

**What changed in the code:**
- `requests` replaced with `urllib.request` (stdlib). This removes the only
  third-party dependency, so the function deploys as a single pasted file with
  no build step and no zip. `boto3` ships with the Lambda runtime.
- No try/except. An uncaught exception marks the invocation failed, which
  surfaces in CloudWatch metrics. Catching it would make every invocation look
  successful.
- `BUCKET` read from an environment variable with `os.environ[...]`, not
  `.get()`, so a missing value fails at import with a clear error rather than
  at the S3 call with a confusing one.
- boto3 client created at module scope, so warm invocations reuse it.

---

## 2026-09-15: Execution role replaces the static access key

**Decision.** The Lambda uses an IAM execution role. The `mta-rt-poller` user
and its access key are deleted.

**Why this was not possible before:** roles work by AWS verifying the identity
of the caller. Lambda runs inside AWS, so that is automatic — credentials are
injected, temporary, and rotated continuously, and `poll_handler.py` has no
`profile_name` and no stored secret. A laptop has no identity AWS can verify,
which is why the static key existed at all.

**Closes:** the "revisit when the Lambda lands" note on the 2026-09-14
credentials entry. Manual runs now use `aws login` (my own identity, correctly
attributed) or `aws lambda invoke` (the execution role, same code path as
production). Neither needs a stored key.

**General rule this follows:** anything running on AWS compute uses a role.
Users are for humans and for systems outside AWS.

---

## 2026-09-15: One schedule, one function, two fetches per invocation

**Context.** Polling every 30 seconds requires sub-minute scheduling.

**Decision.** A single EventBridge Scheduler rate schedule firing once a
minute. The function fetches, sleeps 30 seconds, fetches again.

**Rejected:**

- *Two schedules offset 30 seconds apart, targeting one function.* The
  preferred design: no billed idle time, and two genuinely independent
  invocations with no drift, since each fires against wall-clock time.
  **Rejected on a platform limit, not preference** — EventBridge Scheduler's
  cron has no seconds field, and rate schedules only accept minute-resolution
  start times. A sub-minute offset is not expressible.
- *SQS with delayed delivery.* Avoids the billed sleep by having the first
  invocation enqueue a 30-second-delayed message that triggers the second.
  Rejected as using a queue for scheduling: adds at-least-once duplicate
  delivery, approximate timing, another IAM policy, and its own DLQ, to save
  an amount of Lambda time that is inside the free tier. Queues decouple a
  producer from a consumer running at a different rate; there is one producer,
  one consumer, and a fixed rate here.
- *Step Functions with a Wait state.* The one option that genuinely solves the
  idle-cost problem, since waits are free and it bills per state transition.
  Rejected on cost: four transitions per minute is ~172k/month, and past the
  4k free tier that is ~$4.30/month — most of a $5 budget, to save fractions
  of a cent.
- *Self-invocation after completion.* Rejected as an anti-pattern. No external
  rate limit, so a bug that double-invokes compounds every cycle; a single
  failed invocation stops the chain permanently rather than losing one poll;
  the schedule becomes invisible to anyone reading the infrastructure; and
  timing drifts with each cycle's duration. Scheduling belongs in a scheduler.
- *Lambda durable execution.* Checkpoint/replay for multi-step workflows that
  suspend and resume. There is one step taking two seconds, nothing to
  checkpoint, and retries are actively unwanted.

**Cost:** ~43,200 invocations/month at ~33 billed seconds, 128MB ≈ 178k
GB-seconds, inside the 400k free tier. Thinner margin than a single-fetch
design would have, but free.

**Revisit when:** polling more than one feed. At eight feeds the workload
becomes fan-out rather than one step twice, and Step Functions' Map state
becomes the right tool — because the problem changed shape, not because the
budget grew.

---

## 2026-09-15: Asynchronous retries disabled

**Context.** During the cutover, one invocation failed (the new sleeping code
deployed before the function timeout was raised from 3s to 60s). Lambda
retried the failed async invocation 90 seconds later — same RequestId,
`a06aa9b8-6b2e` — and the retry ran concurrently with the next scheduled
invocation. Object spacing went 8s, 23s, 8s, 20s instead of a clean 30.

**Decision.** Retry attempts set to 0.

**Decided by:** the same reasoning as "let failed polls fail" (2026-09-14). A
retried fetch returns a different snapshot, so the retry recovers nothing. It
adds a duplicate sample at an unpredictable time and hides the real failure
rate behind two silent attempts. With retries off, a failure goes straight to
the CloudWatch `Errors` metric — and, once configured, to the DLQ.

**Note on timeouts, since they share a name:** `TIMEOUT = 10` in the code is
the socket timeout on the HTTP request. The 60-second Lambda timeout is the
platform's limit on the whole invocation. They nest, and the inner one must be
smaller: worst case is 10 + 30 + 10 = 50s. If the socket timeout exceeded the
Lambda timeout, a slow feed would produce a generic `Task timed out` instead
of a readable `URLError`.

---

## 2026-09-15: Collection handoff, local to Lambda

Verified in the data rather than assumed. During the overlap both pollers ran,
producing alternating 9s/21s gaps. After `pkill -f poll.py`, spacing settled to
a clean alternating 29s/31s.

The alternation is structural, not drift: the first fetch lands ~1s into an
invocation, the second at ~31s after the sleep, and the next invocation starts
60s after the first. Jitter is Lambda start latency, roughly a second.

Handoff boundary for the data-quality section: local collection ran from
2026-09-14 21:55 to 2026-09-15 ~21:30 ET. Lambda collection begins 2026-09-15
21:29 ET. The brief overlap produced denser-than-30s sampling, which the
idempotent loader handles without special casing.

---

## 2026-09-16: Compiled the NYCT proto extensions

**Context.** The base GTFS-realtime bindings expose none of MTA's own
extension fields. Three open questions depended on them: how to identify
trips that never run, how to identify skipped stops, and whether the feed
flags rerouted trains.

**Decision.** Compile `gtfs-realtime-NYCT.proto` with protoc and generate the
base bindings alongside it, dropping the `gtfs-realtime-bindings` pip package.

**Rejected:** *keeping the pip package and generating only the NYCT module.*
The generated code imports the base spec at `com.google.transit.realtime`,
the pip package installs it at `google.transit`. Two copies of the same
message definitions in one process risks a duplicate-registration failure.
One source of truth is simpler than explaining which one wins.

**Cost:** imports across the codebase change to
`from com.google.transit.realtime import gtfs_realtime_pb2`, and generated
`_pb2.py` files are committed so nobody needs protoc to read the repo.
Regeneration: `cd proto && protoc --python_out=.. gtfs-realtime-NYCT.proto`.

**Unlocked:** `is_assigned`, `train_id`, `scheduled_track`, `actual_track`.

---

## 2026-09-16: schedule_relationship is not populated — confirmed, not inferred

**Context.** GTFS-realtime defines `SKIPPED` on StopTimeUpdate and `CANCELED`
on TripDescriptor. If MTA populated either, the skip-stop and never-ran
problems would be solved by reading a field.

**Finding.** Across 12.2M stop updates and 573,749 trip updates spanning two
days, both enums were 0 in every single case.

That result is ambiguous on its own — proto3 does not distinguish "set to the
default" from "not set" — and a clean sample could just mean good service.
Two things resolve it:

1. `063100_2..N02R` was independently established as a trip that never ran
   (55 polls, all 48 stops, no vehicle entity, is_assigned false). The
   trip-level enum still read SCHEDULED.
2. MTA's own spec states it directly: ScheduleRelationship is not used,
   because there is no reliable way to link a realtime trip back to the
   static GTFS trip. StopTimeUpdate's `schedule_relationship` is marked
   "Not used."

**Consequence.** Skip-stop and cancellation detection are heuristics by
necessity, not by choice.

---

## 2026-09-16: is_assigned is the primary test for whether a trip ran

**Context.** Three candidate signals for distinguishing a real train from a
scheduled trip that never ran: absence of a VehiclePosition entity, a stop
list that never shrinks, and the NYCT `is_assigned` flag.

**Decision.** `is_assigned`, evaluated **per row**, not per trip. Vehicle
presence is corroboration.

**Why is_assigned over vehicle presence:** the VehiclePosition appears only
once a train starts moving, which is documented behavior and visible in the
data — `072100_1..S15R` had seven polls with predictions and no vehicle, and
the entity appeared in the exact poll its stop count first dropped. Assignment
happens at the origin terminal, earlier, so it discriminates sooner.

**Why per row:** assignment is not a fixed trip property. Over a full day,
**3,143 of 3,797 trips (82.78%)** change their is_assigned value at least
once. Nearly every trip enters the feed unassigned and becomes assigned.
(An earlier one-hour sample showed 25.7%, which was a sampling artifact: a
short window catches most trips mid-run with assignment already settled.)

**Rejected:**
- *Disappearance alone.* Produces phantom departures at scale. A never-run
  trip vanishes all at once, so `063100_2..N02R` would have contributed 48
  simultaneous departures for a train that did not exist. 44% of distinct
  trips in a given hour are unassigned.
- *Prediction convergence alone.* A never-started trip's predictions do not
  converge; they freeze at scheduled values and then vanish, which looks
  exactly like an arrival.
- *Trip-level assignment.* Would discard the 82.78% case entirely.

**Corroborated independently:** Andrew-Dickinson/nyct-gtfs exposes the same
flag as `train_assigned` and uses it the same way.

---

## 2026-09-16: Assignment reverses in 3.8% of trips, and departed stops can reappear

**Context.** Assignment was expected to be one-way and sticky.

**Finding.** 143 of 3,797 trips (3.8%) go assigned -> unassigned. None of the
three inspected cases was a single-poll blip; all were sustained.

The consequential one is `074250_2..S02R`: assigned at 12:01, **departed a
stop at 12:04 (48 -> 47 stops)**, then unassigned at 12:10 with **the stop
list back at 48**. The departure was undone.

Operationally this reads as a work program being revoked — the spec describes
trains at a terminal being assigned or moved to storage, and this is that in
reverse.

**Consequence.** A disappearance is not necessarily final. Taking the last
observation of each stop happens to handle this conservatively: a reappeared
stop looks present at the end and is excluded, so a real departure is dropped
rather than a phantom recorded. **That is the safe direction but it is not
deliberate handling.** Logged as a known gap.

---

## 2026-09-16: trip_type stored per row, filtered at query time

**Context.** The first character of `train_id` is a trip type designator:
`0` scheduled revenue, `=` reroute, `/` skip stop, `$` turn train.

**Decision.** Store `train_id` verbatim plus `trip_type` as the derived first
character, on every observation row. Do not filter at load time.

**Why per row:** a trip can be redesignated mid-run. Over a full day 113
distinct trips carry `/`, and those same trips appear with it both assigned
and unassigned; the per-type trip counts sum past the total. A train running
normally before being redesignated has real departures that should not be
discarded, and stops after redesignation that should not be trusted.

**Distribution over a full day** (trips, not observations): `0` 3,646,
`/` 113, `E` 99, `=` 42, `$` 18.

**Skip-stop concentration:** the 1 (31 trips) and the 6 (28) lead by a wide
margin, which matches the operational pattern that prompted the question in
the first place — a 1 train running 96th to 137th.

---

## 2026-09-16: `E` is an undocumented designator. Investigated and unresolved.

`E` appears in 99 trips/day, 1.5% of trip observations, and in no
documentation anywhere. Everything checked, and what it ruled out:

- **MTA's 2012 spec and the proto comments.** List four designators. No `E`.
- **Third-party implementations,** including Andrew-Dickinson/nyct-gtfs,
  which returns `train_id` raw and quotes the same 2012 docstring verbatim.
- **Route clustering.** Hypothesis: `E` is specific to a line or branch,
  prompted by the first `E` trip observed being a 5 running to Dyre Ave,
  whose track configuration the spec calls out separately. **Rejected** — `E`
  appears on every route in the feed: 2 (21), 1 (20), 4 (16), 5 (15), 6 (8),
  7X (7), 7 (7), 6X (3), 3 (2).
- **Alert entities.** Six `E` trips on the 5 produced the largest negative
  lag outliers, all at stops 420S/423S between 16:22 and 16:58, all predicted
  35+ minutes later. **Zero of them carried an alert.** They were not flagged
  as delayed; they were withdrawn.
- **Track mismatch.** `scheduled_track` vs `actual_track` would flag a manual
  reroute, which the spec says makes predictions unreliable. **Not testable
  on these trips** — `actual_track` was NULL for all 176 relevant rows,
  consistent with the spec's note that it is only set for the first remaining
  stop of a trip. Mismatch rates by type are otherwise proportional to feed
  share, so no signal there either.

**Behaviorally, `E` looks like real service:** 96% assigned, lag distribution
(-110/+14/+93) only mildly wider than type `0`.

**Decision.** Store verbatim, treat as normal service, revisit with two weeks
of data. The ±120s lag filter handles its outliers regardless of cause.

**Also observed:** `T`, exactly once in ~975k observations. Noise, not modelled.

---

## 2026-09-16: Departures, not arrivals

The spec is explicit and a third-party implementation confirms it: a stop is
dropped from a trip's list when the train **departs** that station, not when
it arrives. nyct-gtfs's own example shows a train `STOPPED_AT` a station with
that station still present in its stop list.

**Decision.** The table is `departures` and the column is `departed_at`.
Renamed before building anything on top.

For headway purposes this is arguably the better measure anyway: what a
waiting rider experiences is the gap between departures. The difference is
one dwell time, roughly 20-60 seconds.

---

## 2026-09-16: ±120s lag filter on departures

**Context.** `lag_seconds = last_seen_at - departed_at` measures how stale a
final prediction was when it vanished. It is the error bar on every headway
derived downstream.

**Measured across a full day** (76,696 candidate departures):
median **+12s**, p05 **-51s**, p95 **+55s**. So inferred departure times are
accurate to roughly ±1 minute, comfortably inside the resolution needed for
headways measured in minutes. The +12s median is the expected poll-interval
bias — a stop drops at the poll *after* departure.

By trip type:

| type | departures | p05 | median | p95 |
|---|---|---|---|---|
| `0` | 74,116 | -51 | +12 | +53 |
| `E` | 1,623 | -110 | +14 | +93 |
| `/` | 654 | -45 | +12 | **+417** |
| `=` | 247 | +4 | +30 | +122 |
| `$` | 56 | +3 | +48 | **+671** |

The `/` and `$` tails **confirm the skip-stop hypothesis independently of the
designator**: a skipped stop vanishes while its prediction is still minutes
out and never converged. Two independent signals for a skip now exist.

**Decision.** Exclude candidates outside ±120s. Discards 2,329 of 76,696
(**3.04%**), leaving 74,367.

**Why the outliers are not normal service, and why the filter is symmetric:**
the two tails have different causes.
- *Positive tail:* delayed trains whose predictions froze while they sat.
  These **do** carry Alert entities — `090500_6..S01R` had 58 alerts in one
  hour and also appeared in the lag outliers.
- *Negative tail:* trips withdrawn before running. **No alerts.**

**Rejected:** ±300s (would keep cases that are clearly not departures) and no
filter (the ±45-minute extremes would corrupt headway percentiles).

**Known cost:** the origin terminal of a trip is systematically at risk of
exclusion. A train sits at its origin before departing, so that prediction
goes stale in a way mid-run predictions do not. `072100_1..S15R` produced 36
departures against 37 stops shed, and the missing one is its first stop
(101S, lag +132s). Revisit whether origin stops need a separate threshold.

---

## 2026-09-16: Departure detection validated end to end

`queries/insert_departures.sql` materializes `departures` from `observations`.
Four conditions, each established against real data: is_assigned true at that
poll; the stop not still present in the trip's final poll; |lag| ≤ 120s; a
departure time exists (`departure_time`, falling back to `arrival_time`).

Idempotent via `UNIQUE (trip_id, start_date, stop_id)` and
`ON CONFLICT DO NOTHING`, same pattern as the loader.

**Result:** 74,367 departures from 12.5M observations across 3,278 trips and
341 platforms, exactly matching the predicted count after filtering.

**Validation:** `072100_1..S15R` was independently established days earlier as
having shed 37 stops. It produced 36 departures — the discrepancy is the
origin-terminal case noted above, not a logic error.

---

## 2026-09-16: Headways are per (stop_id, route_id)

**Context.** The first headway query at 96th St southbound produced gaps of
2, 15, and 18 seconds between trains. Physically impossible.

**Cause.** `stop_id` is parent station plus direction, **not platform**. Stop
120S (96th St) is served by the 1, 2, and 3 — 186, 118, and 129 departures
respectively across one day. Computing headways without partitioning by route
interleaves three services.

**Decision.** Headways partition by `(stop_id, route_id)`.

**The limitation this exposes, which is not solved:** at a station where
routes use *different physical platforms*, a rider on the local platform
cannot board an express, so a combined headway would overstate their service.
At a station where routes share a platform, combining them is exactly right.
**The realtime feed does not distinguish these cases.** Resolving it requires
the static GTFS `stops.txt` and its parent-station hierarchy.

**Also found:** route-to-station mapping is not static even within a day.
121S and 122S are 1-train stops (187 departures each) that also saw 16
departures of the 2 — express trains running local, most likely overnight or
during a disruption.

**Next:** pull the static GTFS. It resolves the platform question and
supplies station names, which the frontend needs regardless — "120S" means
nothing to a user.

---

## 2026-09-20: Static GTFS added to the repo, not archived to S3

**Context.** The realtime feed needed a companion: station names for the
frontend, and the parent-station hierarchy to settle the platform question.

**Decision.** Commit `stops.txt`, `routes.txt`, `calendar.txt` and
`calendar_dates.txt` to `data/gtfs-static/`. Do not archive to S3.

**Why the opposite treatment from the realtime feed:** the rule is that
ephemeral data goes to object storage because a missed poll is unrecoverable,
and stable data goes in git because the version any query ran against should
be visible in the diff. Static GTFS changes a handful of times a year at a
stable URL.

**Rejected:** *the supplemented GTFS feed* (`gtfs_supplemented.zip`, updated
hourly, covers seven days forward). It would improve matching realtime trips
to scheduled ones and distinguish planned service changes from real-time
operational calls, which bears directly on the `/` and `=` designators. But
it cannot be retrieved for the past, so it says nothing about the days
already collected, and it would need its own archiving Lambda to be useful
later. Deferred; noted that starting to archive it now is the only way to
have it later.

**Not committed:** `stop_times.txt` and the rest of the zip. Several million
rows, not needed yet.

**Schedule period: 2026-05-26 to 2026-10-31.** This copy expires then.

---

## 2026-09-20: Platform topology is not in either feed. Deferred, not solved.

**The question.** Stop 120S (96 St southbound) carries the 1, 2 and 3 — 186,
118 and 129 departures on one day. Headways partitioned by stop alone
interleave three services. Partitioning by `(stop_id, route_id)` fixes the
arithmetic, but the rider-facing question remains: is a combined "next train"
figure correct for someone standing on that platform?

**What the static GTFS says.** Nothing useful. 96 St is three rows:

    stop_id  stop_name  location_type  parent_station
    120      96 St      1
    120N     96 St                     120
    120S     96 St                     120

Direction only. No local/express children. **Confirmed unsolvable from either
feed.**

**Why it matters, and why my first framing was wrong.** I initially assumed
96 St splits local and express onto separate platforms. It does not — 96 St,
72 St and 42 St are cross-platform transfer stations where local and express
in the same direction share one island platform, which is the whole point of
the design. So a combined figure is *correct* at most stations. The
counterexample is 34 St, where the 1/2/3 split across three platforms with
the express island shared between directions.

So: combined headway is right at most stations and wrong at a few, not the
reverse.

**Decision.** Report per `(stop_id, route_id)`. A combined per-station figure
is computable and honest if labelled as station service frequency rather than
as one rider's wait.

**The fix, priced and deferred:** a hand-built mapping of which routes share
a platform in each direction. On the A division that is roughly a dozen
ambiguous stations, most being local-only single-platform. It is a day of
manual data entry with no architectural component, and it can be added later
as a join at query time without touching anything upstream.

---

## 2026-09-22: Origin terminals publish schedule, not observation

**Found while sanity-checking the first headway output.** At 101S (Van
Cortlandt Park, the 1's northern terminal) overnight departures landed on
22:04:30, 22:14:30, 01:05:30, 01:25:30 — every one on the half-minute,
every gap exactly 20:00. Real service does not do that.

Ten stops down the line at 120S over the same window: 01:02:14, 01:16:19,
01:54:55, with gaps of 14:05, 16:59, 21:37. Arbitrary seconds, scatter around
20 minutes. That is observation.

**Cause.** At an origin terminal the train sits before departing, so its
prediction stays at the scheduled value and never converges on an actual
departure. The spec notes the same thing from the other direction: predicted
times are not updated when a train is not moving.

**Terminals are identifiable empirically, with no maintained list.** Grouping
by `(stop_id, route_id)` and measuring the share of departures landing on :00
or :30 seconds gives a clean separation. Twelve pairs (eleven stops; 247N
serves both the 2 and the 5) sit at exactly 100%:

    901N/GS  902S/GS  101S/1  142N/1  401S/4  501S/5
    601S/6   201S/2   247N/2  247N/5  257N/3  250N/4

Random seconds would hit those two values ~3.3% of the time, so 100% is
unambiguous. A middle band (701S/7 87.8%, 640N/6 86.3%, 702S/7 60.4%,
726N/7 47.1%) is partial: at a busy terminal a train that arrives late and
turns quickly produces an observed time, while one already waiting departs on
schedule.

**Consequence.** Terminal headways describe the timetable, not reality, and
should be excluded or labelled in rider-facing statistics. Overall 7.7% of
departures land on round seconds against a 3.3% chance baseline, so roughly
3,200 of 72,052 are schedule-derived.

**This also explains the earlier count discrepancy.** `072100_1..S15R` shed
37 stops but produced 36 departures. The missing one is its origin (101S, lag
+132s): a stale terminal prediction pushed past the ±120s filter. The filter
was already excluding most terminal departures, which is arguably correct
behaviour arrived at by accident. Flagging terminals explicitly is a to-do.

---

## 2026-09-22: Headways view, and what it deliberately does not handle

`schema/07_headways.sql` defines `headways` as `lag()` over departures,
partitioned by `(stop_id, route_id)`, ordered by `departed_at`, filtered to
`trip_type = '0'`.

**First real output** — the 1 southbound at 96 St, weekday mornings 08:00 to
10:00, from 50 observed departures:

    median headway 3.6 min,  p90 6.5 min

Plausible for rush hour on the 1, and derived end to end from raw protobuf.

**Two things the view does not handle, documented at the definition because a
view looks authoritative:**

1. *Collection gaps.* `lag()` spans the whole table, so a lapse between
   loaded days produces one enormous false headway per stop/route pair at the
   boundary.
2. *Origin terminals*, per the entry above.

**The gap threshold was set from the distribution, not by guess.** Headways
decay smoothly to ~80 minutes, then run as a thin tail through ~290, then
**1,790 rows pile into a 300+ overflow bucket**. That spike is the two
multi-day collection lapses; everything below it decays like real service. An
initial 60-minute cutoff was discarding genuine overnight headways — there is
a real cluster at 61-80 minutes at low-frequency stops.

**Interim decision:** filter at 120 minutes. Keeps essentially all genuine
service, drops all 1,790 artifacts, and is defensible as "no subway headway
exceeds two hours."

**The correct fix, deferred:** flag headways that span a known collection
gap, derived from the observation timestamps rather than inferred from
magnitude. "I excluded headways spanning a known collection gap" survives
scrutiny in a way "I filtered anything over N minutes" does not. The
difference is a few hundred rows out of 200,000, and a continuous backfill
largely dissolves the problem anyway.

---

## 2026-09-22: Load throughput measured — the bottleneck is S3, not Postgres

**One full day (2,880 objects, 12.2M observations): 11 minutes, at 27% CPU.**

That utilisation is the finding. The process is idle three-quarters of the
time waiting on S3 round trips. Parsing and inserting are not the constraint,
which means:

- The full backfill (22,892 objects, ~8 days) is roughly **90 minutes
  sequential** — a leave-it-running job, not an overnight one.
- Dropping indexes before a bulk load would not help much, since index
  maintenance is not what is slow.
- A thread pool of 8-10 on the S3 fetches would likely cut it to 15-20
  minutes. Not built; worth knowing the lever exists.

**Storage:** ~290 bytes per observation row with indexes (7.2GB for 25M
rows). A year of continuous collection is ~800GB. 380GB free locally, so the
backfill itself fits comfortably; the yearly figure is what drives the
architecture decision below.

**Correction to an earlier estimate in this log:** I had assumed 25-35
minutes per day's load without measuring it, then repeated that guess as
though it were measured. It was wrong by 3x. Measured now.

---

## 2026-09-22: No RDS. Parquet in S3 plus Athena, and static JSON output.

**Context.** The natural next step was RDS, and it does not fit the budget.
RDS costs are two separate things: **instance hours** (~$12-15/month
regardless of contents) and **storage** (scales with volume). Moving
observations out of Postgres solves the second and not the first — even a
tiny database holding only departures still pays for the instance.

Against a $5 soft cap and $10 hard cap, that is disqualifying on its own.
Observations at ~800GB/year would add ~$80/month in RDS storage on top.

**Decision.** No database instance at any layer.

    raw/      protobuf snapshots          (poller Lambda, already live)
      ↓       loader Lambda, hourly
    parsed/   observations as Parquet     (one file per input object)
      ↓       Athena: CREATE TABLE AS SELECT
    derived/  departures + headways as Parquet
      ↓       nightly percentile query
    static/   per-station JSON            → frontend reads directly

**Why Parquet.** Columnar, so a query touching 2 of 11 columns reads ~2/11 of
the file. Compresses far better than row-oriented data given how repetitive
these columns are. Athena bills per byte scanned (~$5/TB), so the format
directly reduces the bill, and the existing `year=/month=/day=/hour=`
partitioning is already the Hive convention Athena reads natively — a choice
made on day one for unrelated reasons.

**Idempotency without a database.** One output Parquet file per input object,
keyed to match. Reprocessing overwrites rather than appends, which replaces
the `ON CONFLICT DO NOTHING` that Postgres was providing.

**Why the frontend can be static.** The output is small: ~32k rows at
station × route × day-type × hour, or ~6.6k at coarser time bands. Roughly
400KB gzipped for the whole system, a few KB per station file. **More data
makes the numbers better, not the files bigger** — a p90 from 500 samples is
the same two bytes as one from 50. The expensive query runs once nightly; the
frontend renders numbers.

Carry a sample count `n` in the JSON. With six days of data some
station-hour buckets have single-digit samples, and a p90 from three
observations is noise; the frontend should say so rather than show a
confident wrong number.

**Costs accepted:**
- `pyarrow` is ~100MB, too large for a Lambda zip. The loader needs a
  container image. This is the main new thing to learn and it is useful for
  the exam regardless.
- Athena query latency is 2-10s with fixed startup overhead. Fine for
  derivation, unusable for an interactive dropdown — which is exactly why the
  frontend reads pre-computed JSON rather than querying live.
- No unique constraints, no updates, no indexes. File naming and partitioning
  carry what the database was carrying.

**Honest framing for the README:** the $5 target is self-imposed, and it was
set when the project was S3 and Lambda only. It is a real constraint that has
produced real design decisions — this entry being the clearest — but "I would
use RDS in production, here is what it costs and why" is the fair statement,
not "RDS was the wrong choice."

**Revisit when:** S3 storage for Parquet observations approaches the cap
(~$18/month at a year of data). Lifecycle rules to Glacier after 30 days
address that, since older observations are queried rarely if ever once
departures are derived.

---

## 2026-10-10: Errata

Housekeeping corrections to earlier entries, made in place and recorded
here so the log stays honest about its own edits:

- 2026-09-16 departure validation: referenced `queries/build_departures.sql`;
  the file is `queries/insert_departures.sql`.
- 2026-09-22 terminals: said "Eleven pairs" while listing twelve. Twelve
  stop/route pairs across eleven stops (247N serves the 2 and the 5).
- 2026-09-20 platform topology: removed a paragraph duplicated verbatim
  from the 2026-09-16 headways entry.

---

## 2026-10-10: Terminal detection re-run on the full loaded window

Re-running the round-seconds test over 2026-09-14 to 09-22 (605,319
departures, `trip_type = '0'`, pairs with >50 departures) finds **14**
stop/route pairs at exactly 100%, up from 12 on the 09-22 window.

**New:** 204S/5 (Nereid Av, a part-time short-turn terminal for the 5),
257N/4 (New Lots Av), 601S/6X (Pelham Bay, express variant).
**Dropped:** 250N/4 (Crown Hts–Utica Av).

The 4-train changes are one effect seen twice. With more overnight service
loaded, some 4 trips originate at New Lots and pass *through* Utica, so
Utica is no longer a pure origin and New Lots becomes one. That matches the
late-night 3/4 swap in Brooklyn (see the 2026-10-11 entry).

**Decided by:** the signature finds short-turn and part-time terminals that
no maintained list would include, which supports detecting terminals
empirically rather than hardcoding them.

---

## 2026-10-11: Headway charts, and what they surfaced

`scripts/plot_headways.py` charts median and p90 headway by hour for any
stop and route, reading the `headways` view so every image is reproducible.

**Choices:**
- *Weekdays by default.* Weekday and weekend timetables differ; mixing them
  blurs the rush-hour pattern. `--days` switches.
- *Hours with fewer than 10 headways dropped.* A p90 from three samples is
  noise.
- *Y-axis capped at 40 minutes, outliers labelled at the edge.* One thin
  overnight hour was flattening the whole chart. Clipped values print their
  true number, so nothing is hidden.
- *Lines break at hours with no data.* The first version drew a straight
  line across 18 hours when the 4 doesn't serve Nostrand Av, implying
  all-day service. Fixed by plotting on a full 0-23 grid with NaN gaps.

**Found:**
- *Late-night 3/4 swap at Nostrand Av.* The 3 serves it ~6am-10pm, the 4
  overnight. Recovered from observed departures alone, with no schedule data.
- *Midnight p90 at 96 St (78 min)* comes from two ~111-minute gaps, both
  ending ~00:52 on separate nights (09-17, 09-22). Under the 120-minute gap
  filter, so counted as service; consistent with planned overnight work.
- *A trip's final stop never records a departure.* The trip vanishes from
  the feed instead of shedding that stop. 250S/4 (Crown Hts-Utica Av) shows
  93 departures because most 4 trains terminate there. Mirror image of the
  origin-terminal issue.
- *Departure counts track stopping patterns, not station importance.* The 4
  shows ~100-340 departures at Manhattan local stops against ~1,250 at
  express stops; the smaller counts are late-night local running and
  reroutes.
- *Planned service changes show up in the departures.* Southbound 1 trains
  skipped 125-103 St for most of Sat 09-19 and Sun 09-20: 137 St recorded
  145 and 135 ordinary-service departures, 110 St only 14 and 23. Consistent
  with a weekend service change routing riders to 96 St to double back. On
  every weekday the two stations match exactly, which also shows the
  departure inference is consistent station to station.
- *Express runs for re-spacing.* Seven northbound 1 trips departed 96 St and
  137 St with no departures in between. Six were tagged `/` at both stations;
  one was tagged `0` at 96 St and `/` by 137 St. All seven left 96 St with a
  longer gap to the train ahead than that hour's median (1.4-2.2x, median
  ~1.8x); if gaps were random relative to the median, all seven landing
  above it would happen under 1% of the time. In six of seven the gap had
  shrunk by 1.5-3 minutes at 137 St, roughly what skipping four stops should
  save. The exception followed another express run 17 minutes earlier the
  same night. n=7, so a signal rather than a rate. Started from an anecdote
  from riding the line, then checked in the data.

**Follow-up:** the `headways` view's `trip_type = '0'` filter drops
skip-stop trains at the stops they *do* serve, slightly overstating headways
at 96 St and 137 St. Including `/` trips is likely safe, since skipped stops
never produce a departure row (the ±120s filter excludes them). Not changed
yet.