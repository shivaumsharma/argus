"""
SQLite persistence layer (BRD Section 10).

Two tables matter for the product story:
  clusters  -- every candidate cluster with its Stage 4 features, Stage 5
              verdict, and (once Day 5 runs) the LLM case writeup.
  audit_log -- every clustering decision and every LLM call, with its full
              input evidence and output, so any flag is traceable end to end
              (the RBI FREE-AI explainability/auditability expectation the
              BRD calls out).

Streamlit and FastAPI both read from this single store.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clusters (
    cluster_id TEXT PRIMARY KEY,
    detection_stage TEXT NOT NULL,
    size INTEGER NOT NULL,
    flagged INTEGER NOT NULL,
    filter_reason TEXT,
    organic_score INTEGER,
    suspicion_score INTEGER,
    members_json TEXT NOT NULL,
    features_json TEXT NOT NULL,
    llm_case_summary TEXT,
    llm_confidence REAL,
    llm_recommended_action TEXT,
    llm_key_evidence_json TEXT,
    llm_mode TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    cluster_id TEXT,
    input_evidence_json TEXT,
    output_json TEXT,
    timestamp TEXT NOT NULL
);

-- backend/adversarial_recommender/: proposals only, never auto-applied. See that
-- package's README section in ARCHITECTURE.md for the full status lifecycle:
-- pending -> (approved_pending_reeval | rejected) -> (validated_approved | rejected_after_reeval).
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round_number INTEGER NOT NULL,
    attack_id TEXT NOT NULL,
    attack_description TEXT NOT NULL,
    attack_members_json TEXT NOT NULL,
    gap_parameter TEXT NOT NULL,
    current_value TEXT NOT NULL,
    proposed_value TEXT NOT NULL,
    rationale TEXT NOT NULL,
    sim_rings_caught_before INTEGER,
    sim_rings_caught_after INTEGER,
    sim_confounder_fp_before INTEGER,
    sim_confounder_fp_after INTEGER,
    sim_report_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT,
    review_note TEXT,
    reeval_seed INTEGER,
    reeval_report_json TEXT,
    final_reviewed_by TEXT,
    final_reviewed_at TEXT,
    final_note TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def _now():
    return datetime.now(timezone.utc).isoformat()


def write_clusters(clusters: list[dict]):
    """Upsert Stage 2-5 output and log one audit_log row per clustering decision."""
    init_db()
    with get_conn() as conn:
        for c in clusters:
            conn.execute(
                """INSERT INTO clusters
                   (cluster_id, detection_stage, size, flagged, filter_reason,
                    organic_score, suspicion_score, members_json, features_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cluster_id) DO UPDATE SET
                     detection_stage=excluded.detection_stage, size=excluded.size,
                     flagged=excluded.flagged, filter_reason=excluded.filter_reason,
                     organic_score=excluded.organic_score, suspicion_score=excluded.suspicion_score,
                     members_json=excluded.members_json, features_json=excluded.features_json,
                     updated_at=excluded.updated_at""",
                (c["cluster_id"], c["detection_stage"], c["features"]["size"], int(c["flagged"]),
                 c["filter_reason"], c["organic_score"], c["suspicion_score"],
                 json.dumps(c["members"]), json.dumps(c["features"]), _now()),
            )
            conn.execute(
                """INSERT INTO audit_log (event_type, cluster_id, input_evidence_json, output_json, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                ("stage5_confounder_filter", c["cluster_id"], json.dumps(c["features"]),
                 json.dumps({"flagged": c["flagged"], "reason": c["filter_reason"],
                             "organic_score": c["organic_score"], "suspicion_score": c["suspicion_score"]}),
                 _now()),
            )


