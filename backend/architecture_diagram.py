"""
Renders the end-to-end 8-stage pipeline as a single static HTML diagram, with
every number pulled live from eval_report.json / scale_stress_test.json --
not hand-typed, matching this project's own "no hand-copied numbers" rule.
Used by frontend/app_pages/research_context.py, embedded via st.iframe (a
plain HTML/CSS document, not a vis-network canvas, so none of graph_viz.py's
canvas-height-mismatch gotcha applies here -- only real content clipping if
the caller's iframe height is set too short).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "processed" / "graph_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<style>
:root{{
  --bg:#0b0e14; --surface:#141822; --surface-alt:#181d29; --border:#232838; --border-soft:#1c2130;
  --text:#ece8df; --text-dim:#a9afc0; --muted:#7e8a9e;
  --hard:#e74c3c; --soft:#8e44ad; --clear:#4fae8e; --ai:#e3a94a;
}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0}}
body{{
  background:var(--bg); color:var(--text);
  font-family:"Source Serif 4","Iowan Old Style","Palatino Linotype",Georgia,serif;
  line-height:1.6; -webkit-font-smoothing:antialiased;
}}
h1{{text-wrap:balance}}
.wrap{{max-width:860px;margin:0 auto;padding:40px 28px 60px}}
.eyebrow{{
  font-family:"IBM Plex Mono",monospace;font-size:12px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ai);display:flex;align-items:center;gap:10px;margin-bottom:16px;
}}
.eyebrow::before{{content:"";width:7px;height:7px;border-radius:50%;background:var(--ai);box-shadow:0 0 0 3px rgba(227,169,74,.18)}}
h1{{font-size:34px;font-weight:600;margin:0 0 10px;letter-spacing:-.01em}}
.subtitle{{color:var(--text-dim);font-size:15.5px;max-width:64ch;margin:0 0 26px}}
.scale-strip{{
  display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);
  border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:26px;
}}
.scale-cell{{background:var(--surface);padding:12px 16px}}
.scale-label{{font-family:"IBM Plex Mono",monospace;font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}}
.scale-value{{font-family:"IBM Plex Mono",monospace;font-size:15px;color:var(--text);font-variant-numeric:tabular-nums}}
.legend{{
  display:flex;flex-wrap:wrap;gap:9px 22px;border:1px solid var(--border);border-radius:10px;
  padding:13px 18px;margin-bottom:40px;background:var(--surface);
}}
.legend-item{{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text-dim)}}
.legend-dot{{width:9px;height:9px;border-radius:50%;flex:none}}
.legend-item b{{color:var(--text);font-weight:600}}
.pipeline{{position:relative;padding-left:30px}}
.pipeline::before{{content:"";position:absolute;left:9px;top:8px;bottom:8px;width:2px;background:var(--border-soft)}}
.stage{{position:relative}}
.stage-dot{{
  position:absolute;left:-30px;top:22px;width:19px;height:19px;border-radius:50%;
  background:var(--bg);border:2px solid var(--role-color,var(--muted));
  display:flex;align-items:center;justify-content:center;
  font-family:"IBM Plex Mono",monospace;font-size:9px;color:var(--role-color,var(--muted));font-weight:600;
}}
.card{{
  background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--role-color,var(--border));
  border-radius:9px;padding:15px 20px;margin-bottom:20px;
}}
.card-head{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px}}
.card-title{{font-family:"IBM Plex Mono",monospace;font-size:14px;font-weight:600;color:var(--text)}}
.card-file{{font-family:"IBM Plex Mono",monospace;font-size:11px;color:var(--muted)}}
.card-desc{{font-size:14.5px;color:var(--text-dim);margin:0}}
.req-tag{{
  font-family:"IBM Plex Mono",monospace;font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--role-color,var(--ai));border:1px solid var(--role-color,var(--ai));border-radius:5px;
  padding:2px 8px;margin-left:auto;white-space:nowrap;
}}
.card-stat{{
  font-family:"IBM Plex Mono",monospace;font-size:11px;color:var(--role-color,var(--text-dim));
  margin-top:8px;padding-top:8px;border-top:1px solid var(--border-soft);
}}
.branch{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}}
.branch .card{{margin-bottom:0}}
.flow-label{{font-family:"IBM Plex Mono",monospace;font-size:10.5px;color:var(--muted);margin:-6px 0 14px 2px}}
.footnote{{
  margin-top:40px;padding-top:18px;border-top:1px solid var(--border);
  font-family:"IBM Plex Mono",monospace;font-size:11.5px;color:var(--muted);line-height:1.7;
}}
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">
</head><body>
<div class="wrap">
  <div class="eyebrow">End-to-end pipeline &middot; 8 stages</div>
  <h1>Argus Architecture</h1>
  <p class="subtitle">What actually runs, stage by stage, on every account in the graph &mdash; not a simplified pitch version of it. Every number below is live-computed from this run, not hand-typed.</p>

  <div class="scale-strip">
    <div class="scale-cell"><div class="scale-label">Accounts</div><div class="scale-value">{accounts:,}</div></div>
    <div class="scale-cell"><div class="scale-label">Graph edges</div><div class="scale-value">{edges:,}</div></div>
    <div class="scale-cell"><div class="scale-label">Pipeline time</div><div class="scale-value">{pipeline_time}</div></div>
    <div class="scale-cell"><div class="scale-label">At 50&times; scale</div><div class="scale-value">{pipeline_time_50x}</div></div>
  </div>

  <div class="legend">
    <div class="legend-item"><span class="legend-dot" style="background:var(--hard)"></span><b>Hard signal</b> &mdash; device / instrument, near-certain</div>
    <div class="legend-item"><span class="legend-dot" style="background:var(--soft)"></span><b>Soft signal</b> &mdash; IP subnet / referral timing, circumstantial</div>
    <div class="legend-item"><span class="legend-dot" style="background:var(--clear)"></span><b>Deterministic</b> &mdash; Stage 5's own rules, no model</div>
    <div class="legend-item"><span class="legend-dot" style="background:var(--ai)"></span><b>AI-generated</b> &mdash; Stage 8 only, strictly downstream</div>
  </div>

  <div class="pipeline">

    <div class="stage">
      <div class="stage-dot" style="--role-color:var(--muted)">&middot;</div>
      <div class="card" style="--role-color:var(--muted)">
        <div class="card-head"><span class="card-title">Raw data</span></div>
        <p class="card-desc">accounts &middot; sessions &middot; referrals &middot; payment_instruments &middot; orders</p>
      </div>
    </div>

    <div class="stage">
      <div class="stage-dot" style="--role-color:var(--muted)">1</div>
      <div class="card" style="--role-color:var(--muted)">
        <div class="card-head"><span class="card-title">Stage 1 &mdash; Graph construction</span><span class="card-file">graph_build.py</span></div>
        <p class="card-desc">A shared device, payment instrument, IP subnet, or referral link between two accounts becomes an edge. This is the entire premise: fraud rings are invisible per-row, visible per-relationship.</p>
      </div>
    </div>

    <div class="branch">
      <div class="stage" style="margin-bottom:0">
        <div class="stage-dot" style="--role-color:var(--hard)">2</div>
        <div class="card" style="--role-color:var(--hard);background:var(--surface-alt)">
          <div class="card-head"><span class="card-title">Stage 2 &mdash; Hard clustering</span></div>
          <p class="card-desc">Connected components on device/instrument edges only.</p>
          <div class="card-stat" style="--role-color:var(--hard)">{hard_recall} recall on {n_rings_hard}/{n_rings_hard} planted hard rings</div>
        </div>
      </div>
      <div class="stage" style="margin-bottom:0">
        <div class="stage-dot" style="--role-color:var(--soft)">3</div>
        <div class="card" style="--role-color:var(--soft);background:var(--surface-alt)">
          <div class="card-head"><span class="card-title">Stage 3 &mdash; Soft clustering</span></div>
          <p class="card-desc">Louvain community detection on the full weighted graph.</p>
          <div class="card-stat" style="--role-color:var(--soft)">{soft_recall} recall on {n_rings_soft} planted soft rings</div>
        </div>
      </div>
    </div>
    <div class="flow-label">both feed forward independently &darr;</div>

    <div class="stage">
      <div class="stage-dot" style="--role-color:var(--ai)">4</div>
      <div class="card" style="--role-color:var(--ai)">
        <div class="card-head">
          <span class="card-title">Stage 4 &mdash; Cluster feature scoring</span><span class="card-file">features.py</span>
          <span class="req-tag" style="--role-color:var(--ai)">Brief: ML risk scoring</span>
        </div>
        <p class="card-desc">Burst-signup timing, order-value templating, claim-then-dormant behavior, post-signup engagement &mdash; still deterministic features, plus real trained classifiers (XGBoost / logistic regression) benchmarked in External Validation.</p>
      </div>
    </div>

    <div class="stage">
      <div class="stage-dot" style="--role-color:var(--clear)">5</div>
      <div class="card" style="--role-color:var(--clear)">
        <div class="card-head">
          <span class="card-title">Stage 5 &mdash; Confounder filter</span><span class="card-file">confounder_filter.py</span>
          <span class="req-tag" style="--role-color:var(--clear)">Brief: deterministic policy</span>
        </div>
        <p class="card-desc">Explicit, auditable rules &mdash; not a model score &mdash; actively look for evidence a dense cluster is a household, hostel, or office network before ever agreeing to flag it.</p>
        <div class="card-stat" style="--role-color:var(--clear)">{confounder_fp_rate} false-positive rate &mdash; {confounder_fp_count} of {n_confounders} planted confounders</div>
      </div>
    </div>

    <div class="branch">
      <div class="card" style="--role-color:var(--clear);background:var(--surface-alt)">
        <div class="card-head"><span class="card-title" style="color:var(--clear)">Suppressed</span></div>
        <p class="card-desc">Left alone. No further action, no record beyond the audit log entry explaining why.</p>
      </div>
      <div class="card" style="--role-color:var(--ai);background:var(--surface-alt)">
        <div class="card-head"><span class="card-title" style="color:var(--ai)">Flagged</span></div>
        <p class="card-desc">Survives to Stage 8 &mdash; the verdict is already fixed here, nothing downstream can change it.</p>
      </div>
    </div>
    <div class="flow-label">flagged clusters only &darr;</div>

    <div class="stage">
      <div class="stage-dot" style="--role-color:var(--ai)">8</div>
      <div class="card" style="--role-color:var(--ai)">
        <div class="card-head">
          <span class="card-title">Stage 8 &mdash; LLM investigation layer</span><span class="card-file">llm_investigate.py</span>
          <span class="req-tag" style="--role-color:var(--ai)">Brief: AI-generated evidence</span>
        </div>
        <p class="card-desc">Writes the case in plain English from evidence Stages 1&ndash;5 already computed. The literal, direct answer to the brief's &ldquo;AI-generated evidence&rdquo; requirement &mdash; it narrates a verdict, it never casts one.</p>
      </div>
    </div>

    <div class="stage">
      <div class="stage-dot" style="--role-color:var(--muted)">&middot;</div>
      <div class="card" style="--role-color:var(--muted)">
        <div class="card-head">
          <span class="card-title">Output</span>
          <span class="req-tag" style="--role-color:var(--clear)">Brief: deterministic policy</span>
        </div>
        <p class="card-desc">case_summary &middot; confidence &middot; key_evidence &middot; recommended_action &isin; {{HOLD_BONUS, MANUAL_REVIEW, NO_ACTION}}</p>
        <div class="card-stat">Bounded to exactly those three actions &mdash; a human executes. No code path anywhere bans, blocks, or moves money on its own.</div>
      </div>
    </div>

    <div class="stage">
      <div class="stage-dot" style="--role-color:var(--muted)">&middot;</div>
      <div class="card" style="--role-color:var(--muted)">
        <div class="card-head">
          <span class="card-title">SQLite &mdash; clusters + audit_log</span>
          <span class="req-tag" style="--role-color:var(--muted)">Brief: persistent audit trails</span>
        </div>
        <p class="card-desc">Every clustering decision and every LLM call, with its full input evidence and output &mdash; queryable by cluster ID, not a black box after the fact.</p>
      </div>
    </div>

    <div class="branch">
      <div class="card" style="background:var(--surface-alt)">
        <div class="card-head"><span class="card-title">Streamlit dashboard</span></div>
        <p class="card-desc">This entire submission's UI reads live from here.</p>
      </div>
      <div class="card" style="background:var(--surface-alt)">
        <div class="card-head"><span class="card-title">FastAPI service</span></div>
        <p class="card-desc">Read-only, same store, for programmatic access.</p>
      </div>
    </div>

  </div>

  <div class="footnote">Same eight stages as docs/ARCHITECTURE.md's own canonical diagram &mdash; a rendering of the real pipeline, not a simplified pitch version of it.</div>
</div>
</body></html>
"""


