import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path('data/claims.db')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    purchase_date TEXT NOT NULL,
    merchant TEXT NOT NULL,
    description TEXT,
    amount REAL NOT NULL,
    card TEXT,
    receipt_path TEXT,
    transaction_ref TEXT,
    status TEXT DEFAULT 'monitoring',
    item_unused INTEGER DEFAULT 0,
    merchant_refused INTEGER DEFAULT 0,
    user_approved INTEGER DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id INTEGER,
    event TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);
'''

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.commit()
    return con

def add_audit(con, purchase_id, event, details=''):
    con.execute(
        'INSERT INTO audit_log (purchase_id, event, details, created_at) VALUES (?, ?, ?, ?)',
        (purchase_id, event, details, datetime.utcnow().isoformat())
    )
    con.commit()

def upsert_purchase(con, record):
    now = datetime.utcnow().isoformat()
    # Simple duplicate check: date, merchant, amount, description/ref
    row = con.execute(
        '''SELECT id FROM purchases WHERE purchase_date=? AND merchant=? AND ABS(amount - ?) < 0.01
           AND COALESCE(description,'') = COALESCE(?, '') LIMIT 1''',
        (record['purchase_date'], record['merchant'], float(record['amount']), record.get('description'))
    ).fetchone()
    if row:
        pid = row['id']
        con.execute(
            '''UPDATE purchases SET card=COALESCE(?, card), receipt_path=COALESCE(?, receipt_path),
               transaction_ref=COALESCE(?, transaction_ref), updated_at=? WHERE id=?''',
            (record.get('card'), record.get('receipt_path'), record.get('transaction_ref'), now, pid)
        )
        add_audit(con, pid, 'updated', f"Updated from {record.get('source', 'import')}")
        return pid, False
    cur = con.execute(
        '''INSERT INTO purchases
           (source, purchase_date, merchant, description, amount, card, receipt_path, transaction_ref, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (record.get('source'), record['purchase_date'], record['merchant'], record.get('description'),
         float(record['amount']), record.get('card'), record.get('receipt_path'), record.get('transaction_ref'),
         record.get('notes'), now, now)
    )
    con.commit()
    pid = cur.lastrowid
    add_audit(con, pid, 'created', f"Imported from {record.get('source', 'import')}")
    return pid, True

def fetch_purchases(con):
    return con.execute('SELECT * FROM purchases ORDER BY purchase_date DESC, id DESC').fetchall()

def update_purchase(con, purchase_id, **fields):
    if not fields:
        return
    fields['updated_at'] = datetime.utcnow().isoformat()
    sets = ', '.join([f'{k}=?' for k in fields.keys()])
    vals = list(fields.values()) + [purchase_id]
    con.execute(f'UPDATE purchases SET {sets} WHERE id=?', vals)
    con.commit()
    add_audit(con, purchase_id, 'updated_fields', ', '.join(fields.keys()))

def fetch_audit(con, purchase_id=None):
    if purchase_id:
        return con.execute('SELECT * FROM audit_log WHERE purchase_id=? ORDER BY created_at DESC', (purchase_id,)).fetchall()
    return con.execute('SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200').fetchall()
