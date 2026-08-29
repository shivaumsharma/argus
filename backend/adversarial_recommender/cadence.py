"""
Cadence gate. Attack generation runs on a defined schedule, not literally
continuously -- an unthrottled generator produces alert fatigue and turns
human review into rubber-stamping, which defeats the entire point of the
approval gate. See docs/ADVERSARIAL_RECOMMENDER.md's Cadence section for
the justification of the default chosen here.

Default: MIN_HOURS_BETWEEN_AUTO_ROUNDS = 24. Deliberately conservative --
this is a demonstration system with a synthetic attack generator, not a
live-traffic monitor, so there is no cost to reviewer time from checking
less often, and every hour saved by running more often is an hour closer to
a reviewer starting to click "approve" without really reading the Stage 4
numbers. A manual trigger (--force) is always allowed regardless of cadence
-- the gate only throttles the *automatic* schedule, not a human explicitly
asking for a round right now.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "data" / "adversarial_recommender"
STATE_FILE = STATE_DIR / "cadence_state.json"

MIN_HOURS_BETWEEN_AUTO_ROUNDS = 24


def _load_state() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return {"last_round_at": None, "round_number": 0}
    return json.loads(STATE_FILE.read_text())


def _save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def next_round_number() -> int:
    return _load_state()["round_number"] + 1


def can_run(force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "manual trigger (--force)"
    state = _load_state()
    if state["last_round_at"] is None:
        return True, "no round has run yet"
    last = datetime.fromisoformat(state["last_round_at"])
    elapsed = datetime.now() - last
    min_gap = timedelta(hours=MIN_HOURS_BETWEEN_AUTO_ROUNDS)
    if elapsed >= min_gap:
        return True, f"{elapsed} since last round (>= {MIN_HOURS_BETWEEN_AUTO_ROUNDS}h minimum)"
    remaining = min_gap - elapsed
    return False, f"cadence gate: {remaining} remaining before the next automatic round is allowed"


def record_round(round_number: int):
    state = _load_state()
    state["last_round_at"] = datetime.now().isoformat()
    state["round_number"] = round_number
    _save_state(state)
