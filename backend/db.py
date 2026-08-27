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
