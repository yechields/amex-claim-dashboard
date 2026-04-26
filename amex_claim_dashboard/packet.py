from pathlib import Path
from datetime import datetime
import shutil
from pathlib import Path
from datetime import datetime
import shutil

CLAIM_DIR = Path("claim_packets")
CLAIM_DIR.mkdir(exist_ok=True)


def generate_packet(purchase):
    merchant = str(purchase.get("merchant", "unknown")).replace("/", "-")
    item = str(purchase.get("item", "item")).replace("/", "-")
    packet_name = f"{merchant}_{item}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    packet_folder = CLAIM_DIR / packet_name
    packet_folder.mkdir(parents=True, exist_ok=True)

    summary_path = packet_folder / "claim_summary.txt"

    lines = [
        "Amex Return Protection Claim Packet",
        "",
        f"Merchant: {purchase.get('merchant', '')}",
        f"Item: {purchase.get('item', '')}",
        f"Purchase Date: {purchase.get('purchase_date', '')}",
        f"Amount: {purchase.get('amount', '')}",
        f"Card: {purchase.get('card', '')}",
        f"Status: {purchase.get('status', '')}",
        "",
        "Checklist:",
        "- Receipt included",
        "- Amex transaction included",
        "- Merchant return attempted/refused",
        "- Item unused/new condition",
        "- Within 90 days of purchase",
        "- Under applicable Amex Return Protection limits",
    ]

    summary_path.write_text("\n".join(lines))

    return str(packet_folder)
from rules import evaluate

PACKET_DIR = Path('claim_packets')

def generate_packet(row):
    ev = evaluate(row)
    pid = row['id']
    merchant_safe = ''.join(c if c.isalnum() else '_' for c in row['merchant'])[:50]
    folder = PACKET_DIR / f"{pid}_{merchant_safe}_{row['purchase_date']}"
    folder.mkdir(parents=True, exist_ok=True)

    receipt_path = row.get('receipt_path')
    if receipt_path and Path(receipt_path).exists():
        shutil.copy2(receipt_path, folder / Path(receipt_path).name)

    checklist = folder / 'claim_checklist.pdf'
    c = canvas.Canvas(str(checklist), pagesize=letter)
    width, height = letter
    y = height - 50
    def line(txt, gap=18):
        nonlocal y
        c.drawString(50, y, txt[:105])
        y -= gap
    c.setFont('Helvetica-Bold', 15)
    line('Amex Return Protection Claim Packet')
    c.setFont('Helvetica', 10)
    line(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    line(f"Purchase ID: {pid}")
    line(f"Merchant: {row['merchant']}")
    line(f"Description: {row.get('description') or ''}")
    line(f"Purchase date: {row['purchase_date']}")
    line(f"Amount: ${float(row['amount']):.2f}")
    line(f"Card: {row.get('card') or 'Not specified'}")
    line(f"Claim deadline: {ev['claim_deadline']} ({ev['days_left']} days left)")
    y -= 10
    c.setFont('Helvetica-Bold', 12)
    line('Before submitting, confirm:')
    c.setFont('Helvetica', 10)
    checks = [
        'Item was charged entirely to eligible Amex card.',
        'Item is unused/new and eligible under current policy.',
        'Merchant will not accept the return or return window expired.',
        'Claim is submitted before the 90-day deadline.',
        'Annual Return Protection cap has not been exceeded.',
        'No exclusions apply based on current Amex terms.'
    ]
    for item in checks:
        line('[ ] ' + item)
    y -= 8
    c.setFont('Helvetica-Bold', 12)
    line('Included / needed evidence:')
    c.setFont('Helvetica', 10)
    line(f"Receipt file: {'included' if receipt_path else 'missing'}")
    line(f"Merchant refusal / return proof: {'confirmed' if row.get('merchant_refused') else 'missing'}")
    line(f"Unused/new confirmation: {'confirmed' if row.get('item_unused') else 'missing'}")
    y -= 8
    c.setFont('Helvetica-Bold', 12)
    line('Notes:')
    c.setFont('Helvetica', 10)
    notes = row.get('notes') or ''
    for chunk in [notes[i:i+95] for i in range(0, len(notes), 95)] or ['']:
        line(chunk)
    c.save()

    readme = folder / 'README.txt'
    readme.write_text(
        'Use this folder when filing the Amex Return Protection claim. Review the checklist and upload supporting documents.\n'
        'This app does not verify your card-specific terms; confirm current Amex policy before submitting.\n'
    )
    return folder
