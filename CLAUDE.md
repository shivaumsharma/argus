# Argus — working rules

## 🚫 Do not push to GitHub until 2026-09-14

**No `git push` (to `origin` or any remote) until September 14, 2026 — even if asked to commit or if a commit already exists locally.** Local commits are fine and expected; pushing is not, until that date.

**Why:** this repo (`shivaumsharma/argus`) is the live submission for a Razorpay hackathon (AI Buildathon 2026, Track 02) that is still under evaluation/review as of this writing. The project is also being extended with content aimed at a Palo Alto Networks job application (see below) — none of that should become visible on the public GitHub repo while Razorpay's reviewers may still be looking at it.

If a task seems to call for a push (deploying, sharing a link, "make it live"), stop and ask the user first — don't assume the date has passed or that they meant to override this. If the user explicitly says the freeze is lifted (e.g. confirms it's past Sept 14, or says the Razorpay review is over), you may resume pushing — but get that confirmation in the conversation itself before doing so, don't infer it from the calendar alone.

## Project goal: Palo Alto Networks, not just the hackathon

Argus's real end goal, per the user (2026-09-11), is bigger than the hackathon: it's meant to be impressive enough to help land an interview/offer at **Palo Alto Networks**. The project's actual technical core — graph-based ring/anomaly detection, explainable-by-design architecture, deterministic policy enforcement, adversarial-robustness testing, rigorous external-validation methodology — has real, honest overlap with security analytics (coordinated-attack/botnet detection, alert-fatigue reduction via false-positive suppression), worth surfacing when relevant.

How explicit vs. implicit that Palo Alto Networks tie-in should be (naming them directly vs. a general "this applies to security analytics too" framing) is the user's call, not something to assume — check with them before adding an explicit company reference anywhere in the project. Until the push freeze above lifts, any such content stays local-only regardless.

When weighing polish/framing decisions on this project, consider how it reads to a cybersecurity-company recruiter/hiring team, not only a hackathon judge — the two audiences mostly reinforce each other, don't trade one off against the other.
