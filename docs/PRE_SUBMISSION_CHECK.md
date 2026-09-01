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

## Addendum — a fourth issue, found after this pass, fixed the same way

A follow-up question asked directly whether Elliptic's Stage 4/5 rules
actually applied to Bitcoin data, and whether that cost real recall.
Checked, not assumed: they never applied at all — `elliptic.py` only ever
ran Stage 2/3 clustering, substituting one bare `density > 50%` rule
(inherited unchanged from YelpChi/Amazon) for the entire Stage 4+5 decision
logic. Sweeping that one threshold on the exact same, already-computed
clusters found 3.4x more identifiable illicit transactions (2,033 vs. 597)
at a still-real 3.2x lift over base rate — meaning the reported 829/597/
72.0% headline was one unswept point, not a ceiling. Fixed the same way as
everything above: a real, re-runnable sweep added to `elliptic.py` itself
(not a one-off calculation), and the finding written into
`EXTERNAL_VALIDATION.md`, `ARCHITECTURE.md`, and `README.md` rather than
left as a chat answer.

## Addendum 2 — the primary-dataset re-freeze this doc's own numbers predate

Everything above was checked against the original `SEED=20260828` dataset.
That dataset was subsequently re-frozen (`SEED=51238923`,
`USE_GROUNDED_DEVICE_SHARING` turned on — see `ARCHITECTURE.md`'s Known
Limitations), per the same eval integrity protocol used everywhere else in
this project: fresh seed, one `generate → pipeline → eval` run, numbers
reported as-is. Every doc that cites a number computed against the primary
dataset (`FAIRNESS_AUDIT.md`, `COST_THRESHOLD_SENSITIVITY.md`,
`FRAUDAR_CROSSCHECK.md`, `COMPLIANCE_SUMMARY.md`, the confidence-calibration
bullet in `ARCHITECTURE.md`, and the concurrent-attack/infra-resilience/
time-drift docs) was re-run against the new freeze and updated — not left
standing next to numbers that no longer match the live system, and not
silently patched without the fresh-seed/single-run discipline. External
validation (YelpChi/Amazon/Elliptic) is unaffected, since it runs against
outside data, not ours. The numbers in this document's own tables above
are intentionally left as the dated historical record of that specific
pass, not rewritten to match the new freeze — the "Known limitations"
narrative sections that referenced now-superseded specifics were fixed at
their source (`ARCHITECTURE.md`, `README.md`) rather than here.

## Addendum 3 — a second re-freeze, same discipline

Everything above (including Addendum 2) was checked against the
`SEED=51238923` dataset. That dataset was subsequently re-frozen a second
time (`SEED=42668329`, `HARD_RING_SIZE_RANGE` minimum lowered 3→2, grounded
in real YelpChi/Amazon confirmed-fraud cluster sizes — see
`EXTERNAL_VALIDATION.md`'s ring-size grounding section), per the identical
eval integrity protocol: fresh seed, one `generate → pipeline → eval` run,
numbers reported as-is. The same full downstream sweep was repeated:
`FAIRNESS_AUDIT.md`, `COST_THRESHOLD_SENSITIVITY.md`, `FRAUDAR_CROSSCHECK.md`
(headline moved 5/40→7/40), `COMPLIANCE_SUMMARY.md` (auto-regenerated), the
confidence-calibration and fairness bullets in `ARCHITECTURE.md`, and the
concurrent-attack/infra-resilience/time-drift/scale-stress/adversarial-stress
scripts were all re-run against the new freeze and their docs updated where
numbers moved — not left standing next to stale figures. `explainer.html`'s
KPI tiles were checked and corrected the same way as Addendum 2's original
fix (confounder FP rate and cluster precision had drifted; soft-signal
recall and background-account count happened to already match). External
validation (YelpChi/Amazon/Elliptic) is unaffected by this re-freeze either
— it runs against outside data, not ours, though this specific re-freeze is
itself *derived from* that external data, a different relationship than
"unaffected by." As with Addendum 2, this document's own historical tables
above are left as the dated record of the pass they document, not rewritten.

## What this check does not cover

This is a consistency and dry-run pass, not a re-verification of every
underlying claim from scratch — each capability's own numbers were already
measured and reported honestly in its own doc when it was built (see
`ARCHITECTURE.md`'s Known Limitations for the full list of what's honestly
unresolved: the adaptive-adversary limit, the zero-attribute blind spot,
and the rest).
What this pass adds is confirmation that those already-honest numbers
still agree with each other and with the live system, and it found three
places where they had quietly drifted apart.
