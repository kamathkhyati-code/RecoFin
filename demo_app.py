import tempfile
import uuid
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from datagents.agents.ingestion_agent import ingest_sources
from datagents.schemas import SourceConfig, SourceType
from reasoning.agents.exception_escalation import needs_escalation, sla_hours_for_risk
from recon_platform.graph.build import build_graph
from recon_platform.reporting.report_builder import build_report_zip

BANK_FIELD_MAP = {"transaction_id": "txn_id", "value_date": "date", "ccy": "currency"}


def rows(txns):
    return [
        {
            "txn_id": t.txn_id,
            "date": t.date.isoformat(),
            "amount": str(t.amount),
            "currency": t.currency.value,
            "counterparty": t.counterparty,
            "reference": t.reference,
        }
        for t in txns
    ]


st.set_page_config(page_title="RecoFin Demo", layout="wide")

if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

_ACCENT = "#14b8a6"

_DARK_CSS = f"""
<style>
.stApp {{ background-color: #0a0a0d; color: #e5e5e5; }}
[data-testid="stSidebar"] {{ background-color: #101014; border-right: 1px solid #202027; }}
[data-testid="stSidebar"] * {{ color: #e5e5e5; }}
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small {{ color: #8a8a92 !important; }}
.stApp h1, .stApp h2, .stApp h3 {{ color: #f2f2f2; }}
[data-testid="stMetric"] {{
    background-color: #131318; border: 1px solid #24242c; border-radius: 10px;
    padding: 14px 16px;
}}
[data-testid="stMetricValue"] {{ color: {_ACCENT}; }}
[data-testid="stMetricLabel"] {{ color: #9a9aa2; }}
[data-testid="stDataFrame"] {{ color-scheme: dark; border: 1px solid #24242c; border-radius: 8px; }}
[data-testid="stFileUploader"] {{ background-color: #131318; border: 1px solid #24242c; border-radius: 8px; padding: 8px; }}
.stTabs [data-baseweb="tab"] {{ color: #9a9aa2; }}
.stTabs [aria-selected="true"] {{ color: {_ACCENT} !important; }}
hr {{ border-color: #24242c; }}
</style>
"""

_LIGHT_CSS = f"""
<style>
.stApp {{ background-color: #faf6ee; color: #2b2b28; }}
[data-testid="stSidebar"] {{ background-color: #f1ece0; border-right: 1px solid #e3ddcd; }}
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small {{ color: #8a8474 !important; }}
[data-testid="stMetric"] {{
    background-color: #ffffff; border: 1px solid #e8e2d3; border-radius: 10px;
    padding: 14px 16px;
}}
[data-testid="stMetricValue"] {{ color: #0f766e; }}
[data-testid="stMetricLabel"] {{ color: #7a7568; }}
[data-testid="stDataFrame"] {{ border: 1px solid #e8e2d3; border-radius: 8px; }}
[data-testid="stFileUploader"] {{ background-color: #ffffff; border: 1px solid #e8e2d3; border-radius: 8px; padding: 8px; }}
.stTabs [aria-selected="true"] {{ color: #0f766e !important; }}
hr {{ border-color: #e8e2d3; }}
</style>
"""

_SANS = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
_SERIF = 'Georgia, "Times New Roman", serif'

_FONT_CSS = f"""
<style>
html, body, .stApp, .stApp * {{
    font-family: {_SANS} !important;
}}
[data-testid="stDataFrame"] * {{
    font-family: {_SANS} !important;
}}
.stApp .brand-wordmark {{
    font-family: {_SERIF} !important;
}}
/* Streamlit's icons (sidebar collapse arrow, expander chevron, upload
icon) are rendered as ligature text in a Material Symbols icon font --
the blanket override above turns that ligature text into literal,
visible words ("keyboard_double_arrow_left") instead of a glyph. Exempt
icon elements so they keep their own font. */
[data-testid="stIconMaterial"] {{
    font-family: "Material Symbols Rounded" !important;
}}
</style>
"""

_BUTTON_CSS = f"""
<style>
.stButton button[kind="primary"] {{
    background-color: {_ACCENT}; border-color: {_ACCENT}; color: #04140f;
}}
.stButton button[kind="primary"]:hover {{
    background-color: #0f9c8c; border-color: #0f9c8c;
}}
.brand-wordmark {{
    font-size: 1.7rem;
    font-weight: 700;
    margin: 0;
    line-height: 1.2;
}}
[data-testid="stSidebar"] .stCaption p, [data-testid="stSidebar"] small {{
    letter-spacing: 0.06em;
}}
</style>
"""

