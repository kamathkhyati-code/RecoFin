import pandas as pd
import requests
import streamlit as st

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="RecoFin Demo", page_icon="$", layout="wide")

with st.sidebar:
    st.header("RecoFin")
    st.write(
        "An agentic reconciliation system - it matches a company's books "
        "against the bank and flags what doesn't line up."
    )
    st.markdown("**Pipeline**")
    st.markdown(
        "1. **Ingest** - pull from CSV / API / SFTP\n"
        "2. **Validate** - catch bad data\n"
        "3. **Normalize** - one currency, canonical names\n"
        "4. **Match** - real matching agent: exact -> tolerance -> fuzzy"
    )
    st.caption(f"UI calls the FastAPI backend at {API_URL}")

st.title("RecoFin - Reconciliation Demo")
st.write("**Ingest -> Validate -> Normalize -> Match** (via FastAPI backend)")

if st.button("Run reconciliation", type="primary"):
    try:
        resp = requests.post(f"{API_URL}/reconcile", timeout=30)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        st.error(f"Could not reach the API at {API_URL}: {e}")
        st.stop()

    data = resp.json()
    summary = data["summary"]
    matches = data["matches"]
    unmatched = data["unmatched"]
    book_raw = data["book_raw"]
    book_normalized = data["book_normalized"]
    bank_raw = data["bank_raw"]
    findings = data["validation_findings"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Match rate", f"{summary['match_rate']:.0f}%")
    c2.metric("Matched", summary["matched"])
    c3.metric("Unmatched", summary["unmatched"])
    c4.metric("Bad rows rejected", summary["bad_rows_rejected"])

    chart = pd.DataFrame(
        {"count": [summary["matched"], summary["unmatched"], summary["bad_rows_rejected"]]},
        index=["Matched", "Unmatched", "Rejected"],
    )
    st.bar_chart(chart)

    t1, t2, t3 = st.tabs(
        ["Results", "Normalization (before -> after)", "Raw & findings"]
    )
    with t1:
        st.subheader("Matched pairs")
        st.dataframe(matches, use_container_width=True)
        st.subheader("Unmatched - needs review")
        st.dataframe(unmatched, use_container_width=True)
    with t2:
        st.write(
            "Normalization converts everything to USD and canonical names, "
            "so the book and bank become comparable."
        )
        a, b = st.columns(2)
        with a:
            st.caption("Book - raw")
            st.dataframe(book_raw, use_container_width=True)
        with b:
            st.caption("Book - normalized")
            st.dataframe(book_normalized, use_container_width=True)
    with t3:
        st.subheader("Validation findings")
        st.dataframe(findings or [{"status": "all clean"}], use_container_width=True)
        st.subheader("Bank - raw ingested")
        st.dataframe(bank_raw, use_container_width=True)
