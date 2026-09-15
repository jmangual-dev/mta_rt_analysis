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
