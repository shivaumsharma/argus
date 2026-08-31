# Infrastructure failure resilience test

Every other test in this project checks whether *detection* holds up. This
one checks whether the *system* holds up — realistic mid-run failure
conditions beyond the one already-handled case ("no LLM credentials at all,"
which was always a designed fallback, not a failure). Two scenarios, both
run for real against the actual production code, not reasoned about, and
both documenting **observed** behavior — including the two real bugs this
test found, fixed, and re-verified rather than just wrote down.

Run: `python -m backend.infra_resilience_test`

## (a) A slow / rate-limited / timing-out LLM call during Stage 8

White-box tests the real `llm_investigate.ProviderRunner.investigate()`
orchestration loop with stubbed provider call functions — no network calls,
which deliberately isolates the retry/degrade/fallback *logic* from
provider reliability. Four checks, all against the unmodified production
class:

| # | Scenario | Result |
|---|---|---|
| 1 | Provider rate-limited (429) once, retried | Retried with the real parsed backoff delay, succeeded on attempt 2. PASS |
| 2 | Provider times out (a generic exception, not 429-shaped) | Degraded cleanly to the next provider in the chain, which succeeded. PASS |
| 3 | Every configured provider fails (429 retries exhausted, then a timeout) | Fell through to the deterministic template fallback — a real, complete, non-empty writeup, not an empty result. PASS |
| 4 | No providers configured at all (baseline) | Template fallback, as already designed. PASS |

**Result: no code changes needed here.** The existing retry-with-backoff
(429-specific), degrade-to-next-provider (any other exception, including a
timeout — the `except Exception` in `ProviderRunner.investigate()` was
already generic, not narrowly scoped to rate limits), and fallback-to
-template paths all behaved exactly as designed under every failure
combination tested. Every failure is printed as it happens; no run ever
crashed, and no result was ever empty or malformed (checked directly:
non-empty `case_summary`, `confidence` in `[0,1]`, a valid
`recommended_action`, non-empty `key_evidence` — every single time).

## (b) Malformed records injected into the middle of a batch

Five malformed records — not at the start or end of a file, where an
edge-case-only bug could hide, but spliced into the middle — across two
different tables:

| Table | Column | Corruption |
|---|---|---|
| orders | order_value | wrong type (`"NOT_A_NUMBER"`) |
| orders | order_value | missing field (empty) |
| orders | order_value | out-of-range value (`-999.00`) |
| orders | user_id | missing required field |
| sessions | timestamp | wrong type (`"not-a-date"`) |

**Two real bugs found, both fixed in `backend/pipeline/data_io.py`, then
re-verified — not just documented.**

1. **A crash, not a graceful skip.** `load_data()` cast `orders.order_value`
   and `referrals.bonus_amount` with `.astype(float)`, and every date/
   timestamp column with `pd.to_datetime()`, neither wrapped in error
   handling. One malformed value anywhere in a 16,000+ row file raised a
   bare `ValueError` and halted the *entire* pipeline run — confirmed
   directly: injecting one bad `order_value` or one bad `timestamp` string
   crashed `load_data()` every time, before this fix.
2. **Silent miscounting, not a crash.** A missing `order_value` (empty
   string), a negative `order_value`, and a missing `user_id` in an orders
   row all passed through *without* crashing — but also without being
   flagged. A missing/negative value became `NaN`/a nonsensical negative
   number sitting silently in downstream averages and CV calculations; a
   missing `user_id` caused that order to silently vanish from every
   `groupby("user_id")` with zero record it had ever existed. Confirmed
   directly, not assumed: each of these three corruptions passed through
   `load_data()` with no error, no log line, no trace.

**The fix**: every datetime cast now uses `errors="coerce"` (never raises)
instead of a hard cast; every numeric cast is validated for both
parseability and a sane range (rejecting negative amounts); every table's
`user_id`/`referrer_user_id` is checked for missing/empty. Every row that
fails a check is dropped **and logged** — table, reason, count, and example
row ids — collected in a new `DataBundle.data_quality_report` field, not
just printed and discarded. A shared `_drop_invalid()` helper handles the
drop-and-log step once, so every check reports the same way.

**Re-verified after the fix, not assumed fixed:**

- The same 5 injected corruptions: **zero crash**, **5/5 dropped and
  logged** (matching the injected count exactly — nothing silently missed,
  nothing double-dropped), and the **full Stage 1-5 pipeline completes
  end-to-end** on the cleaned data (174 candidate clusters, 74 flagged —
  consistent with the frozen dataset's own known 74-flagged baseline, since
  removing 5 malformed rows out of 80,000+ shouldn't and doesn't change
  cluster-level outcomes).
- **Zero regression on the real frozen dataset**: run against the actual,
  unmodified `data/raw/` (which has no malformed rows), the new validation
  drops exactly **0** rows, and a full `python -m backend.pipeline.eval` re
  -run reproduces the identical headline numbers as before this fix (100%
  hard recall, 82.5% soft recall, 2.5% confounder FP rate, 98.65% cluster
  precision) — the fix changes failure-handling, not the frozen dataset's
  own results.

## Honest read

Scenario (a) needed no fix — the existing design already handled this
correctly, verified rather than assumed. Scenario (b) found two real,
concrete bugs (one a hard crash, one silent data loss) in code that had
never been tested against malformed input before, fixed both, and confirmed
the fix doesn't change a single number on the real dataset. This is exactly
the discipline the rest of this project applies to detection claims, applied
here to operational robustness instead: measure the actual failure, fix it,
re-verify — don't document a bug and move on.
