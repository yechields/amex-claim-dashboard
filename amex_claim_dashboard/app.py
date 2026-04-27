import streamlit as st
import pandas as pd
import requests
from datetime import datetime

import storage
from rules import evaluate


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
    if value is None or pd.isna(value):
        return value
    return str(pd.to_datetime(value).date())


def plaid_backend_available():
    return "PLAID_BACKEND_URL" in st.secrets


def update_claim_state(purchase_id, claim_state):
    if claim_state == "submitted":
        con.execute(
            "UPDATE purchases SET claim_state = ?, submitted_date = ? WHERE id = ?",
            (claim_state, str(datetime.now().date()), int(purchase_id)),
        )
    else:
        con.execute(
            "UPDATE purchases SET claim_state = ? WHERE id = ?",
            (claim_state, int(purchase_id)),
        )

    con.commit()


def is_junk(row):
    merchant = str(row.get("merchant", "")).lower()

    junk_words = [
        "payment",
        "thank",
        "deposit",
        "credit card",
        "transfer",
        "interest",
        "ach",
        "cd deposit",
    ]

    return any(word in merchant for word in junk_words)


def recommendation_for(row):
    if is_junk(row):
        return "ignore"

    amount = float(row.get("amount") or 0)

    if amount < 20:
        return "ignore"

    if amount >= 100:
        return "likely_claim"

    return "maybe"


st.title("Amex Return Protection Dashboard")
st.write("Local-first claim assistant.")


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

    if st.button("Load Transactions"):
        try:
            res = requests.get(f"{st.secrets['PLAID_BACKEND_URL']}/transactions")
            data = res.json()

            if "error" in data:
                st.error(data["error"])
            else:
                transactions = data.get("transactions", [])
                created = 0

                for t in transactions:
                    amount = float(t.get("amount") or 0)

                    if amount <= 0:
                        continue

                    merchant = t.get("merchant_name") or t.get("name") or "Unknown"
                    purchase_date = clean_date(t.get("date"))

                    con.execute(
                        """
                        INSERT INTO purchases
                        (purchase_date, merchant, amount, card, claim_state)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            purchase_date,
                            merchant,
                            amount,
                            t.get("account_id"),
                            "monitoring",
                        ),
                    )

                    created += 1

                con.commit()
                st.success(f"Loaded {created} purchase transactions.")
                st.rerun()

        except Exception as e:
            st.error(f"Could not load transactions: {e}")


df = pd.read_sql_query("SELECT * FROM purchases ORDER BY purchase_date DESC", con)

if df.empty:
    st.info("No purchases yet. Connect Plaid and click Load Transactions.")
    st.stop()


if "purchase_date" in df.columns:
    df["purchase_date"] = df["purchase_date"].apply(clean_date)

df["recommendation"] = df.apply(recommendation_for, axis=1)

rows = []

for _, row in df.iterrows():
    rec = row.to_dict()

    if "purchase_date" in rec:
        rec["purchase_date"] = clean_date(rec["purchase_date"])

    try:
        rec.update(evaluate(rec))
    except Exception:
        pass

    rows.append(rec)

df = pd.DataFrame(rows)


st.subheader("Transactions")

filter_option = st.selectbox(
    "Filter",
    ["all", "likely_claim", "maybe", "ignore", "approved", "submitted"],
)

view = df.copy()

if filter_option in ["likely_claim", "maybe", "ignore"]:
    view = view[view["recommendation"] == filter_option]

if filter_option in ["approved", "submitted"]:
    view = view[view["claim_state"] == filter_option]


display_cols = [
    c
    for c in [
        "id",
        "purchase_date",
        "merchant",
        "amount",
        "status",
        "claim_deadline",
        "claim_state",
        "recommendation",
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
    selected_id_int = int(selected_id)

    rec = df[df["id"] == selected_id_int].iloc[0].to_dict()

    if "purchase_date" in rec:
        rec["purchase_date"] = clean_date(rec["purchase_date"])

    try:
        latest = evaluate(rec)
    except Exception:
        latest = {}

    st.write(
        {
            "merchant": rec.get("merchant"),
            "amount": rec.get("amount"),
            "claim_state": rec.get("claim_state"),
            "recommendation": rec.get("recommendation"),
            "status": latest.get("status"),
            "claim_deadline": latest.get("claim_deadline"),
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


st.subheader("Audit Log")

try:
    audit = pd.read_sql_query("SELECT * FROM audit_log ORDER BY id DESC LIMIT 50", con)
    st.dataframe(audit, use_container_width=True, hide_index=True)
except Exception:
    st.caption("No audit log available yet.")
