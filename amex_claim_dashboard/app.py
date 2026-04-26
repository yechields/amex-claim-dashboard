import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import storage
from rules import evaluate

st.set_page_config(page_title="Amex Return Protection Dashboard", layout="wide")

# -----------------------
# DB SETUP
# -----------------------
con = storage.connect()

def ensure_columns(con):
    cols = {row[1] for row in con.execute("PRAGMA table_info(purchases)").fetchall()}

    if "claim_state" not in cols:
        con.execute("ALTER TABLE purchases ADD COLUMN claim_state TEXT DEFAULT 'monitoring'")

    if "submitted_date" not in cols:
        con.execute("ALTER TABLE purchases ADD COLUMN submitted_date TEXT")

    con.commit()

ensure_columns(con)

# -----------------------
# HELPERS
# -----------------------
def plaid_backend_available():
    return "PLAID_BACKEND_URL" in st.secrets

def get_transactions():
    url = st.secrets["PLAID_BACKEND_URL"] + "/transactions"
    res = requests.get(url)
    return res.json()["transactions"]

def clean_transactions(txns):
    df = pd.DataFrame(txns)

    if df.empty:
        return df

    df["purchase_date"] = pd.to_datetime(df["date"]).dt.date
    df["merchant"] = df["name"]
    df["amount"] = df["amount"].astype(float)

    return df

def is_junk(row):
    name = str(row.get("merchant", "")).lower()

    junk_words = [
        "payment", "thank", "deposit", "credit", "transfer",
        "withdrawal", "interest", "cd deposit"
    ]

    return any(word in name for word in junk_words)

def get_recommendation(row):
    if is_junk(row):
        return "ignore"

    amt = row.get("amount", 0)

    if amt < 20:
        return "ignore"

    if amt >= 100:
        return "likely_claim"

    return "maybe"

def update_purchase(con, purchase_id, claim_state):
    con.execute(
        "UPDATE purchases SET claim_state = ? WHERE id = ?",
        (claim_state, purchase_id)
    )
    con.commit()

# -----------------------
# UI
# -----------------------
st.title("Amex Return Protection Dashboard")
st.write("Local-first claim assistant.")

# -----------------------
# AUTO IMPORT
# -----------------------
st.sidebar.header("Auto Import")

if plaid_backend_available():
    st.sidebar.success("Plaid backend is connected.")
else:
    st.sidebar.warning("Plaid backend not configured.")

if st.sidebar.button("Load Transactions"):
    txns = get_transactions()
    df = clean_transactions(txns)

    if not df.empty:
        for _, row in df.iterrows():
            con.execute("""
                INSERT INTO purchases (purchase_date, merchant, amount, card)
                VALUES (?, ?, ?, ?)
            """, (
                str(row["purchase_date"]),
                row["merchant"],
                float(row["amount"]),
                "plaid"
            ))
        con.commit()
        st.success(f"Loaded {len(df)} transactions")

# -----------------------
# LOAD DATA
# -----------------------
df = pd.read_sql("SELECT * FROM purchases ORDER BY purchase_date DESC", con)

if not df.empty:
    df["recommendation"] = df.apply(get_recommendation, axis=1)

# -----------------------
# FILTER
# -----------------------
st.subheader("Transactions")

filter_option = st.selectbox(
    "Filter by status",
    ["all", "likely_claim", "maybe", "ignore"]
)

view = df.copy()

if filter_option != "all":
    view = view[view["recommendation"] == filter_option]

st.dataframe(view, use_container_width=True)

# -----------------------
# CLAIM ACTIONS
# -----------------------
st.subheader("Claim Actions")

if not view.empty:
    selected_id = st.selectbox(
        "Select purchase ID",
        options=view["id"].tolist()
    )

    selected_id_int = int(selected_id)

    rec = df[df["id"] == selected_id_int].iloc[0].to_dict()
    latest = evaluate(rec)

    st.json(latest)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("Approve for claim"):
            update_purchase(con, selected_id_int, "approved")
            st.success("Marked as approved")
            st.rerun()

    with col2:
        if st.button("Ignore"):
            update_purchase(con, selected_id_int, "ignored")
            st.success("Ignored")
            st.rerun()

    with col3:
        if st.button("Generate claim packet"):
            st.info("Coming next step")

    with col4:
        if st.button("Mark submitted"):
            con.execute(
                "UPDATE purchases SET claim_state = ?, submitted_date = ? WHERE id = ?",
                ("submitted", str(datetime.now().date()), selected_id_int)
            )
            con.commit()
            st.success("Marked submitted")
            st.rerun()

# -----------------------
# AUDIT LOG
# -----------------------
st.subheader("Audit Log")

audit = pd.read_sql("SELECT * FROM audit_log ORDER BY id DESC LIMIT 20", con)

if not audit.empty:
    st.dataframe(audit, use_container_width=True)
