import os
import tempfile
import uuid
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from datagents.agents.ingestion_agent import ingest_sources
from datagents.schemas import SourceConfig, SourceType
from reasoning.agents.exception_escalation import needs_escalation, sla_hours_for_risk
from recon_platform.auth.db import is_ephemeral, make_engine
from recon_platform.auth.service import AuthError, authenticate, register_user
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


@st.cache_resource
def _build_gateway():
    """Construct a real Groq gateway if GROQ_API_KEY is set in this
    deployment's secrets (share.streamlit.io -> app -> Settings ->
    Secrets); returns None (deterministic-only, the prior default
    behavior) if it's absent, or if construction fails for any reason
    (bad/expired key) -- a broken key degrades gracefully to the
    always-tested no-gateway path instead of crashing the whole demo.
    Cached so this only runs once per server process, not once per
    script rerun.
    """
    try:
        api_key = st.secrets.get("GROQ_API_KEY")
    except Exception:
        api_key = None
    if not api_key:
        return None
    try:
        os.environ.setdefault("GROQ_API_KEY", api_key)
        from recon_platform.gateway.llm_gateway import GroqLLMGateway

        return GroqLLMGateway()
    except Exception:
        return None


def _resolve_database_url() -> str | None:
    """Same optional-secret pattern as _build_gateway: DATABASE_URL is
    the user's own external Postgres (Supabase/Neon/etc, provisioned by
    them, not something this app can set up on its own). Absent -> the
    local SQLite fallback in recon_platform.auth.db, which works but is
    wiped on every redeploy on Streamlit Community Cloud."""
    try:
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


@st.cache_resource
def _get_auth_engine():
    """Cached like _build_gateway's client -- without @st.cache_resource
    this would reopen a connection on every single script rerun (every
    button click, every form submit anywhere in the app)."""
    return make_engine(_resolve_database_url())


st.set_page_config(page_title="RecoFin Demo", layout="wide")

gateway = _build_gateway()
auth_engine = _get_auth_engine()
registration_disabled = is_ephemeral(_resolve_database_url())

st.session_state.setdefault("user", None)

_ACCENT = "#14b8a6"
_ACCENT_BRIGHT = "#2dd4bf"

# Dark-only by design (see .streamlit/config.toml's [theme] base="dark") --
# light mode was unreadable and this gets presented live, so there's no
# toggle to accidentally switch away from it mid-demo.
_DARK_CSS = f"""
<style>
.stApp {{
    background: radial-gradient(ellipse 1200px 800px at 50% -10%, #10151a 0%, #0a0a0d 55%);
    color: #e5e5e5;
}}
[data-testid="stSidebar"] {{ background-color: #0d0d11; border-right: 1px solid #1f1f26; }}
[data-testid="stSidebar"] * {{ color: #e5e5e5; }}
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] small {{ color: #8a8a92 !important; }}
.stApp h1, .stApp h2, .stApp h3 {{ color: #f2f2f2; }}
[data-testid="stMetric"] {{
    background-color: #131318; border: 1px solid #24242c; border-top: 2px solid {_ACCENT};
    border-radius: 10px; padding: 14px 16px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.35);
    transition: border-color 0.15s ease, transform 0.15s ease;
}}
[data-testid="stMetric"]:hover {{ border-color: {_ACCENT_BRIGHT}; transform: translateY(-1px); }}
[data-testid="stMetricValue"] {{ color: {_ACCENT_BRIGHT}; }}
[data-testid="stMetricLabel"] {{ color: #9a9aa2; }}
[data-testid="stDataFrame"] {{ color-scheme: dark; border: 1px solid #24242c; border-radius: 8px; }}
[data-testid="stFileUploader"] {{
    background-color: #131318; border: 1px solid #24242c; border-radius: 8px; padding: 8px;
    transition: border-color 0.15s ease;
}}
[data-testid="stFileUploader"]:hover {{ border-color: #34343e; }}
.stTabs [data-baseweb="tab"] {{ color: #9a9aa2; }}
.stTabs [aria-selected="true"] {{ color: {_ACCENT_BRIGHT} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {_ACCENT} !important; }}
hr {{ border-color: #24242c; }}
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
.stButton button[kind="primary"], [data-testid^="stBaseButton-primary"] {{
    background-color: {_ACCENT}; border-color: {_ACCENT}; color: #04140f;
    font-weight: 600;
    box-shadow: 0 2px 12px rgba(20, 184, 166, 0.25);
    transition: box-shadow 0.15s ease, transform 0.15s ease;
}}
.stButton button[kind="primary"]:hover, [data-testid^="stBaseButton-primary"]:hover {{
    background-color: {_ACCENT_BRIGHT}; border-color: {_ACCENT_BRIGHT};
    box-shadow: 0 4px 20px rgba(45, 212, 191, 0.4);
    transform: translateY(-1px);
}}
.stDownloadButton button {{
    border-color: #2c2c34; transition: border-color 0.15s ease;
}}
.stDownloadButton button:hover {{ border-color: {_ACCENT}; color: {_ACCENT_BRIGHT}; }}
.brand-wordmark {{
    font-size: 1.7rem;
    font-weight: 700;
    margin: 0;
    line-height: 1.2;
    background: linear-gradient(135deg, #f2f2f2 0%, {_ACCENT_BRIGHT} 140%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}}
[data-testid="stSidebar"] .stCaption p, [data-testid="stSidebar"] small {{
    letter-spacing: 0.06em;
}}
</style>
"""

