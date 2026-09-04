"""
FastAPI backend (BRD Section 10). Exposes the same SQLite store the Streamlit
dashboard reads, as a documented service boundary for programmatic access --
e.g. a merchant's own risk console pulling flagged clusters into its own UI.

The dashboard itself reads the store directly rather than through this API,
for demo reliability (one process to keep alive instead of two); this API is
the architecture's intended integration surface, not a hard dependency of the
Streamlit app. Run with: uvicorn backend.api:app --reload

No endpoint here can ban, block, or move money -- POST /pipeline/run and
POST /pipeline/investigate only ever re-run the deterministic clustering and
the bounded LLM narrative layer, both of which output recommendations for a
human to act on, never an executed action.
"""

from fastapi import FastAPI, HTTPException

from . import db, reporting
from .llm_investigate import investigate_all
from .pipeline.run_pipeline import run as run_pipeline

app = FastAPI(
    title="Argus API",
    description="Read-only views over the graph-clustering fraud-ring detector. "
                 "Every recommendation is bounded to HOLD_BONUS / MANUAL_REVIEW / NO_ACTION.",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/clusters")
def list_clusters(flagged: bool = None):
    clusters = db.get_all_clusters()
    if flagged is not None:
        clusters = [c for c in clusters if c["flagged"] == flagged]
    return clusters


@app.get("/clusters/{cluster_id}")
def get_cluster(cluster_id: str):
    cluster = db.get_cluster(cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
    return cluster


@app.get("/confounders")
def confounders():
    """Ground-truth legitimate clusters and whether the detector correctly left them alone."""
    return reporting.confounder_callout_rows()


@app.get("/rings")
def rings():
    """Ground-truth planted rings and whether the detector recovered them."""
    return reporting.ring_recall_rows()


@app.get("/metrics")
def metrics():
    report = reporting.load_eval_report()
    if report is None:
        raise HTTPException(status_code=404, detail="No eval report yet -- run POST /pipeline/run then the eval harness.")
    return report


@app.get("/audit-log")
def audit_log(cluster_id: str = None, limit: int = 200):
    return db.get_audit_log(cluster_id=cluster_id, limit=limit)


@app.post("/pipeline/run")
def trigger_pipeline():
    """Re-runs Stages 1-5 (graph, clustering, feature scoring, confounder filter)."""
    results = run_pipeline(verbose=False)
    return {"candidate_clusters": len(results), "flagged": sum(1 for r in results if r["flagged"])}


@app.post("/pipeline/investigate")
def trigger_investigation():
    """Re-runs the Day 5 LLM narrative layer over currently-flagged clusters."""
    results = investigate_all(verbose=False)
    n_llm = sum(1 for r in results if r["mode"] == "llm")
    return {"investigated": len(results), "via_llm": n_llm, "via_template_fallback": len(results) - n_llm}