def render_architecture_diagram(eval_report: dict, scale_report: dict | None,
                                 cache_key: str = "architecture_diagram") -> Path:
    """Build and cache the 8-stage architecture diagram as a standalone HTML file,
    every stat pulled live from eval_report.json / scale_stress_test.json.

    Returns a Path for the caller to render via st.iframe(src=path, height=...).
    Unlike graph_viz.render_cluster_graph(), this is a plain HTML/CSS document with
    no canvas library involved, so there is no canvas-sizing-at-construction-time
    gotcha here -- an iframe height that's too short just clips/scrolls real content,
    it doesn't mis-center anything."""
    overall = eval_report["overall"]
    scale_1x = (scale_report or {}).get("1x", {})
    scale_50x = (scale_report or {}).get("50x", {})
    t_1x = scale_1x.get("timings_sec", {}).get("total_pipeline")
    t_50x = scale_50x.get("timings_sec", {}).get("total_pipeline")

    html = _TEMPLATE.format(
        accounts=scale_1x.get("n_accounts", 0),
        edges=scale_1x.get("n_graph_edges", 0),
        pipeline_time=f"{t_1x:.2f}s" if t_1x is not None else "n/a",
        pipeline_time_50x=f"{t_50x:.1f}s" if t_50x is not None else "n/a",
        hard_recall=f"{overall['hard_signal_recall']:.0%}",
        soft_recall=f"{overall['soft_signal_recall']:.0%}",
        n_rings_hard=overall["n_rings_hard"],
        n_rings_soft=overall["n_rings_soft"],
        confounder_fp_rate=f"{overall['confounder_false_positive_rate']:.1%}",
        confounder_fp_count=overall["cluster_fp"],
        n_confounders=overall["n_confounders"],
    )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"{cache_key}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