st.markdown(_DARK_CSS if st.session_state.dark_mode else _LIGHT_CSS, unsafe_allow_html=True)
st.markdown(_FONT_CSS, unsafe_allow_html=True)
st.markdown(_BUTTON_CSS, unsafe_allow_html=True)


def _toggle_theme():
    st.session_state.dark_mode = not st.session_state.dark_mode


with st.sidebar:
    st.markdown('<p class="brand-wordmark">RecoFin</p>', unsafe_allow_html=True)
    st.caption("AGENTIC RECONCILIATION")
    st.write(
        "An agentic reconciliation system — it matches a company's books "
        "against the bank and flags what doesn't line up."
    )
    st.markdown("**Pipeline**")
    st.markdown(
        "1. **Ingest** — pull from CSV / API / SFTP\n"
        "2. **Validate** — catch bad data\n"
        "3. **Normalize** — one currency, canonical names\n"
        "4. **Match** — deterministic + memory-boosted\n"
        "5. **Classify exceptions** — risk-scored, resolution suggested"
    )
    st.divider()
    st.markdown("**Upload your data**")
    book_file = st.file_uploader("Book CSV", type=["csv"], key="book_upload")
    bank_file = st.file_uploader("Bank CSV", type=["csv"], key="bank_upload")
    with st.expander("Expected columns"):
        st.caption("Book: txn_id, date, amount, currency, counterparty, reference")
        st.caption("Bank: transaction_id, value_date, amount, ccy, counterparty, reference")
    st.divider()
    toggle_label = "Light mode" if st.session_state.dark_mode else "Dark mode"
    st.button(toggle_label, on_click=_toggle_theme, use_container_width=True)

st.markdown('<p class="brand-wordmark" style="font-size: 2.2rem;">RecoFin — Reconciliation Demo</p>', unsafe_allow_html=True)
st.write("**Ingest → Validate → Normalize → Match → Classify exceptions**, run on the real compiled graph.")

both_uploaded = book_file is not None and bank_file is not None
if not both_uploaded:
    st.info("Upload a book CSV and a bank CSV in the sidebar to run a reconciliation.")

run_clicked = st.button("Run reconciliation", type="primary", disabled=not both_uploaded)

