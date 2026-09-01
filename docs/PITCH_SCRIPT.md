# Demo walkthrough — claims, numbers, and what was tested

A factual summary of what the live demo demonstrates: the core argument,
what the deterministic pipeline actually decides, the measured results, and
one resilience test — with the real numbers and citations behind each
claim. Not a script; nothing here is delivery guidance.

## The core argument

A row-level fraud classifier scores one account at a time and cannot see a
farming ring, regardless of model quality — a farmed account is designed to
look ordinary in isolation (a real-looking phone number, a plausible order,
no single field that trips a rule). The signal exists only *across*
accounts at once: the same device behind multiple "different" signups, a
referral bonus claimed within hours of signup, order values that are
identical to the rupee. This is a graph problem, not a row-classification
problem.

## Hard-signal detection

Accounts sharing a payment instrument, a device, or an IP subnet form
edges in the entity graph — purple for shared instrument, red for shared
device, orange for IP-subnet overlap. Two distinct people legitimately
sharing a payment instrument is rare enough that this is treated as a
near-certain signal: a connected component in the graph, not a model
score.

## The deterministic pipeline, and where the LLM fits

Before any LLM involvement, five deterministic stages already decide
whether a cluster is suspicious, from features including: a shared
payment instrument, a signup burst measured in days rather than months, an
order-value coefficient of variation near zero (near-identical amounts),
and members going silent after claiming a bonus. Only a cluster that
survives this filter reaches an LLM, which writes a plain-English case and
selects exactly one bounded action: `HOLD_BONUS`, `MANUAL_REVIEW`, or
`NO_ACTION`. It cannot ban an account or block a transaction — a human
executes the final action.

## Confounder handling

A real, legitimate dense cluster — a hostel's shared wifi, an entire
office on one network — shares the same graph shape as a fraud ring:
many accounts, dense shared attributes. The system correctly leaves such
clusters unflagged based on organic evidence: activity spread over months
(not a burst), diverse order values (not templated), ongoing engagement
(not dormancy after a claim). Actively looking for evidence that a cluster
is legitimate, rather than only scoring evidence of fraud, is a first
-class stage in the pipeline, not an afterthought.

## Metrics (held-out split, never used to tune any threshold)

- Hard-signal ring recall: **100%** — all 40 planted hard-signal rings
  detected.
- Soft-signal ring recall: **85%** — the genuinely harder case, with no
  shared device or instrument at all, only IP overlap and referral timing.
  Every miss is the deliberately "hard mode" ring variant (slower claims,
  noisier order values); zero misses on the easy soft rings.
- Confounder false-positive rate: **5%** (2 of 40 planted legitimate
  clusters wrongly flagged) — both are households with a compressed,
  borderline signup window that failed the spread-out check. Zero false
  positives on the easy confounders.
- Cost asymmetry: a missed ring costs real, paid-out money. A
  wrongly-flagged legitimate cluster costs a delayed bonus pending human
  review, since nothing here auto-executes. This asymmetry is why the
  filter defaults to not flagging when evidence is ambiguous.

## External validation

The same unmodified clustering, run against real Bitcoin transaction data
(the Elliptic dataset) with zero device or payment signals available,
achieved a real **7.3x lift** over random-guess baseline — read as a
floor, not a ceiling, for what the same architecture should do on the
identity-linking signals it was actually designed around. Full methodology
in [`EXTERNAL_VALIDATION.md`](EXTERNAL_VALIDATION.md).

## Failure-injection test

`python -m backend.demo_failure_injection` deliberately corrupts device
IDs, IPs, and payment instruments on 15 real accounts, then reruns the
full pipeline against the result. Outcome: zero exceptions, zero spurious
edges. Critically, a missing device ID on two different accounts is never
treated as "they share a device" — a real bug found during development
(an earlier version of the code was one `NaN == NaN` comparison away from
clustering every account with missing data together and flagging all of
them as a ring), fixed, with a regression test added to keep it fixed.
