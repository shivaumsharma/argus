# Argus — working rules

## ✅ Push freeze lifted (2026-09-14)

The Razorpay hackathon result came back and the user explicitly confirmed in conversation on 2026-09-14 that pushing to GitHub is fine now. The prior "no push until 2026-09-14" rule (below, kept for history) no longer applies — normal push behavior (confirm before pushing, per the general safety rules, but no standing freeze) resumes.

<details>
<summary>Former rule (2026-09-11 to 2026-09-14, now lifted)</summary>

**No `git push` (to `origin` or any remote) until September 14, 2026 — even if asked to commit or if a commit already exists locally.** Local commits are fine and expected; pushing is not, until that date.

**Why:** this repo (`shivaumsharma/argus`) was the live submission for a Razorpay hackathon (AI Buildathon 2026, Track 02) still under evaluation/review as of 2026-09-11. The project was also being extended with content aimed at a Palo Alto Networks job application (see below) — none of that was meant to become visible on the public GitHub repo while Razorpay's reviewers might still be looking at it.

</details>

## Project goal: Palo Alto Networks, not just the hackathon

Argus's real end goal, per the user (2026-09-11), is bigger than the hackathon: it's meant to be impressive enough to help land an interview/offer at **Palo Alto Networks**. The project's actual technical core — graph-based ring/anomaly detection, explainable-by-design architecture, deterministic policy enforcement, adversarial-robustness testing, rigorous external-validation methodology — has real, honest overlap with security analytics (coordinated-attack/botnet detection, alert-fatigue reduction via false-positive suppression), worth surfacing when relevant.

How explicit vs. implicit that Palo Alto Networks tie-in should be (naming them directly vs. a general "this applies to security analytics too" framing) is the user's call, not something to assume — check with them before adding an explicit company reference anywhere in the project. Until the push freeze above lifts, any such content stays local-only regardless.

When weighing polish/framing decisions on this project, consider how it reads to a cybersecurity-company recruiter/hiring team, not only a hackathon judge — the two audiences mostly reinforce each other, don't trade one off against the other.
