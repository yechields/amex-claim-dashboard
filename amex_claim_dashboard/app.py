import streamlit as st
import requests
import pandas as pd
from datetime import date

import storage
from storage import upsert_purchase, update_purchase, fetch_audit
from importers import import_amex_csv, parse_receipt_file
from rules import evaluate
from packet import generate_packet
from config import ANNUAL_LIMIT


st.set_page_config(page_title="Amex Return Protection Dashboard", layout="wide")

con = storage.connect()

st.title("Amex Return Protection Dashboard")
st.write("Local-first claim assistant.")


def plaid_backend_available():
    return "PLAID_BACKEND_URL" in st.secrets


with st.sidebar:
    st.header("Auto Import")

    if plaid_backend_available():
        st.success("Plaid backend is connected.")
    else:
        st.error("Missing PLAID_BACKEND_URL in secrets")

    if st.button("Connect Amex"):
        if plaid_backend_available():
            st.markdown(
                f"[Open Plaid Connect]({st.secrets['PLAID_BACKEND_URL']}/link)",
                unsafe_allow_html=True,
            )
        else:
            st.error("Missing PLAID_BACKEND_URL in Streamlit secrets.")

    st.divider()

    st.header("Manual Import")

    amex_file = st.file_uploader("Upload Amex transaction CSV", type=["csv"], key="amex")

    if amex_file and st.button("Import Amex CSV"):
        records, err = import_amex_csv(amex_file)

        if err:
            st.error(err)
        else:
            created = 0

            for rec in records:
                _, is_new = upsert_purchase(con, rec)
                created += int(is_new)

            st.success(f"Imported {len(records)} rows, {created} new purchases.")
            st.rerun()

    receipt_files = st.file_uploader(
        "Upload receipt/order files",
        type=["eml", "html", "htm", "txt", "csv"],
        accept_multiple_files=True,
    )

    if receipt_files and st.button("Import receipts"):
        total = 0
        warnings = []

        for f in receipt_files:
            records, err = parse_receipt_file(f)

            if err:
                warnings.append(f"{f.name}: {err}")
                continue

            for rec in records:
                _, is_new = upsert_purchase(con, rec)
                total += int(is_new)

        st.success(f"Imported {total} new receipt-derived purchases.")

        for w in warnings:
            st.warning(w)

        st.rerun()


st.header("Plaid Transactions")

if st.button("Preview Plaid Transactions"):
    try:
        res = requests.get(f"{st.secrets['PLAID_BACKEND_URL']}/transactions")
        data = res.json()

        if "error" in data:
            st.error(data["error"])
        else:
            transactions = data.get("transactions", [])

            if not transactions:
                st.warning("No transactions found.")
            else:
                df_txn = pd.DataFrame(transactions)

                cols = [
                    c
                    for c in [
                        "date",
                        "name",
                        "merchant_name",
                        "amount",
                        "account_id",
                        "category",
                        "pending",
                    ]
                    if c in df_txn.columns
                ]

                st.success(f"Loaded {len(transactions)} transactions.")
                st.dataframe(df_txn[cols], use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Could not load Plaid transactions: {e}")


if st.button("Import Plaid Transactions into Claim Tracker"):
    try:
        res = requests.get(f"{st.secrets['PLAID_BACKEND_URL']}/transactions")
        data = res.json()

        if "error" in data:
            st.error(data["error"])
        else:
            transactions = data.get("transactions", [])

            if not transactions:
                st.warning("No transactions found.")
            else:
                created = 0
                attempted = 0

                for t in transactions:
                    amount = t.get("amount", 0)

                    if amount <= 0:
                        continue

                    merchant = t.get("merchant_name") or t.get("name") or "Unknown"

                    rec = {
                        "purchase_date": str(pd.to_datetime(t.get("date")).date()),                        
                        "merchant": merchant,
                        "item": t.get("name") or merchant,
                        "amount": amount,
                        "card": t.get("account_id"),
                    }

                    attempted += 1
                    _, is_new = upsert_purchase(con, rec)
                    created += int(is_new)

                st.success(f"Imported {attempted} purchase transactions, {created} new.")
                st.rerun()

    except Exception as e:
        st.error(f"Could not import Plaid transactions: {e}")


st.divider()

purchases = pd.read_sql_query("SELECT * FROM purchases ORDER BY purchase_date DESC", con)

if purchases.empty:
    st.info("No tracked purchases yet. Connect Plaid and import transactions, or upload a CSV.")
    st.stop()


rows = []

for _, row in purchases.iterrows():
    r = row.to_dict()
    r.update(evaluate(r))
    rows.append(r)

df = pd.DataFrame(rows)

summary_cols = st.columns(4)

summary_cols[0].metric("Tracked purchases", len(df))
summary_cols[1].metric(
    "Ready/possible claims",
    int((df["status"] == "Claim window").sum()) if "status" in df else 0,
)
summary_cols[2].metric(
    "Urgent",
    int((df["status"] == "Urgent").sum()) if "status" in df else 0,
)
summary_cols[3].metric("Annual limit", f"${ANNUAL_LIMIT:,.0f}")


status_filter = st.multiselect(
    "Filter by status",
    sorted(df["status"].dropna().unique()) if "status" in df else [],
    default=[],
)

view = df.copy()

if status_filter:
    view = view[view["status"].isin(status_filter)]


display_cols = [
    c
    for c in [
        "id",
        "purchase_date",
        "merchant",
        "item",
        "amount",
        "card",
        "status",
        "days_since_purchase",
        "claim_deadline",
        "reason",
    ]
    if c in view.columns
]

st.dataframe(view[display_cols], use_container_width=True, hide_index=True)


st.subheader("Claim Actions")

selected_id = st.selectbox(
    "Select purchase ID",
    options=view["id"].tolist() if "id" in view else [],
)

if selected_id:
    rec = df[df["id"] == selected_id].iloc[0].to_dict()
    latest = evaluate(rec)

    st.write(
        {
            "merchant": rec.get("merchant"),
            "item": rec.get("item"),
            "amount": rec.get("amount"),
            "status": latest.get("status"),
            "reason": latest.get("reason"),
            "claim_deadline": latest.get("claim_deadline"),
        }
    )

    col1, col2, col3, col4 = st.columns(4)

    if col1.button("Approve for claim"):
        update_purchase(con, selected_id, {"claim_state": "approved"})
        st.success("Marked approved.")
        st.rerun()

    if col2.button("Ignore"):
        update_purchase(con, selected_id, {"claim_state": "ignored"})
        st.success("Marked ignored.")
        st.rerun()

    if col3.button("Generate claim packet"):
        path = generate_packet(rec)
        st.success(f"Created packet: {path}")

    if col4.button("Mark submitted"):
        update_purchase(
            con,
            selected_id,
            {
                "claim_state": "submitted",
                "submitted_date": str(date.today()),
            },
        )
        st.success("Marked submitted.")
        st.rerun()


st.subheader("Audit Log")

audit = fetch_audit(con)

if audit:
    st.dataframe(pd.DataFrame(audit), use_container_width=True, hide_index=True)
else:
    st.caption("No audit entries yet.")
