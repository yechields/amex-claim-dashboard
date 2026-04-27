import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

import storage

st.set_page_config(page_title="Amex Return Protection Dashboard", layout="wide")

con = storage.connect()


def ensure_columns(con):
    cols = {row[1] for row in con.execute("PRAGMA table_info(purchases)").fetchall()}

    if "claim_state" not in cols:
        con.execute("ALTER TABLE purchases ADD COLUMN claim_state TEXT DEFAULT 'monitoring'")

    if "submitted_date" not in cols:
        con.execute("ALTER TABLE purchases ADD COLUMN submitted_date TEXT")

    con.commit()


ensure_columns(con)


def clean_date(value):
    try:
        return str(pd.to_datetime(value).date())
    except Exception:
        return None


def claim_deadline(value):
    d = clean_date(value)
    if not d:
        return None
    return str(pd.to_datetime(d).date() + timedelta(days=90))


def recommendation(row):
    merchant = str(row.get("merchant", "")).lower()
    amount = float(row.get("amount") or 0)

    junk = ["payment", "deposit", "transfer", "interest", "credit card", "thank", "ach"]

    if any(w in merchant for w in junk):
        return "ignore"
    if amount < 20:
        return "ignore"
    if amount >= 100:
        return "likely_claim"
    return "maybe"


def update_claim_state(purchase_id, state):
    if state == "submitted":
        con.execute(
            "UPDATE purchases SET claim_state = ?, submitted_date = ? WHERE id = ?",
            (state, str(datetime.now().date()), int(purchase_id)),
        )
    else:
        con.execute(
            "UPDATE purchases SET claim_state = ? WHERE id = ?",
            (state, int(purchase_id)),
        )
    con.commit()


def backend_ok():
    return "PLAID_BACKEND_URL" in st.secrets


st.title("Amex Return Protection Dashboard")
st.write("Local-first claim assistant.")


with st.sidebar:
    st.header("Auto Import")

    if backend_ok():
        st.success("Plaid backend is connected.")
    else:
        st.error("Missing PLAID_BACKEND_URL")

    if st.button("Connect Amex"):
        st.markdown(
            f"[Open Plaid Connect]({st.secrets['PLAID_BACKEND_URL']}/link)",
            unsafe_allow_html=True,
        )

    if st.button("Load Transactions"):
        try:
            res = requests.get(f"{st.secrets['PLAID_BACKEND_URL']}/transactions")
            data = res.json()

            if "error" in data:
                st.error(data["error"])
            else:
                created = 0

                for t in data.get("transactions", []):
                    amount = float(t.get("amount") or 0)

                    if amount <= 0:
                        continue

                    merchant = t.get("merchant_name") or t.get("name") or "Unknown"
                    pdate = clean_date(t.get("date"))

                    con.execute(
                        """
                        INSERT INTO purchases
                        (purchase_date, merchant, amount, card, claim_state)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            pdate,
                            merchant,
                            amount,
                            t.get("account_id"),
                            "monitoring",
                        ),
                    )

                    created += 1

                con.commit()
                st.success(f"Loaded {created} transactions.")
                st.rerun()

        except Exception as e:
            st.error(f"Could not load transactions: {e}")


df = pd.read_sql_query("SELECT * FROM purchases ORDER BY purchase_date DESC", con)

if df.empty:
    st.info("No purchases yet. Connect Plaid and click Load Transactions.")
    st.stop()

df["purchase_date"] = df["purchase_date"].apply(clean_date)
df["claim_deadline"] = df["purchase_date"].apply(claim_deadline)
df["recommendation"] = df.apply(recommendation, axis=1)

if "claim_state" not in df.columns:
    df["claim_state"] = "monitoring"

st.subheader("Transactions")

filter_option = st.selectbox(
    "Filter",
    ["all", "likely_claim", "maybe", "ignore", "monitoring", "approved", "ignored", "submitted"],
)

view = df.copy()

if filter_option in ["likely_claim", "maybe", "ignore"]:
    view = view[view["recommendation"] == filter_option]

if filter_option in ["monitoring", "approved", "ignored", "submitted"]:
    view = view[view["claim_state"] == filter_option]

cols = [
    c
    for c in [
        "id",
        "purchase_date",
        "merchant",
        "amount",
        "claim_deadline",
        "claim_state",
        "recommendation",
    ]
    if c in view.columns
]

st.dataframe(view[cols], use_container_width=True, hide_index=True)


st.subheader("Claim Actions")

selected_id = st.selectbox(
    "Select purchase ID",
    options=view["id"].tolist() if "id" in view else [],
)

if selected_id:
    selected_id_int = int(selected_id)
    rec = df[df["id"] == selected_id_int].iloc[0].to_dict()

    st.write(
        {
            "merchant": rec.get("merchant"),
            "amount": rec.get("amount"),
            "claim_state": rec.get("claim_state"),
            "recommendation": rec.get("recommendation"),
            "claim_deadline": rec.get("claim_deadline"),
        }
    )

    col1, col2, col3 = st.columns(3)

    if col1.button("Approve for claim"):
        update_claim_state(selected_id_int, "approved")
        st.success("Marked approved.")
        st.rerun()

    if col2.button("Ignore"):
        update_claim_state(selected_id_int, "ignored")
        st.success("Marked ignored.")
        st.rerun()

    if col3.button("Mark submitted"):
        update_claim_state(selected_id_int, "submitted")
        st.success("Marked submitted.")
        st.rerun()
