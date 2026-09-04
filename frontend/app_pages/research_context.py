import sys
from pathlib import Path

import streamlit as st

FRONTEND_DIR = Path(__file__).resolve().parents[1]
if str(FRONTEND_DIR) not in sys.path:
    sys.path.insert(0, str(FRONTEND_DIR))

st.title(":material/menu_book: Why this, why now")
st.caption(
    "The technical pages on this dashboard show what Argus does. This page answers a different "
    "question: is this a real research direction, is anyone else building it, has it worked anywhere "
    "real, and why does a payments company that already owns a fraud-prevention product still have a "
    "gap here? Every claim below is sourced — external links, not internal opinion."
)

st.space("large")

# ==========================================================================
# The research lineage
# ==========================================================================
st.header(":material/school: The research this builds on")
st.write(
    "Graph-based fraud detection is an active, citable research area, not a technique invented for "
    "this submission. Argus's own external validation (see External Validation) runs directly against "
    "the benchmark datasets two of these papers introduced."
)

papers = [
    ("CARE-GNN — CIKM 2020", "Dou, Liu, Sun, Deng, Peng, Yu",
     "\"Enhancing Graph Neural Network-based Fraud Detectors against Camouflaged Fraudsters.\" Introduced "
     "the YelpChi and Amazon multi-relation fraud graphs Argus is externally validated against — the "
     "same benchmark, not a look-alike.",
     "https://dl.acm.org/doi/10.1145/3340531.3411903"),
    ("PC-GNN — WWW 2021", "Liu, Ao, Qin, Chi, Feng, Yang, He",
     "\"Pick and Choose: A GNN-based Imbalanced Learning Approach for Fraud Detection.\" A second, "
     "independent model published against the same YelpChi/Amazon graphs — the field's own standard "
     "comparison point.",
     "https://dl.acm.org/doi/10.1145/3442381.3449989"),
    ("FRAUDAR — KDD 2016 (best paper)", "Hooi, Shah, Hooi, Beutel, Günnemann, Akoglu, Kumar, Basu, Faloutsos",
     "The densest-subgraph, camouflage-resistant detection algorithm Argus runs as its own independent "
     "cross-check (see External Validation) — a published method, not our own code marking its own work.",
     "https://bhooi.github.io/papers/fraudar_kdd16.pdf"),
    ("PromoGuardian — arXiv 2025 / IEEE S&P 2026", "(Meituan + academic co-authors)",
     "\"Detecting Promotion Abuse Fraud with Multi-Relation Fused Graph Neural Networks.\" The closest "
     "published match to Argus's actual problem — promo-abuse ring detection via a multi-relation graph "
     "— deployed and evaluated on Meituan's real platform.",
     "https://arxiv.org/abs/2510.12652"),
    ("FLAG — KDD 2025", "(fraud detection research track)",
     "\"Fraud Detection with LLM-enhanced Graph Neural Network.\" Independent confirmation that pairing "
     "graph-based detection with an LLM layer — Argus's own Stage 8 — is where current research is "
     "heading, not a novelty invented here.",
     "https://arxiv.org/abs/2601.06800"),
]
for title, authors, desc, url in papers:
    with st.container(border=True):
        st.markdown(f"**{title}** — *{authors}*")
        st.write(desc)
        st.markdown(f"[Read the paper]({url})")

st.caption(
    "A broader, continuously-updated survey of this literature: "
    "[safe-graph/graph-fraud-detection-papers](https://github.com/safe-graph/graph-fraud-detection-papers) "
    "— a curated academic reading list maintained independently of this project."
)

st.space("large")

# ==========================================================================
# Who else is building this
# ==========================================================================
st.header(":material/domain: Who else is building this, commercially")
st.write(
    "This isn't a hypothetical market. Real, funded companies sell graph/network-based fraud detection "
    "today, and at least two publish promo/referral abuse as a named use case."
)

companies = [
    ("Feedzai", "RiskOps platform for large banks and payment processors; ships graph-based investigation "
                "tools that visualize account/device/behavior relationships to surface organized, "
                "multi-account fraud specifically."),
    ("DataVisor", "Unsupervised ML (UML) plus graph/device intelligence built to catch coordinated attacks "
                  "with zero prior examples — the same \"rings look normal one at a time\" problem Argus "
                  "targets, at production scale."),
    ("Forter", "Network intelligence combined with risk scoring, explicitly marketed for fraud patterns "
               "that only reveal themselves through relationships between accounts, not single transactions."),
    ("Sardine", "Publishes promo-abuse detection as a named product line — their own framing, \"a strategic "
               "infrastructure shift,\" for the exact loss type this project's primary demo targets."),
    ("SHIELD", "Sells referral- and promo-abuse detection as a dedicated use case, aimed at the same "
              "device/account-linkage signals Argus's Stage 1 graph is built from."),
    ("Featurespace", "ARIC Risk Hub — adaptive behavioral analytics modeling what \"normal\" looks like per "
                     "customer, the same organic-evidence philosophy behind Argus's Stage 5 confounder filter."),
]
cols = st.columns(2)
for i, (name, desc) in enumerate(companies):
    with cols[i % 2]:
        with st.container(border=True):
            st.markdown(f"**{name}**")
            st.caption(desc)

