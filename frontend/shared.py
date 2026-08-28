"""Shared imports, caches, and small helpers used by every page."""

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import db, graph_viz, reporting  # noqa: E402
from backend.pipeline.data_io import load_data  # noqa: E402
from backend.pipeline.graph_build import build_graph  # noqa: E402

ACTION_COLOR = {"HOLD_BONUS": "red", "MANUAL_REVIEW": "orange", "NO_ACTION": "gray"}
MODE_LABEL = {"anthropic": "Claude (live)", "gemini": "Gemini (live)", "fallback_template": "Template fallback"}
MODE_ICON = {"anthropic": ":material/bolt:", "gemini": ":material/bolt:", "fallback_template": ":material/description:"}
ACTION_ICON = {"HOLD_BONUS": ":material/pause_circle:", "MANUAL_REVIEW": ":material/search:", "NO_ACTION": ":material/check_circle:"}
STAGE_COLOR = {"hard": "red", "soft": "violet"}
DIFFICULTY_COLOR = {"easy": "gray", "hard": "orange", "tight": "orange", "n/a": "gray"}


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
