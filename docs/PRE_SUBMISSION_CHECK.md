# Pre-submission consistency check

A full end-to-end dry run of the live dashboard exactly as a judge would use
it, plus a cross-reference pass over every doc's numbers against every
other doc and against the live, current code — not a re-assertion that
things are fine, but an actual check, with what was found and fixed below.

## Dashboard dry run — every tab, live

Ran `streamlit run frontend/streamlit_app.py` and walked every page:
**Overview, Flagged clusters, Confounders left alone, Graph explorer, Live
injection, Metrics (including the two sections newly wired in this pass —
FRAUDAR and the scale stress test), Compliance, Recommendations, Audit
log.** Every page rendered its live-computed numbers with zero fatal
errors, and every number checked against another page or a doc matched:

- 74 flagged clusters, 41 hard-signal / 33 soft-signal, 73 `HOLD_BONUS` / 1
  `NO_ACTION` — identical across Flagged Clusters, Compliance, and
  `COMPLIANCE_SUMMARY.md`.
- 40 confounders / 1 wrongly flagged (2.5%) — identical across
  Confounders, Metrics, Compliance, `FAIRNESS_AUDIT.md`, and
  `ARCHITECTURE.md`.
- FRAUDAR's 15/40 (37.5%) and the scale test's 79.3s at 375,000 accounts —
  the new Metrics sections render numbers pulled live from
  `data/processed/fraudar_analysis.json` / `scale_stress_test.json`,
  matching `FRAUDAR_CROSSCHECK.md` and `SCALE_STRESS_TEST.md` exactly.
- The Recommendations page's History (1) and the Audit Log's
  `validated_approved` entry match the round-2 resolution written up in
  `ADVERSARIAL_RECOMMENDER.md`.

**One pre-existing, non-fatal item noted, not fixed**: Graph Explorer's
embedded network visualization (a third-party `pyvis` component) triggers
a handful of browser console 404s, most likely a bundled asset the
component references. The graph itself still renders and is fully
interactive — confirmed visually, not just checked in the console. This
predates every change made this session and is out of scope for this pass.

## Cross-doc numeric consistency — three real staleness issues found and fixed

**1. `docs/explainer.html` — the "read this first" page — had stale
headline numbers from an earlier dataset snapshot.** It's the single
highest-visibility document (linked first in `README.md`), so this was
worth catching, not assuming fine. Found by direct comparison against the
current frozen dataset (pulled exact per-difficulty counts from
`backend.reporting` rather than eyeballing), not by inspection alone:

| Number | Was (stale) | Now (verified against live data) |
|---|---|---|
| Soft-signal ring recall | 77.5% (31 of 40) | **82.5% (33 of 40)** |
| Confounder false-positive rate | 5.0% (2 of 40) | **2.5% (1 of 40)** |
| Cluster-level precision | 97.3% | **98.6%** |
| Background accounts | 5,964 | **5,994** |
| Soft rings, hard-mode difficulty | "7 detected, 9 missed" | **"9 detected, 7 missed"** |
| Confounders, tight difficulty | "1 spared, 2 wrongly flagged" | **"2 spared, 1 wrongly flagged"** |
| Honest-part prose | "9 missed rings," "both wrongly-flagged confounders" | **"7 missed rings," "the single wrongly-flagged confounder"** |

All six corrected in place; the page's structure and argument (six
deterministic stages, three bounded actions, what it doesn't claim) needed
no changes — only the specific numbers had drifted from an earlier
snapshot of the dataset.

**2. `README.md`'s Elliptic paragraph still used pre-reframe language.**
It read "the deliberately weakest-fit domain tested," the framing
`EXTERNAL_VALIDATION.md` and `ARCHITECTURE.md` replaced earlier this
session with "deliberately the hardest test available... a generalization
proof-of-concept... the floor, not the ceiling." `README.md` was the one
place that edit never propagated to. Fixed, and the Amazon `net_usu`
investigation (tested 3 ways, confirmed to add nothing) was added to the
same paragraph since it was also missing there.

**3. `README.md`'s adversarial-recommender paragraph didn't mention the
round-2 resolution.** It described the round-2 finding (a fix that doesn't
close its own gap) but stopped there — no mention of the audit-trail
confirmation, the computed root cause, the round-3 suspicion-side attempt,
or the exhaustive parameter sweep that closes the question. Updated to
summarize the resolution, matching `ADVERSARIAL_RECOMMENDER.md` and
`ARCHITECTURE.md`.

## Navigation and doc-inventory accuracy

`README.md`'s project-structure listing was checked against the actual
files on disk, not assumed current: `frontend/app_pages/compliance.py` (a
real, working tab, confirmed in the dry run above) was missing from the
`frontend/` listing, and this session's new docs
(`CONCURRENT_ATTACK_STRESS_TEST.md`, `INFRASTRUCTURE_RESILIENCE_TEST.md`,
`TIME_DRIFT_SIMULATION.md`, and this file) were missing from the `docs/`
listing. The Quickstart command list and the `backend/` file listing were
also missing the three new scripts
(`concurrent_attack_stress_test.py`, `infra_resilience_test.py`,
`time_drift_simulation.py`). All added. No page or script is now described
that doesn't exist, and nothing that exists is left undocumented.

## Regeneration check

`python -m backend.compliance_report` was re-run fresh as part of this
pass. Result: only the generation timestamp changed — every underlying
number was already consistent with the current code and current frozen
dataset, confirming the earlier fixes this session (fairness rebuild,
calibration rebuild, the data_io.py malformed-record fix) didn't leave
anything stale behind in the one doc that's supposed to be fully
auto-generated.

## What this check does not cover

This is a consistency and dry-run pass, not a re-verification of every
underlying claim from scratch — each capability's own numbers were already
measured and reported honestly in its own doc when it was built (see
`ARCHITECTURE.md`'s Known Limitations for the full list of what's honestly
unresolved: the adaptive-adversary limit, the zero-attribute blind spot,
the primary-dataset re-freeze still staged but not applied, and the rest).
What this pass adds is confirmation that those already-honest numbers
still agree with each other and with the live system, and it found three
places where they had quietly drifted apart.