_LANDING_CSS = f"""
<style>
.hero-section {{
    text-align: center;
    padding: 3.5rem 1rem 2.5rem;
}}
.hero-title {{
    font-family: {_SERIF};
    font-size: 3rem;
    font-weight: 700;
    line-height: 1.15;
    margin: 0 0 0.75rem;
    background: linear-gradient(135deg, #f2f2f2 0%, {_ACCENT_BRIGHT} 150%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}}
.hero-subtitle {{
    font-size: 1.15rem;
    color: #a8a8b0;
    max-width: 640px;
    margin: 0 auto;
    line-height: 1.6;
}}
.feature-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1rem;
    margin: 2.5rem 0;
}}
.feature-card {{
    background-color: #131318; border: 1px solid #24242c; border-top: 2px solid {_ACCENT};
    border-radius: 12px; padding: 1.25rem;
    box-shadow: 0 4px 16px rgba(0,0,0,0.35);
    transition: border-color 0.15s ease, transform 0.15s ease;
}}
.feature-card:hover {{ border-color: {_ACCENT_BRIGHT}; transform: translateY(-2px); }}
.feature-icon {{
    width: 42px; height: 42px; border-radius: 10px;
    background: rgba(20, 184, 166, 0.12); color: {_ACCENT_BRIGHT};
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 0.75rem;
}}
.feature-title {{ font-weight: 700; color: #f2f2f2; margin-bottom: 0.35rem; }}
.feature-desc {{ font-size: 0.9rem; color: #9a9aa2; line-height: 1.5; margin: 0; }}
.pipeline-row {{
    display: flex; flex-wrap: wrap; align-items: center; justify-content: center;
    gap: 0.4rem; margin: 1.5rem 0 2.5rem;
}}
.pipeline-chip {{
    background-color: #131318; border: 1px solid #24242c; border-radius: 999px;
    padding: 0.45rem 1rem; font-size: 0.85rem; color: #d0d0d6; font-weight: 600;
}}
.pipeline-arrow {{ color: {_ACCENT}; font-size: 1.1rem; }}
.auth-card {{
    max-width: 420px; margin: 0 auto; background-color: #101014;
    border: 1px solid #24242c; border-radius: 14px; padding: 1.75rem;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}}
.welcome-banner {{
    display: flex; align-items: center; justify-content: space-between;
    background-color: #131318; border: 1px solid #24242c; border-left: 3px solid {_ACCENT};
    border-radius: 10px; padding: 0.9rem 1.25rem; margin-bottom: 1.5rem;
}}
</style>
"""

st.markdown(_DARK_CSS, unsafe_allow_html=True)
st.markdown(_FONT_CSS, unsafe_allow_html=True)
st.markdown(_BUTTON_CSS, unsafe_allow_html=True)
st.markdown(_LANDING_CSS, unsafe_allow_html=True)


_FEATURES = [
    (
        '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M4 19h16"/>',
        "Data Ingestion",
        "Real ingestion from CSV, API, and SFTP sources, with schema-drift handling and retry-on-failure built in.",
    ),
    (
        '<circle cx="9" cy="12" r="5"/><circle cx="15" cy="12" r="5"/>',
        "Intelligent Matching",
        "Exact, tolerance, and fuzzy matching, boosted by a growing match-memory and optional LLM-assisted matching for ambiguous pairs.",
    ),
    (
        '<path d="M12 3l9 16H3z"/><path d="M12 9v5"/><circle cx="12" cy="17" r="0.6" fill="currentColor"/>',
        "Exception Management",
        "Every unmatched item is classified and risk-scored, with an SLA deadline that scales by risk -- nothing sits unreviewed indefinitely.",
    ),
    (
        '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 13l2 2 4-5"/>',
        "Reporting",
        "Live close-readiness at a glance, with a one-click audit-ready export (summary + every underlying table) for any run.",
    ),
]

_PIPELINE_STAGES = ["Ingest", "Validate", "Normalize", "Match", "Classify", "Report"]


