from datetime import date, datetime, timedelta
from config import CLAIM_WINDOW_DAYS, CLAIM_START_DAY, URGENT_DAY, ITEM_LIMIT, DEFAULT_IGNORE_BELOW, EXCLUDED_KEYWORDS

def parse_date(s):
    if isinstance(s, date):
        return s
    return datetime.fromisoformat(str(s)).date()

def evaluate(row, today=None):
    today = today or date.today()
    pdate = parse_date(row['purchase_date'])
    age = (today - pdate).days
    deadline = pdate + timedelta(days=CLAIM_WINDOW_DAYS)
    day30 = pdate + timedelta(days=30)
    lower_text = ' '.join([str(row.get('merchant','')), str(row.get('description','')), str(row.get('notes',''))]).lower()
    excluded_hits = [kw for kw in EXCLUDED_KEYWORDS if kw in lower_text]
    amount = float(row['amount'])
    reasons = []
    if amount < DEFAULT_IGNORE_BELOW:
        reasons.append('Below default value threshold')
    if amount > ITEM_LIMIT:
        reasons.append(f'Over ${ITEM_LIMIT:.0f} item cap')
    if excluded_hits:
        reasons.append('Possible exclusion: ' + ', '.join(excluded_hits[:3]))
    if age < CLAIM_START_DAY:
        reasons.append('Too early')
    if age > CLAIM_WINDOW_DAYS:
        reasons.append('Past 90-day window')
    if row.get('status') in ('ignored', 'submitted', 'closed'):
        reasons.append(f"Status is {row.get('status')}")
    needs_docs = []
    if not row.get('receipt_path'):
        needs_docs.append('receipt')
    if not row.get('merchant_refused'):
        needs_docs.append('merchant refusal/expired return proof')
    if not row.get('item_unused'):
        needs_docs.append('unused/new confirmation')
    candidate = (CLAIM_START_DAY <= age <= CLAIM_WINDOW_DAYS and amount <= ITEM_LIMIT and not excluded_hits and row.get('status') not in ('ignored','submitted','closed'))
    urgent = URGENT_DAY <= age <= CLAIM_WINDOW_DAYS
    return {
        'age_days': age,
        'day30_check': day30.isoformat(),
        'claim_deadline': deadline.isoformat(),
        'days_left': (deadline - today).days,
        'candidate': candidate,
        'urgent': urgent,
        'blocked_reasons': reasons,
        'needs_docs': needs_docs,
        'ready_to_packet': candidate and not needs_docs and bool(row.get('user_approved'))
    }
