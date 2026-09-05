"""Shared imports, caches, and small helpers used by every page."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import architecture_diagram, db, graph_viz, reporting  # noqa: E402
from backend.pipeline.data_io import load_data  # noqa: E402
from backend.pipeline.graph_build import build_graph  # noqa: E402

ACTION_COLOR = {"HOLD_BONUS": "red", "MANUAL_REVIEW": "orange", "NO_ACTION": "gray"}
MODE_LABEL = {"anthropic": "Primary LLM (live)", "gemini": "Fallback LLM (live)", "fallback_template": "Template fallback"}
MODE_ICON = {"anthropic": ":material/bolt:", "gemini": ":material/bolt:", "fallback_template": ":material/description:"}
ACTION_ICON = {"HOLD_BONUS": ":material/pause_circle:", "MANUAL_REVIEW": ":material/search:", "NO_ACTION": ":material/check_circle:"}
STAGE_COLOR = {"hard": "red", "soft": "violet"}
DIFFICULTY_COLOR = {"easy": "gray", "hard": "orange", "tight": "orange", "n/a": "gray"}

# audit_log's event_type is written as f"llm_investigation_{mode}" (backend/db.py),
# where mode is the raw provider key -- humanize just that one dynamic suffix for
# display, without touching the stored value or any code that filters/counts by it.
_EVENT_TYPE_SUFFIX_LABEL = {"anthropic": "primary LLM", "gemini": "fallback LLM", "fallback_template": "template"}


def humanize_event_type(event_type: str) -> str:
    for mode, label in _EVENT_TYPE_SUFFIX_LABEL.items():
        suffix = f"_{mode}"
        if event_type.endswith(suffix):
            return f"{event_type[:-len(suffix)]} ({label})"
    return event_type


@st.cache_resource(show_spinner="Building the entity graph...")
def get_graph(_version: int):
    data = load_data()
    return build_graph(data)


def ensure_version() -> int:
    if "data_version" not in st.session_state:
        st.session_state["data_version"] = 0
    return st.session_state["data_version"]


def bump_version():
    st.session_state["data_version"] = st.session_state.get("data_version", 0) + 1
    get_graph.clear()
    get_cod_graph.clear()


@st.cache_data(show_spinner=False)
def cached_all_clusters(_version: int):
    return db.get_all_clusters()


@st.cache_data(show_spinner=False)
def cached_confounder_rows(_version: int):
    return reporting.confounder_callout_rows()


@st.cache_data(show_spinner=False)
def cached_ring_rows(_version: int):
    return reporting.ring_recall_rows()


@st.cache_data(show_spinner=False)
def cached_eval_report(_version: int):
    return reporting.load_eval_report()


@st.cache_data(show_spinner=False)
def cached_calibration_report(_version: int):
    import json
    from backend.pipeline.data_io import PROCESSED_DIR
    path = PROCESSED_DIR / "confidence_calibration.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def cached_fairness_report(_version: int):
    import json
    from backend.pipeline.data_io import PROCESSED_DIR
    path = PROCESSED_DIR / "fairness_audit.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def cached_cost_sensitivity_report(_version: int):
    import json
    from backend.pipeline.data_io import PROCESSED_DIR
    path = PROCESSED_DIR / "cost_threshold_sensitivity.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def cached_compliance_data(_version: int):
    from backend.compliance_report import compute_compliance_data
    return compute_compliance_data()


@st.cache_data(show_spinner=False)
def cached_fraudar_report(_version: int):
    import json
    from backend.pipeline.data_io import PROCESSED_DIR
    path = PROCESSED_DIR / "fraudar_analysis.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def cached_scale_stress_report(_version: int):
    import json
    from backend.pipeline.data_io import PROCESSED_DIR
    path = PROCESSED_DIR / "scale_stress_test.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _cached_json(_version: int, path):
    import json
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def cached_concurrent_attack_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "concurrent_attack_stress_test.json")


@st.cache_data(show_spinner=False)
def cached_infra_resilience_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "infra_resilience_test.json")


@st.cache_data(show_spinner=False)
def cached_time_drift_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "time_drift_simulation.json")


@st.cache_data(show_spinner=False)
def cached_external_validation_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "external_validation.json")


@st.cache_data(show_spinner=False)
def cached_cod_clusters(_version: int):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    return _cached_json(_version, root / "data" / "cod" / "processed" / "clusters.json") or []


@st.cache_data(show_spinner=False)
def cached_cod_eval(_version: int):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    return _cached_json(_version, root / "data" / "cod" / "processed" / "eval_report.json")


@st.cache_resource(show_spinner="Building the COD collusion entity graph...")
def get_cod_graph(_version: int):
    from backend.cod_collusion import graph_build
    accounts, orders = graph_build.load_data()
    return graph_build.build_graph(accounts)


@st.cache_data(show_spinner=False)
def cached_cod_confounder_rows(_version: int):
    return reporting.cod_confounder_callout_rows()


@st.cache_data(show_spinner=False)
def cached_cod_ring_rows(_version: int):
    return reporting.cod_ring_recall_rows()


@st.cache_data(show_spinner=False)
def cached_cod_ground_truth(_version: int):
    return reporting.load_cod_ground_truth()


@st.cache_data(show_spinner=False)
def cached_fraudar_seed_isolation(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "fraudar_seed_isolation.json")


@st.cache_data(show_spinner=False)
def cached_supernode_stress_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "supernode_stress_test.json")


@st.cache_data(show_spinner=False)
def cached_leak_safeguard_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "no_label_leakage_test.json")


@st.cache_data(show_spinner=False)
def cached_ulb_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "ulb_validation.json")


@st.cache_data(show_spinner=False)
def cached_ieee_cis_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "ieee_cis_validation.json")


@st.cache_data(show_spinner=False)
def cached_ieee_cis_graph_report(_version: int):
    from backend.pipeline.data_io import PROCESSED_DIR
    return _cached_json(_version, PROCESSED_DIR / "ieee_cis_graph_validation.json")
