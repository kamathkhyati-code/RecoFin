import pandas as pd
import streamlit as st 
from pathlib import Path 

from datagents.agents.ingestion_agent import ingest_sources 
from datagents.agents.normalization_agent import normalize_transactions
from datagents.agents.validation_agent import validate_transactions
from datagents.schemas import SourceConfig, SourceType

SAMPLE = Path(__file__).parent / "sample_data"
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


def match(book, source):
    matched, unmatched_book, used = [], [], set()
    for b in book:
        hit = None
        for i, s in enumerate(source):
            if (
                i not in used
                and b.amount == s.amount
                and b.date == s.date
                and b.counterparty == s.counterparty
            ):
                hit = s
                used.add(i)
                break
        if hit:
            matched.append((b, hit))
        else:
            unmatched_book.append(b)
    unmatched_source = [s for i, s in enumerate(source) if i not in used]
    return matched, unmatched_book, unmatched_source


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
.stTabs [aria-selected="true"] {{ color: #0f766e !important; }}
hr {{ border-color: #e8e2d3; }}
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
    font-family: Georgia, "Times New Roman", serif;
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
        "4. **Match** — book vs bank"
    )
    st.caption("Demo running on sample book & bank data.")
    st.divider()
    toggle_label = "Light mode" if st.session_state.dark_mode else "Dark mode"
    st.button(toggle_label, on_click=_toggle_theme, use_container_width=True)

st.markdown('<p class="brand-wordmark" style="font-size: 2.2rem;">RecoFin — Reconciliation Demo</p>', unsafe_allow_html=True)
st.write("**Ingest → Validate → Normalize → Match**")

if st.button("Run reconciliation", type="primary"):
    book_res = ingest_sources([
        SourceConfig(
            name="book", source_type=SourceType.CSV,
            location=str(SAMPLE / "demo_book.csv"),
        ),
    ])
    bank_res = ingest_sources([
        SourceConfig(
            name="bank", source_type=SourceType.CSV,
            location=str(SAMPLE / "demo_bank.csv"),
            options={"field_map": BANK_FIELD_MAP},
        ),
    ])

    findings = validate_transactions(book_res.transactions + bank_res.transactions)
    book_norm = normalize_transactions(book_res.transactions)
    bank_norm = normalize_transactions(bank_res.transactions)
    matched, un_book, un_bank = match(book_norm, bank_norm)

    total = len(book_norm) or 1
    rate = len(matched) / total * 100
    rejected = len(book_res.issues) + len(bank_res.issues)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Match rate", f"{rate:.0f}%")
    c2.metric("Matched", len(matched))
    c3.metric("Unmatched", len(un_book) + len(un_bank))
    c4.metric("Bad rows rejected", rejected)

    chart = pd.DataFrame(
        {"count": [len(matched), len(un_book) + len(un_bank), rejected]},
        index=["Matched", "Unmatched", "Rejected"],
    )
    st.bar_chart(chart)

    t1, t2, t3 = st.tabs(
        ["Results", "Normalization (before → after)", "Raw & findings"]
    )

    with t1:
        st.subheader("Matched pairs")
        st.dataframe(
            [
                {
                    "book_id": b.txn_id, "bank_id": s.txn_id,
                    "amount_usd": str(b.amount), "counterparty": b.counterparty,
                    "date": b.date.isoformat(),
                }
                for b, s in matched
            ],
            use_container_width=True,
        )
        st.subheader("Unmatched — needs review")
        st.dataframe(rows(un_book + un_bank), use_container_width=True)

    with t2:
        st.write(
            "Normalization converts everything to USD and canonical names, "
            "so the book and bank become comparable."
        )
        a, b = st.columns(2)
        with a:
            st.caption("Book — raw")
            st.dataframe(rows(book_res.transactions), use_container_width=True)
        with b:
            st.caption("Book — normalized")
            st.dataframe(rows(book_norm), use_container_width=True)

    with t3:
        st.subheader("Validation findings")
        st.dataframe(
            [
                {"txn_id": f.txn_id, "reason": f.reason.value, "escalate": f.escalate}
                for f in findings
            ]
            or [{"status": "all clean"}],
            use_container_width=True,
        )
        st.subheader("Bank — raw ingested")
        st.dataframe(rows(bank_res.transactions), use_container_width=True)