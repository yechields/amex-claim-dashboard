import streamlit as st
import requests

st.set_page_config(page_title="Amex Return Protection Dashboard")

st.title("Amex Return Protection Dashboard")
st.write("Local-first claim assistant.")

# =========================
# SIDEBAR (PLAID)
# =========================
with st.sidebar:
    st.header("Auto Import")

    if "PLAID_BACKEND_URL" in st.secrets:
        st.success("Plaid backend is connected.")
    else:
        st.error("Missing PLAID_BACKEND_URL in secrets")

    # Button → opens Plaid Link page
    if st.button("Connect Amex"):
        st.markdown(
            f"[Open Plaid Connect]({st.secrets['PLAID_BACKEND_URL']}/link)",
            unsafe_allow_html=True
        )

# =========================
# MAIN IMPORT SECTION
# =========================
st.divider()

st.header("Import")

amex_file = st.file_uploader(
    "Upload Amex transaction CSV",
    type=["csv"]
)

if amex_file:
    st.success("File uploaded (not processed in this step)")

# =========================
# LOAD PLAID TRANSACTIONS
# =========================
st.divider()

st.header("Transactions")

if st.button("Load Transactions"):
    try:
        res = requests.get(
            f"{st.secrets['PLAID_BACKEND_URL']}/transactions"
        )
        data = res.json()

        if "error" in data:
            st.error(data["error"])
        else:
            transactions = data.get("transactions", [])

            if not transactions:
                st.warning("No transactions found")
            else:
                st.success(f"Loaded {len(transactions)} transactions")

                for t in transactions[:25]:
                    st.write(
                        f"{t.get('date')} — {t.get('name')} — ${t.get('amount')}"
                    )

    except Exception as e:
        st.error(f"Error: {e}")
