# Adversarial evasion via graph fragmentation

Every adversarial test built before this one varies *what a ring looks like
once formed*: `attack_generator.py` drops the shared hard signal entirely
(soft-only evasion), `concurrent_attack_stress_test.py`'s
`build_soft_masking_ring()` keeps one shared device but fakes organic timing
and spending, `time_drift_simulation.py` escalates those same behavioral
knobs across periods. None of them vary the **shape** of the sharing graph
itself while holding ring size and behavior fixed — the actual gap this test
closes, and the question Palo Alto Networks' whole detection philosophy
centers on: does the system hold up against an adversary who knows how it
works and is actively restructuring to slip under it?

## Design — three tactics, isolated so each is attributable on its own

1. **Sparsify edges.** Instead of 12 accounts all sharing one device (a
   single dense clique — Stage 2's easiest case), split the same 12 accounts
   into *K* independent pods, each sharing only its own device internally,
   zero edges between pods. "Run K small device/kit setups instead of one
   big one."
2. **Mimic legitimate density.** At the point of complete atomization (pod
   size 1 — no shared device at all), does giving the group one other real
   -world attribute in common (an IP subnet, the way accounts on the same
   physical network naturally would share one) let it hide as an ordinary
   shared-infrastructure cluster instead of a fraud ring?
3. **Spread activity over time.** Layered on top of (2): accounts atomized,
   subnet-linked, *and* their signups spread across roughly a month instead
   of launched together in a burst.

Behavior is held deliberately, obviously suspicious throughout all three
tactics (a 2-day signup burst per pod, templated near-identical order
values, a fast referral claim followed by total silence — the complete
claim-then-dormant archetype Stage 4 actually reads
`claim_then_dormant_frac`/`bonus_claim_velocity_hours` from, not just the
order-timing half of it) so that any recall change is attributable to the
structural or temporal tactic being tested, not to also faking organic
behavior — that separate axis is already covered by
`concurrent_attack_stress_test.py` and `time_drift_simulation.py`.

Injection is the same isolated pattern used throughout this project's
adversarial tests: a disposable tempdir copy of `data/raw/`, unmodified
Stage 1-5 pipeline, cleaned up in a `finally` block, never touching the
frozen dataset. Fresh seed (`71940852`), never reused elsewhere.

## Part 1: sparsifying alone does not work as evasion

| Pods | Pod size | Members captured | Recall |
|---|---|---|---|
| 1 | 12 | 12/12 | 100% |
| 2 | 6 | 12/12 | 100% |
| 3 | 4 | 12/12 | 100% |
| 4 | 3 | 12/12 | 100% |
| 6 | 2 | 12/12 | 100% |

**100% recall holds all the way down to 2-member pods.** Stage 5 scores each
candidate cluster on its own behavioral merits regardless of size — a small
pod with blatant claim-then-dormant behavior is exactly as catchable as one
big cluster. Fragmenting the shared-device graph into smaller pieces does
not, by itself, buy an adversary anything.

## Part 2: the true limiting case — complete atomization

Pod size 1 means literally zero shared device between any two members — the
floor of tactic 1. Three isolated conditions, so each subsequent tactic's
real effect is attributable on its own, not blended together:

| Condition | Shared subnet | Signup spread | Members captured | Recall |
|---|---|---|---|---|
| (a) Atomized, tight timing, no other shared signal | no | 0 days | 0/12 | **0%** |
| (b) Atomized, tight timing, shared IP subnet | yes | 0 days | 12/12 | **100%** |
| (c) Atomized, spread over time, shared IP subnet | yes | up to ~33 days | 12/12 | **100%** |

**(a) is a real limitation, but not a new one.** With zero shared attributes
of *any* kind — no device, no instrument, no subnet, nothing — none of the 12
accounts ever form a candidate cluster at all. This is the same
zero-shared-attribute blind spot already disclosed for isolated Elliptic
transactions and this project's own stated architecture limits
(`ARCHITECTURE.md`'s Known Limitations) — confirmed here directly in this
system's own primary domain, rather than assumed to transfer from an
external dataset.

**(b) and (c) both fail to hold that evasion.** The instant the atomized
accounts share *any* other real-world attribute — here, an IP subnet, which
this project's own Stage 1 already treats as a soft signal — Stage 3's
**existing** Louvain clustering, with zero code change, recovers all 12
members at 100% recall. Spreading the same accounts' signups across roughly
a month on top of that (c) does not undo the recovery either. The evasion
floor is genuinely "zero shared attributes of any kind," not "zero shared
*hard* signal" — an important, more precise statement of the actual limit
than "shares no device" alone would suggest.

## Reading this honestly

**No countermeasure was tuned, because nothing tested actually degraded
detection short of the theoretical floor.** That's reported as a real,
disclosed robustness finding, not manufactured by picking an easy attack to
declare beaten — the honest alternative would have been to report exactly
this null result, and that's what's reported. An adversary who wants to beat
this system's detection specifically by restructuring their sharing graph
has exactly one working lever among the three tested here: eliminate every
shared attribute entirely, including soft ones like IP subnet, which in
practice usually means operating from genuinely distinct devices, payment
instruments, *and* network locations for every single account — a
significantly higher operational cost than simply splitting a fraud ring
into smaller device pods, and a cost this system's own soft-signal layer
already imposes without any change made in response to this test.

**What this test does not establish:** that no evasion tactic exists. It
tested three specific, named structural/temporal tactics — it did not test,
for example, an adversary who also fakes organic behavioral signals *at the
same time* as fragmenting the graph (a combined attack), which is a
reasonable next axis but a different, not-yet-built test, not something this
result should be read as already covering.

## Running it yourself

```bash
python -m backend.adversarial_evasion
```

The dashboard's Resilience page reads the identical JSON
(`data/processed/adversarial_evasion.json`) this script writes.
