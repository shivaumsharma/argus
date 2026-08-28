"""
Freeze / reset the live dataset around demo actions that mutate it.

The live-injection demo control appends real rows to data/raw/*.csv and
reruns the real pipeline -- that's the point, it should look exactly like a
new ring landing in the system. But that would silently drift the dataset
away from the frozen, single-pass, fresh-seed run the eval numbers in the
README/ARCHITECTURE docs were measured on. Freezing a snapshot before a demo
and offering a one-click reset keeps "live injection" from quietly
invalidating "clean holdout eval" -- the two things can coexist as long as
one always returns to the other.
"""

import shutil

from .pipeline.data_io import GT_DIR, PROCESSED_DIR, RAW_DIR, ROOT

SNAPSHOT_DIR = ROOT / "data" / "frozen_snapshot"
DB_PATH = ROOT / "data" / "app.db"

RAW_FILES = ["accounts.csv", "sessions.csv", "referrals.csv", "payment_instruments.csv", "orders.csv"]
PROCESSED_FILES = ["clusters.json", "eval_report.json", "cases.json", "confidence_calibration.json"]


def freeze_snapshot(verbose=True):
    (SNAPSHOT_DIR / "raw").mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / "processed").mkdir(parents=True, exist_ok=True)
    for name in RAW_FILES:
        shutil.copy(RAW_DIR / name, SNAPSHOT_DIR / "raw" / name)
    for name in PROCESSED_FILES:
        src = PROCESSED_DIR / name
        if src.exists():
            shutil.copy(src, SNAPSHOT_DIR / "processed" / name)
    if DB_PATH.exists():
        shutil.copy(DB_PATH, SNAPSHOT_DIR / "app.db")
    if verbose:
        print(f"Snapshot frozen -> {SNAPSHOT_DIR}")


def has_snapshot() -> bool:
    return (SNAPSHOT_DIR / "raw" / "accounts.csv").exists()


def reset_to_snapshot(verbose=True):
    if not has_snapshot():
        raise FileNotFoundError(f"No frozen snapshot found at {SNAPSHOT_DIR}. Run freeze_snapshot() first.")
    for name in RAW_FILES:
        shutil.copy(SNAPSHOT_DIR / "raw" / name, RAW_DIR / name)
    for name in PROCESSED_FILES:
        src = SNAPSHOT_DIR / "processed" / name
        if src.exists():
            shutil.copy(src, PROCESSED_DIR / name)
    snap_db = SNAPSHOT_DIR / "app.db"
    if snap_db.exists():
        shutil.copy(snap_db, DB_PATH)
    if verbose:
        print("Live dataset reset to the frozen snapshot.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        reset_to_snapshot()
    else:
        freeze_snapshot()
