# Amex Return Protection Dashboard for Mac

A local-first dashboard that helps track eligible Amex Return Protection claim opportunities without maintaining a spreadsheet.

## What it does

- Imports Amex transaction CSV files.
- Imports receipt/order confirmation files exported from Gmail as `.eml`, `.html`, `.txt`, or `.csv`.
- Stores everything locally in `data/claims.db`.
- Shows purchase age, claim deadline, and status.
- Flags potential claim candidates between day 31 and day 89.
- Generates a claim packet folder and PDF checklist for approved candidates.
- Keeps claim submission human-approved.

## What it intentionally does not do

- It does not store your Amex password.
- It does not bypass MFA.
- It does not silently submit claims.
- It does not fabricate merchant refusal or item condition.

## Mac setup

1. Install Python 3.11 or newer.
2. Open Terminal.
3. Run:

```bash
cd /path/to/amex_claim_dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The dashboard opens in your browser at `http://localhost:8501`.

## Amex CSV import

Export your card transactions from Amex as CSV, then upload them in the dashboard.

The importer looks for common columns like:

- Date
- Description
- Amount
- Card Member / Account

If your export uses different headers, the app will still try to infer them.

## Receipt import

For the first version, export Gmail receipts manually or use Google Takeout/Gmail download to get `.eml`, `.html`, `.txt`, or `.csv` files. Upload them in the dashboard. The app extracts merchant, amount, and purchase date when possible.

Later upgrade: add Gmail OAuth so this can scan receipts automatically after you approve access.

## Submission flow

For each claim candidate:

1. Review the item.
2. Confirm the item is unused/new.
3. Confirm the merchant refused or will not accept the return.
4. Generate packet.
5. Use the packet to file the claim through Amex Claims Center.

## Policy assumptions

The default configuration assumes a 90-day claim window, $300 item cap, and $1,000 annual cap. Always confirm the current terms for your exact Amex card before submitting.