st.space("large")

# ==========================================================================
# What's actually been achieved
# ==========================================================================
st.header(":material/monitoring: What's actually been achieved, in the real world")
st.write("Three real, cited outcomes — not projections:")

with st.container(border=True):
    st.markdown("**PromoGuardian on Meituan's real platform**")
    st.write(
        "65,006 labeled fraudsters and 20,979 previously-unlabeled fraudsters detected via multi-relation "
        "graph modeling, against 8,431 false positives — published results, not a vendor claim."
    )
    st.markdown("[Source: arXiv 2510.12652](https://arxiv.org/abs/2510.12652)")

with st.container(border=True):
    st.markdown("**A global crypto exchange, referral/sign-up bonus abuse**")
    st.write(
        "Investigation found synthetic identities and duplicate-account networks exploiting sign-up and "
        "referral incentives; tightening device checks and eligibility rules recovered an estimated "
        "$300,000 in prevented losses — the same abuse pattern, same fix category (device/account "
        "linkage), as Argus's primary demo."
    )
    st.markdown("[Source: Sardine — Promo Abuse Detection](https://www.sardine.ai/blog/promo-abuse)")

with st.container(border=True):
    st.markdown("**Razorpay's own Thirdwatch (Mitra), for context**")
    st.write(
        "Razorpay acquired Thirdwatch in 2019; its Mitra platform scores roughly 200 parameters per "
        "transaction to generate a real-time trust score, and is credited with an 80% reduction in "
        "e-commerce fraud losses for merchants using it. Real, working, and — as the next section covers "
        "— solving a structurally different problem than the one this project targets."
    )
    st.markdown("[Source: Razorpay Blog — Thirdwatch acquisition](https://razorpay.com/blog/thirdwatch-acquisition-rto-fraud-ecommerce/)")

st.space("large")

# ==========================================================================
# The gap at Razorpay, specifically
# ==========================================================================
st.header(":material/search: The gap this fills — stated precisely, not as a knock on what exists")
with st.container(border=True):
    st.write(
        "Razorpay is not starting from zero on fraud. Thirdwatch's Mitra engine already does real-time, "
        "per-transaction risk scoring, and its published results are genuinely strong. That's the honest "
        "starting point — not a claim that Razorpay's fraud stack is weak."
    )
    st.write(
        "But per-transaction scoring is architecturally a *row-level* method: it asks \"is this one "
        "transaction risky,\" account by account, order by order. A promo/referral farming ring is built "
        "specifically to defeat exactly that question — every individual account in the ring is designed "
        "to look ordinary on its own. The fraud only exists in the **relationship** between accounts: the "
        "same device behind thirteen signups, a referral bonus claimed in hours instead of weeks. No "
        "amount of tuning a per-row score reaches that signal, because the signal was never in any single "
        "row to begin with."
    )
    st.write(
        "That's not a hypothetical gap. This exact problem — coordinated, multi-account promo/referral "
        "abuse — is the one Razorpay's own AI Buildathon Track 02 asked teams to solve from scratch, "
        "rather than pointing to an existing internal system. The clearest evidence the gap is real is "
        "that the brief exists at all."
    )

st.space("large")

# ==========================================================================
# Why now — the regulatory case
# ==========================================================================
st.header(":material/gavel: Why now — the regulatory case, not just the technical one")
with st.container(border=True):
    st.write(
        "The RBI's FREE-AI framework (Fairness, Reliability, Explainability, Ethics — submitted August "
        "2025) named fraud detection explicitly as a **high-risk AI system** requiring enhanced "
        "governance and audit trails. 2026 is the year Indian financial institutions move from reading "
        "that framework to being held to it — implementation and audit, not discussion."
    )
    st.write(
        "That timing favors an architecture like Argus's over a typical black-box classifier by "
        "construction: every flag here already traces back to a specific graph edge, a specific feature "
        "score, and a specific deterministic rule — logged in a queryable audit trail (see Compliance and "
        "Audit log) — not because the RBI framework was retrofitted onto the design, but because "
        "explainability was the starting requirement, before the framework's own implementation deadline "
        "arrived."
    )
    st.markdown(
        "[Source: RBI FREE-AI framework, implementation status 2026](https://rmaindia.org/rbis-free-ai-framework-2026-7-sutras-and-practical-implementation-roadmap/)"
    )

st.space("large")
st.caption(
    "Everything on this page links to an external, independently-published source. If you're fact-checking "
    "before the pitch, this is the page to verify first."
)
