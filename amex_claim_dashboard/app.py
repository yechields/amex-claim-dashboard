import streamlit as st
import pandas as pd
from datetime import date
import streamlit.components.v1 as components

import storage
from storage import upsert_purchase, update_purchase, fetch_audit
from importers import import_amex_csv, parse_receipt_file
from rules import evaluate
from packet import generate_packet
from config import ANNUAL_LIMIT

try:
    import plaid
    from plaid.api import plaid_api
    from plaid.api_client import ApiClient
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.products import Products
    from plaid.model.country_code import CountryCode
except Exception:
    plaid = None
    plaid_api = None


st.set_page_config(page_title="Amex Return Protection Dashboard", layout="wide")

con = storage.connect()

st.title("Amex Return Protection Dashboard")
st.caption("Local-first claim assistant. It prepares and organizes claims; you approve and submit.")


def plaid_available():
    return (
        plaid is not None
        and plaid_api is not None
        and "PLAID_CLIENT_ID" in st.secrets
        and "PLAID_SECRET" in st.secrets
    )


def make_plaid_client():
    if not plaid_available():
        return None

    env = st.secrets.get("PLAID_ENV", "sandbox")

    host = plaid.Environment.Sandbox
    if env == "development":
        host = plaid.Environment.Development
    elif env == "production":
        host = plaid.Environment.Production

    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": st.secrets["PLAID_CLIENT_ID"],
            "secret": st.secrets["PLAID_SECRET"],
        },
    )

    api_client = ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)


with st.sidebar:
    st.header("Auto Import")

    if plaid_available():
        st.success("Plaid is connected in app settings.")
    else:
        st.warning("Plaid is not fully configured yet.")

    if st.button("if st.button("Connect Amex"):     st.markdown(         f"[Open Plaid Connect]({st.secrets['PLAID_BACKEND_URL']}/link)",         unsafe_allow_html=True     )"):
        client = make_plaid_client()

        if not client:
            st.error("Plaid client could not load.")
        else:
            try:
                request = LinkTokenCreateRequest(
                    products=[Products("transactions")],
                    client_name="Amex Dashboard",
                    country_codes=[CountryCode("US")],
                    language="en",
                    user=LinkTokenCreateRequestUser(client_user_id="user-id"),
                )

                response = client.link_token_create(request)
                link_token = response["link_token"]

                components.html(f"""
                <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
                <script>
                const handler = Plaid.create({{
                    token: "{link_token}",
                    onSuccess: function(public_token, metadata) {{
                        alert("Plaid connected. Public token created. Next step is token exchange.");
                        console.log(public_token);
                    }},
                    onExit: function(err, metadata) {{
                        console.log("Plaid Link exited", err, metadata);
                    }}
                }});
                handler.open();
                </script>
                """, height=500)

                st.info("Plaid popup should open.")
            except Exception as e:
                st.error(f"Could not create Plaid link token: {e}")

    st.divider()

    st.header("Import")
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


purchases = pd.read_sql_query("SELECT * FROM purchases ORDER BY purchase_date DESC", con)

if purchases.empty:
    st.info("Import an Amex CSV or receipt files to begin. Sample CSV is included in sample_exports/sample_amex.csv.")
    st.stop()

rows = []
for _, row in purchases.iterrows():
    r = row.to_dict()
    r.update(evaluate(r))
    rows.append(r)

df = pd.DataFrame(rows)

summary_cols = st.columns(4)
summary_cols[0].metric("Tracked purchases", len(df))
summary_cols[1].metric("Ready/possible claims", int((df["status"] == "Claim window").sum()) if "status" in df else 0)
summary_cols[2].metric("Urgent", int((df["status"] == "Urgent").sum()) if "status" in df else 0)
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
    c for c in [
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
    ] if c in view.columns
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
        update_purchase(con, selected_id, {"claim_state": "submitted", "submitted_date": str(date.today())})
        st.success("Marked submitted.")
        st.rerun()

st.subheader("Audit Log")
audit = fetch_audit(con)
if audit:
    st.dataframe(pd.DataFrame(audit), use_container_width=True, hide_index=True)
else:
    st.caption("No audit entries yet.")