def write_llm_result(cluster_id: str, prompt_evidence: str, result: dict, mode: str):
    init_db()
    with get_conn() as conn:
        conn.execute(
            """UPDATE clusters SET llm_case_summary=?, llm_confidence=?, llm_recommended_action=?,
               llm_key_evidence_json=?, llm_mode=?, updated_at=? WHERE cluster_id=?""",
            (result["case_summary"], result["confidence"], result["recommended_action"],
             json.dumps(result["key_evidence"]), mode, _now(), cluster_id),
        )
        conn.execute(
            """INSERT INTO audit_log (event_type, cluster_id, input_evidence_json, output_json, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (f"llm_investigation_{mode}", cluster_id, json.dumps({"prompt": prompt_evidence}),
             json.dumps(result), _now()),
        )


def get_all_clusters() -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM clusters ORDER BY cluster_id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["flagged"] = bool(d["flagged"])
            d["members"] = json.loads(d.pop("members_json"))
            d["features"] = json.loads(d.pop("features_json"))
            d["llm_key_evidence"] = json.loads(d.pop("llm_key_evidence_json")) if d["llm_key_evidence_json"] else None
            out.append(d)
        return out


def get_cluster(cluster_id: str) -> dict | None:
    for c in get_all_clusters():
        if c["cluster_id"] == cluster_id:
            return c
    return None


def get_audit_log(cluster_id: str = None, limit: int = 500) -> list[dict]:
    init_db()
    with get_conn() as conn:
        if cluster_id:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE cluster_id=? ORDER BY id DESC LIMIT ?", (cluster_id, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# backend/adversarial_recommender/ -- proposals only, never auto-applied.
# Every write here also logs to audit_log (event_type "recommendation_*"),
# extending the existing audit mechanism rather than creating a parallel one.
# --------------------------------------------------------------------------

def insert_recommendation(rec: dict) -> int:
    """rec keys: round_number, attack_id, attack_description, attack_members (list),
    gap_parameter, current_value, proposed_value, rationale, sim_rings_caught_before,
    sim_rings_caught_after, sim_confounder_fp_before, sim_confounder_fp_after, sim_report (dict).
    Returns the new recommendation's id."""
    init_db()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO recommendations
               (round_number, attack_id, attack_description, attack_members_json, gap_parameter,
                current_value, proposed_value, rationale, sim_rings_caught_before, sim_rings_caught_after,
                sim_confounder_fp_before, sim_confounder_fp_after, sim_report_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (rec["round_number"], rec["attack_id"], rec["attack_description"],
             json.dumps(rec["attack_members"]), rec["gap_parameter"], str(rec["current_value"]),
             str(rec["proposed_value"]), rec["rationale"], rec["sim_rings_caught_before"],
             rec["sim_rings_caught_after"], rec["sim_confounder_fp_before"], rec["sim_confounder_fp_after"],
             json.dumps(rec["sim_report"]), _now()),
        )
        rec_id = cur.lastrowid
        conn.execute(
            """INSERT INTO audit_log (event_type, cluster_id, input_evidence_json, output_json, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            ("recommendation_proposed", f"REC{rec_id:05d}", json.dumps({"attack_id": rec["attack_id"]}),
             json.dumps({"gap_parameter": rec["gap_parameter"], "proposed_value": str(rec["proposed_value"]),
                         "rings_delta": rec["sim_rings_caught_after"] - rec["sim_rings_caught_before"],
                         "confounder_fp_delta": rec["sim_confounder_fp_after"] - rec["sim_confounder_fp_before"]}),
             _now()),
        )
        return rec_id


def get_all_recommendations() -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM recommendations ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["attack_members"] = json.loads(d.pop("attack_members_json"))
            d["sim_report"] = json.loads(d["sim_report_json"]) if d["sim_report_json"] else None
            d["reeval_report"] = json.loads(d["reeval_report_json"]) if d["reeval_report_json"] else None
            out.append(d)
        return out


def get_recommendation(rec_id: int) -> dict | None:
    for r in get_all_recommendations():
        if r["id"] == rec_id:
            return r
    return None


def review_recommendation(rec_id: int, decision: str, reviewer: str, note: str = ""):
    """First gate. decision: 'approved_pending_reeval' or 'rejected'."""
    assert decision in ("approved_pending_reeval", "rejected")
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE recommendations SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
            (decision, reviewer, _now(), note, rec_id),
        )
        conn.execute(
            """INSERT INTO audit_log (event_type, cluster_id, input_evidence_json, output_json, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            ("recommendation_reviewed", f"REC{rec_id:05d}", json.dumps({"reviewer": reviewer, "note": note}),
             json.dumps({"decision": decision}), _now()),
        )


def record_reeval(rec_id: int, seed: int, reeval_report: dict):
    """Stage 5 governance result: a fresh, never-used-seed dataset generated and evaluated
    exactly once with the proposed change applied. Moves status to pending_final_confirmation
    regardless of outcome -- a bad reeval result is still shown to the human, never hidden."""
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE recommendations SET status='pending_final_confirmation', reeval_seed=?, reeval_report_json=? "
            "WHERE id=?",
            (seed, json.dumps(reeval_report), rec_id),
        )
        conn.execute(
            """INSERT INTO audit_log (event_type, cluster_id, input_evidence_json, output_json, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            ("recommendation_reevaluated", f"REC{rec_id:05d}", json.dumps({"fresh_seed": seed}),
             json.dumps(reeval_report), _now()),
        )


def finalize_recommendation(rec_id: int, decision: str, reviewer: str, note: str = ""):
    """Second gate, after the human has seen the fresh-seed reeval numbers.
    decision: 'validated_approved' or 'rejected_after_reeval'. This is where this
    subsystem's responsibility ends -- validated_approved means the change is fully
    vetted and ready for a human developer to apply manually; nothing here writes to
    backend/pipeline/ itself, ever."""
    assert decision in ("validated_approved", "rejected_after_reeval")
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE recommendations SET status=?, final_reviewed_by=?, final_reviewed_at=?, final_note=? WHERE id=?",
            (decision, reviewer, _now(), note, rec_id),
        )
        conn.execute(
            """INSERT INTO audit_log (event_type, cluster_id, input_evidence_json, output_json, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            ("recommendation_finalized", f"REC{rec_id:05d}", json.dumps({"reviewer": reviewer, "note": note}),
             json.dumps({"decision": decision}), _now()),
        )