def _icon_svg(path: str) -> str:
    return (
        f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        f'stroke-linejoin="round">{path}</svg>'
    )


def _render_landing() -> None:
    # Every fragment below is built as a single unindented line before
    # being handed to st.markdown -- CommonMark treats 4+ leading spaces
    # as a code block, and once one HTML block ends at a blank line, any
    # indented content that follows gets swallowed as a code block
    # instead of rendered HTML. Multi-line indented triple-quoted f-strings
    # tripped exactly this: the first card rendered, every card after it
    # showed as raw escaped text. Keeping everything on one line per
    # st.markdown call sidesteps the ambiguity entirely.
    hero_html = (
        '<div class="hero-section">'
        '<p class="brand-wordmark" style="font-size: 3.2rem; display:inline-block;">RecoFin</p>'
        '<div class="hero-title">Agentic financial reconciliation, actually agentic.</div>'
        '<div class="hero-subtitle">A real multi-agent pipeline reconciles your books '
        "against your bank — ingesting, validating, normalizing, matching, classifying "
        "exceptions with risk scores and SLA deadlines, and producing an audit-ready "
        "report — all on a compiled LangGraph, not a mocked-up demo.</div>"
        "</div>"
    )
    st.markdown(hero_html, unsafe_allow_html=True)

    cards_html = "".join(
        f'<div class="feature-card"><div class="feature-icon">{_icon_svg(path)}</div>'
        f'<div class="feature-title">{title}</div>'
        f'<p class="feature-desc">{desc}</p></div>'
        for path, title, desc in _FEATURES
    )
    st.markdown(f'<div class="feature-grid">{cards_html}</div>', unsafe_allow_html=True)

    chips = []
    for i, stage in enumerate(_PIPELINE_STAGES):
        chips.append(f'<span class="pipeline-chip">{stage}</span>')
        if i < len(_PIPELINE_STAGES) - 1:
            chips.append('<span class="pipeline-arrow">&#8594;</span>')
    st.markdown(f'<div class="pipeline-row">{"".join(chips)}</div>', unsafe_allow_html=True)

    st.markdown('<div class="auth-card">', unsafe_allow_html=True)
    login_tab, register_tab = st.tabs(["Log in", "Register"])

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Log in", type="primary", use_container_width=True)
        if submitted:
            try:
                user = authenticate(auth_engine, username, password)
                st.session_state.user = {"username": user.username, "email": user.email}
                st.rerun()
            except AuthError as e:
                st.error(str(e))

    with register_tab:
        if registration_disabled:
            st.warning(
                "Registration is temporarily disabled on this deployment -- no "
                "persistent database is configured (DATABASE_URL), so accounts "
                "created here would be wiped on the next deploy. Log in still "
                "works if you already have an account from before the last "
                "redeploy. Ask the app owner to configure a persistent database "
                "to re-enable sign-up."
            )
        else:
            with st.form("register_form"):
                reg_username = st.text_input("Username", key="register_username")
                reg_email = st.text_input("Email", key="register_email")
                reg_password = st.text_input("Password", type="password", key="register_password")
                reg_submitted = st.form_submit_button(
                    "Create account", type="primary", use_container_width=True
                )
            if reg_submitted:
                try:
                    user = register_user(auth_engine, reg_username, reg_email, reg_password)
                    st.session_state.user = {"username": user.username, "email": user.email}
                    st.rerun()
                except AuthError as e:
                    st.error(str(e))
    st.markdown("</div>", unsafe_allow_html=True)


if st.session_state.user is None:
    _render_landing()
    st.stop()


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
    if gateway is not None:
        st.caption("LLM gateway: connected — semantic matching and ambiguous-row review are live.")
    else:
        st.caption("LLM gateway: not configured — deterministic-only mode.")

_greeting_col, _logout_col = st.columns([5, 1])
with _greeting_col:
    st.markdown(
        f'<div class="welcome-banner">Hey <strong>{st.session_state.user["username"]}</strong> '
        f"— ready to reconcile.</div>",
        unsafe_allow_html=True,
    )
with _logout_col:
    if st.button("Log out", use_container_width=True):
        st.session_state.user = None
        st.rerun()

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
            graph = build_graph(gateway=gateway)
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
        if gateway is not None:
            st.caption(
                "Four deterministic checks always run (completeness, dedupe, "
                "format, FX), plus LLM review for ambiguous (no-reference) rows "
                "since a gateway is configured for this run."
            )
        else:
            st.caption(
                "Four deterministic checks always run (completeness, dedupe, "
                "format, FX). Ambiguous-row LLM review is disabled (no gateway "
                "configured), so only deterministic findings appear here."
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
