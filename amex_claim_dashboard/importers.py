import re
import csv
from pathlib import Path
from datetime import datetime
from email import policy
from email.parser import BytesParser
import pandas as pd
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

UPLOAD_DIR = Path('data/uploads')
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

AMOUNT_RE = re.compile(r'(?<!\w)(?:USD\s*)?\$\s*([0-9,]+(?:\.[0-9]{2})?)')
DATE_RE = re.compile(r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b')

def _norm_date(value):
    if pd.isna(value):
        return None
    try:
        return dateparser.parse(str(value), fuzzy=True).date().isoformat()
    except Exception:
        return None

def _norm_amount(value):
    if pd.isna(value):
        return None
    s = str(value).replace('$', '').replace(',', '').strip()
    try:
        return abs(float(s))
    except Exception:
        return None

def _find_col(columns, candidates):
    lower = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        for lc, orig in lower.items():
            if cand in lc:
                return orig
    return None

def import_amex_csv(file_obj):
    df = pd.read_csv(file_obj)
    date_col = _find_col(df.columns, ['date'])
    desc_col = _find_col(df.columns, ['description', 'merchant', 'name'])
    amount_col = _find_col(df.columns, ['amount', 'charge'])
    card_col = _find_col(df.columns, ['card', 'account'])
    records = []
    if not (date_col and desc_col and amount_col):
        return records, f'Could not infer required CSV columns. Found: {list(df.columns)}'
    for idx, row in df.iterrows():
        d = _norm_date(row[date_col])
        amount = _norm_amount(row[amount_col])
        desc = str(row[desc_col]).strip() if not pd.isna(row[desc_col]) else 'Unknown purchase'
        if not d or amount is None or amount == 0:
            continue
        records.append({
            'source': 'amex_csv',
            'purchase_date': d,
            'merchant': desc.split('  ')[0][:80],
            'description': desc,
            'amount': amount,
            'card': str(row[card_col]).strip() if card_col and not pd.isna(row[card_col]) else None,
            'transaction_ref': f'csv-row-{idx}'
        })
    return records, None

def _extract_text_from_upload(path):
    ext = path.suffix.lower()
    if ext == '.eml':
        msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        parts = []
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ('text/plain', 'text/html'):
                try:
                    parts.append(part.get_content())
                except Exception:
                    pass
        return '\n'.join(parts), msg.get('From', '') or msg.get('Subject', '')
    raw = path.read_text(errors='ignore')
    if ext in ('.html', '.htm'):
        soup = BeautifulSoup(raw, 'lxml')
        return soup.get_text('\n'), soup.title.get_text(' ', strip=True) if soup.title else ''
    return raw, path.name

def parse_receipt_file(file_obj):
    safe_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', file_obj.name)
    path = UPLOAD_DIR / f'{datetime.utcnow().strftime("%Y%m%d%H%M%S")}_{safe_name}'
    path.write_bytes(file_obj.getvalue())
    if path.suffix.lower() == '.csv':
        # Treat receipt CSV like a generic order export.
        records, err = import_amex_csv(path)
        for r in records:
            r['source'] = 'receipt_csv'
            r['receipt_path'] = str(path)
        return records, err
    text, header = _extract_text_from_upload(path)
    text_compact = re.sub(r'\s+', ' ', text)
    amounts = [float(x.replace(',', '')) for x in AMOUNT_RE.findall(text_compact)]
    date_match = DATE_RE.search(text_compact)
    purchase_date = _norm_date(date_match.group(0)) if date_match else None
    amount = max(amounts) if amounts else None
    merchant = 'Unknown merchant'
    if header:
        merchant = re.sub(r'[^A-Za-z0-9 &.-]+', ' ', header).strip()[:80] or merchant
    if not purchase_date or amount is None:
        return [], 'Could not confidently extract date and amount. Keep file attached and add via CSV/import later.'
    return [{
        'source': 'receipt_file',
        'purchase_date': purchase_date,
        'merchant': merchant,
        'description': header or merchant,
        'amount': amount,
        'receipt_path': str(path),
        'notes': 'Auto-parsed receipt; review merchant/amount before filing.'
    }], None
