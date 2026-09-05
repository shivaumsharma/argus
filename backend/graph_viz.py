"""
Renders a single cluster's subgraph as an interactive pyvis network -- nodes
are the accounts, edges are labeled with the shared attribute that produced
them (BRD Section 11 UI requirement). Used by the Streamlit dashboard.
"""

from pathlib import Path

from pyvis.network import Network

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "processed" / "graph_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SIGNAL_COLOR = {
    "shared_instrument": "#8e44ad",
    "shared_device": "#e74c3c",
    "ip_subnet_overlap": "#e67e22",
    "referral_link": "#3498db",
    # COD collusion loss type (backend/cod_collusion/graph_build.py) -- same
    # hard/soft color roles (purple = hard, orange = soft), reused rather than
    # invented, since the two loss types are never shown side by side.
    "shared_address": "#8e44ad",
    "phone_prefix": "#e67e22",
}
SIGNAL_PRIORITY = ["shared_instrument", "shared_device", "ip_subnet_overlap", "referral_link",
                   "shared_address", "phone_prefix"]
# Same hard/soft split as backend/pipeline/graph_build.py's HARD_SIGNALS -- duplicated rather than
# imported to keep this module decoupled from the pipeline package. Used to make edge *width* carry
# the hard/soft distinction as strongly as edge color does: a near-certain shared-instrument/device
# signal should look unmistakably bolder than an IP-subnet-only overlap, not just a slightly
# different shade -- the two illustrative Overview graphs looked "the same shape" before this because
# both signal types rendered as similarly thin lines once buried under a same-size, same-color node.
HARD_SIGNALS_FOR_WIDTH = {"shared_instrument", "shared_device", "shared_address"}
SIGNAL_LABEL = {
    "shared_instrument": "shared instrument",
    "shared_device": "shared device",
    "ip_subnet_overlap": "IP subnet overlap",
    "referral_link": "referral link",
    "shared_address": "shared delivery address",
    "phone_prefix": "shared phone-number prefix",
}


def _edge_color(signals: set) -> str:
    for s in SIGNAL_PRIORITY:
        if s in signals:
            return SIGNAL_COLOR[s]
    return "#95a5a6"


def render_cluster_graph(G, members, node_color="#c0392b", cache_key=None, height: int = 520,
                          show_edge_labels: bool = True) -> Path:
    """Build and cache an interactive HTML visualization of the subgraph induced by `members`.

    `height` must match the caller's own st.iframe(..., height=height) exactly. pyvis/vis-network
    sizes and centers its canvas at construction time using THIS height, not the iframe it ends up
    embedded in -- passing a mismatched height here is why a graph can render with the node cluster
    pushed toward the bottom and a dead blank band at the top of the visible iframe: the canvas was
    built taller (or shorter) than the window actually showing it, and fit()/centering happened
    against the wrong box. Every call site must pass its real display height, not rely on the default.

    `show_edge_labels=False` drops the always-on edge text (still available on hover via `title`) --
    on a dense, near-complete cluster the labels stack and overlap into unreadable clutter that
    competes with edge color for attention, which is the one signal these illustrative renders most
    need to read clearly at a glance. Graph Explorer keeps labels on (default True) since there a
    user is inspecting one edge at a time, not scanning two clusters side by side."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    members = list(members)
    sub = G.subgraph(members)

    # cdn_resources="in_line" embeds the vis-network JS/CSS directly in the HTML file --
    # "local" is misleadingly named and still fetches vis-network from cdnjs.cloudflare.com,
    # which fails in network-sandboxed environments and leaves the canvas undrawn.
    net = Network(height=f"{height}px", width="100%", bgcolor="#111318", font_color="#e8e8e8", cdn_resources="in_line")
    net.barnes_hut(gravity=-4000, spring_length=140, spring_strength=0.02, damping=0.25)

    for uid in members:
        degree = sub.degree(uid) if uid in sub else 0
        size = 14 + min(degree, 10) * 2
        net.add_node(uid, label=uid, color=node_color, size=size, title=f"{uid} -- {degree} connection(s) in this cluster")

    for u, v, d in sub.edges(data=True):
        signals = d.get("signals", set())
        label = " + ".join(SIGNAL_LABEL.get(s, s) for s in signals)
        width = 6 if signals & HARD_SIGNALS_FOR_WIDTH else 2
        net.add_edge(u, v, label=(label if show_edge_labels else ""), color=_edge_color(signals),
                     width=width, title=f"{label} (weight {d.get('weight', 1.0):.1f})")

    net.set_options("""
    {
      "edges": {"font": {"size": 10, "color": "#cccccc", "strokeWidth": 0}, "smooth": {"type": "continuous"}},
      "nodes": {"font": {"size": 13, "color": "#e8e8e8"}},
      "interaction": {"hover": true, "tooltipDelay": 100}
    }
    """)

    key = cache_key or "_".join(sorted(members))[:80]
    out_path = CACHE_DIR / f"{key}.html"
    # net.write_html() opens the file with the OS locale encoding (cp1252 on Windows),
    # which chokes on the inlined vis-network bundle. generate_html() returns a plain
    # string, so we control the encoding by writing it ourselves.
    html = net.generate_html(notebook=False)
    html = html.replace("</body>", _RESIZE_FIX + "</body>")
    out_path.write_text(html, encoding="utf-8")
    return out_path


# vis-network sizes its canvas once, at construction time, using the container's
# current dimensions. Streamlit renders every tab/expander's content into the DOM
# regardless of which one is visible, so a graph embedded in a collapsed expander
# or an inactive tab initializes against a 0x0 container and its canvas never
# recovers even after the panel is shown. A ResizeObserver (plus a short polling
# fallback for browsers/timings it misses) forces a redraw once real size exists.
_RESIZE_FIX = """
<script>
(function() {
  var el = document.getElementById('mynetwork');
  if (!el) return;
  function kick() {
    if (window.network && typeof window.network.redraw === 'function' && el.clientWidth > 0) {
      window.network.setSize(el.clientWidth + 'px', el.clientHeight + 'px');
      window.network.redraw();
      window.network.fit();
    }
  }
  if (window.ResizeObserver) { new ResizeObserver(kick).observe(el); }
  var tries = 0;
  var iv = setInterval(function() { kick(); if (++tries > 20) clearInterval(iv); }, 150);
})();
</script>
"""