if run_clicked and both_uploaded:
    with tempfile.TemporaryDirectory() as tmp:
        book_path = Path(tmp) / "book.csv"
        bank_path = Path(tmp) / "bank.csv"
        book_path.write_bytes(book_file.getvalue())
        bank_path.write_bytes(bank_file.getvalue())

        # Separate, lightweight ingest purely for the raw before/after
        # display below -- doesn't feed into the reconciliation itself,
        # which re-ingests the same files inside the real graph.
        raw_book = ingest_sources([
            SourceConfig(name="book", source_type=SourceType.CSV, location=str(book_path)),
        ])
        raw_bank = ingest_sources([
            SourceConfig(
                name="bank", source_type=SourceType.CSV, location=str(bank_path),
                options={"field_map": BANK_FIELD_MAP},
            ),
        ])

        with st.spinner("Running the real multi-agent pipeline (ingest, validate, normalize, match, classify)..."):
            graph = build_graph()
            run_id = f"demo-{uuid.uuid4().hex[:8]}"
            result = graph.invoke({
                "run_id": run_id,
                "period": "demo",
                "messages": [],
                "issues": [],
                "book_source_configs": [
                    SourceConfig(name="book", source_type=SourceType.CSV, location=str(book_path)),
                ],
                "bank_source_configs": [
                    SourceConfig(
                        name="bank", source_type=SourceType.CSV, location=str(bank_path),
                        options={"field_map": BANK_FIELD_MAP},
                    ),
                ],
            })

    report = result["report"]
    matches = result.get("match_results") or []
    unmatched_book = result.get("unmatched_book") or []
    unmatched_source = result.get("unmatched_source") or []
    exceptions = result.get("exceptions") or []
    findings = result.get("validation_findings") or []
    issues = result.get("issues") or []
    rejected = len([i for i in issues if i.severity == "error"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Match rate", f"{report.match_rate * 100:.0f}%")
    c2.metric("Matched", report.matched_count)
    c3.metric("Unmatched", report.unmatched_count)
    c4.metric("Exceptions", report.exception_count)
    c5.metric("Bad rows rejected", rejected)

    chart = pd.DataFrame(
        {
            "status": ["Matched", "Unmatched", "Rejected"],
            "count": [report.matched_count, report.unmatched_count, rejected],
        }
    )
    st.bar_chart(
        chart, x="status", y="count", color="status",
        use_container_width=True,
    )

    report_package = result.get("report_package")
    if report_package is not None:
        st.download_button(
            "Download audit report (.zip)",
            data=build_report_zip(report_package),
            file_name=f"recofin-report-{run_id}.zip",
            mime="application/zip",
        )

    t1, t2, t3, t4 = st.tabs(
        ["Results", "Exceptions", "Normalization (before → after)", "Raw & findings"]
    )

    with t1:
        st.subheader("Matched pairs")
        st.caption(
            "match_type shows which layer of the real matching engine caught it: "
            "exact / tolerance / fuzzy (deterministic), memory (RAG-boosted), or "
            "semantic (LLM, only when a gateway is configured)."
        )
        if matches:
            st.dataframe(
                [
                    {
                        "book_id": m.book_txn_id,
                        "bank_id": m.source_txn_id,
                        "match_type": m.match_type.value,
                        "confidence": m.confidence,
                        "rule": m.rule,
                    }
                    for m in matches
                ],
                use_container_width=True,
                column_config={
                    "confidence": st.column_config.ProgressColumn(
                        "confidence", min_value=0.0, max_value=1.0, format="%.2f"
                    ),
                },
            )
        else:
            st.info("No matches on this run.")

        st.subheader("Unmatched — book side")
        if unmatched_book:
            st.dataframe(rows(unmatched_book), use_container_width=True)
        else:
            st.success("Everything on the book side matched.")

        st.subheader("Unmatched — bank side")
        if unmatched_source:
            st.dataframe(rows(unmatched_source), use_container_width=True)
        else:
            st.success("Everything on the bank side matched.")

    with t2:
        st.subheader("Exception classification")
        st.caption(
            "Every unmatched transaction, classified and risk-scored by the "
            "real exception agent -- high-risk items are escalated to the "
            "review queue with an SLA deadline scaled by risk (24h / 72h / "
            "7 days); low-risk ones auto-resolve with no deadline."
        )
        if exceptions:
            by_type = Counter(e.exc_type.value for e in exceptions)
            st.dataframe(
                pd.DataFrame({"count": list(by_type.values())}, index=list(by_type.keys())),
                use_container_width=True,
            )
            st.dataframe(
                [
                    {
                        "txn_id": e.txn_id,
                        "side": e.side,
                        "type": e.exc_type.value,
                        "risk_score": e.risk_score,
                        "suggested_resolution": e.suggested_resolution,
                        "sla_hours": sla_hours_for_risk(e.risk_score) if needs_escalation(e) else "N/A (auto-resolved)",
                    }
                    for e in exceptions
                ],
                use_container_width=True,
                column_config={
                    "risk_score": st.column_config.ProgressColumn(
                        "risk_score", min_value=0.0, max_value=1.0, format="%.2f"
                    ),
                },
            )
        else:
            st.success("No exceptions on this run.")

    with t3:
        st.write(
            "Normalization converts everything to USD and canonical names, "
            "so the book and bank become comparable."
        )
        a, b = st.columns(2)
        with a:
            st.caption("Book — raw")
            st.dataframe(rows(raw_book.transactions), use_container_width=True)
        with b:
            st.caption("Book — normalized")
            st.dataframe(rows(result.get("book_transactions") or []), use_container_width=True)

    with t4:
        st.subheader("Validation findings")
        st.caption(
            "Four deterministic checks always run (completeness, dedupe, "
            "format, FX). Ambiguous-row LLM review is disabled in this "
            "demo (no gateway configured), so only deterministic findings "
            "appear here."
        )
        if findings:
            st.dataframe(
                [
                    {"txn_id": f.txn_id, "reason": f.reason.value, "escalate": f.escalate}
                    for f in findings
                ],
                use_container_width=True,
            )
        else:
            st.success("All clean — no validation findings.")
        st.subheader("Bank — raw ingested")
        st.dataframe(rows(raw_bank.transactions), use_container_width=True)
