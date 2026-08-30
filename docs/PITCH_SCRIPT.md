# Pitch video script (5 minutes)

Target structure per the submission brief: problem (30s) → live demo (2.5min) → honest metrics (1min) → one failure handled gracefully (1min).

---

## 0:00–0:30 — The problem

> "Every promo-abuse detector I've seen scores one account at a time: is *this* signup fraudulent. That architecture cannot see a farming ring, no matter how good the model is — because a farmed account is *designed* to look ordinary alone. Real-looking phone number, plausible order, no red flag. The fraud only becomes visible when you look at accounts *together*: the same device behind thirteen 'different' signups, a referral bonus claimed within two hours of signup, order values that are suspiciously identical down to the rupee. That's not a classification problem. That's a graph problem — so I built a graph."

**Screen:** title slide or README open, graph-vs-classifier paragraph visible.

---

## 0:30–3:00 — Live demo

**[0:30–1:15] Show the graph forming.**
Open the Streamlit dashboard — start on **Overview** for two seconds to establish scale (7,500 accounts, dozens of rings caught, dozens of confounders spared), then go to **Flagged clusters**, pick a hard-signal row from the table (any of them — sort by confidence and take the top one), and open its **Graph** panel.
> "This is a cluster that all signed up within a few days of each other. Watch the edges: purple means they share one payment instrument, red means shared device, orange means the same IP subnet. Two different people legitimately sharing a payment instrument is rare — this is a near-certain signal, and it's a *connected component* in the graph, not a model score."

**[1:15–2:00] Show a flagged case card.**
Stay on the same row's detail panel.
> "Here's the case the system built. The deterministic pipeline — five stages, zero LLM calls — already decided this is suspicious: shared instrument, a signup burst measured in days not months, an order-value coefficient of variation near zero — that means the order amounts are practically identical — and most of the members went silent after claiming their bonus. *Only now* does an LLM see it, and only to write this up in plain English and pick one bounded action: `HOLD_BONUS`. It cannot ban anyone. It cannot block a transaction. A human executes the final call."

**[2:00–3:00] Show a confounder correctly left alone.**
Switch to **Confounders left alone**, filter to "hostel" or "office", pick a large one that's correctly unflagged.
> "Now here's the part that actually matters for a submission like this: this is a *planted, legitimate* cluster — dozens of students on the same hostel wifi, or an entire office on the same network. Same kind of dense, shared-attribute cluster as the ring I just showed you. But the system left it alone, and it tells you exactly why: activity spread out over months, diverse order values, ongoing engagement — not a burst, not templated, not dormant. The entire job of the last deterministic stage is to actively look for evidence a cluster is *legitimate* and suppress the flag. That's not a nice-to-have. That's the difference between a system a trust-and-safety team can actually run and one that gets shut off after week one for punishing real customers."

---

## 3:00–4:00 — Honest metrics

Switch to **Metrics**.
> "On a held-out split — never used to tune any threshold — across 40 planted rings per category: the hard-signal rings, the ones sharing a device or payment instrument: 100% recall. The soft-signal rings, the ones with no shared device or instrument at all, only IP overlap and referral timing: 77.5%. That number is lower on purpose, and I'm not going to pretend otherwise — soft-signal-only detection is the genuinely hard case. And it's not scattered, either: every single miss is my deliberately 'patient' ring variant, the ones with slower claims and noisier order values — zero misses on the easy soft rings. Confounder false-positive rate: 5%, two out of forty planted legitimate clusters wrongly flagged — and both of those are households with a compressed, borderline signup window that fooled the spread-out check. Same story: zero false positives on the easy confounders.

> Look at the difficulty breakdown on this page — that's not me hiding a scattershot failure rate behind an average. Every miss traces to a specific, deliberately-hard planted case.

> And here's the framing that actually matters for the business: a missed ring costs real, paid-out money. A wrongly-flagged legitimate cluster costs a *delayed* bonus, pending human review — because nothing here auto-executes. That asymmetry is why the filter defaults to *not* flagging when evidence is ambiguous."

**Optional one-liner, only if the 3:00–4:00 segment is running under time** (the script above is already budgeted to the minute — don't force this in and blow the timing; cut it first if anything runs long):
> "One more thing worth ten seconds: I also ran this exact, unmodified clustering against real Bitcoin transaction data — zero device or payment signals to lean on, the hardest domain I could find — and it still landed a real 7.3x lift over random guessing. That's the floor for what it does on the signals it was actually built for, not the ceiling."

---

## 4:00–5:00 — One failure, handled gracefully

Switch to terminal (or pre-recorded terminal output) → run `python -m backend.demo_failure_injection`.
> "Real account data has gaps — a fingerprint SDK that failed to load, an IP that never got logged. I deliberately corrupted device IDs, IPs, and payment instruments on fifteen real accounts and reran the full pipeline against it."

Let the script output scroll: corruption applied, graph built, zero exceptions, zero spurious edges.
> "No crash. And critically — a missing device ID on two different accounts never got treated as 'they share a device.' A gap is a gap, not a shared value. That's a real bug I caught building this: an earlier version of the code was one `NaN == NaN` away from clustering every account with missing data together and flagging all of them as a ring. Fixed it, wrote a test that proves it stays fixed, and that's the honest story — not that this system is perfect, but that its failure modes are visible, explained, and closed one at a time."

**Close:**
> "Graph problem, not a row-classification problem. Deterministic and auditable first, LLM last and bounded. And confounders as a first-class citizen, not an afterthought. That's the submission."

---

## Recording notes

- Pre-load the Streamlit dashboard (`streamlit run frontend/streamlit_app.py`) and let clusters/graphs render *before* recording — the pyvis graphs take a second to lay out via physics simulation.
- Have a terminal window ready with the venv activated for the failure-injection segment.
- If narrating live, rehearse the 2:00–3:00 confounder segment once — it's the section most likely to run long and it's the section that differentiates this submission most, so it's worth protecting the time for.
