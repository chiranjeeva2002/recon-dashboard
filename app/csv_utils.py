import csv
import io
import json
import re
from datetime import datetime
from typing import Optional


def read_csv_text(text: str) -> list[dict]:
    """Parses CSV text into a list of dicts, tolerant of BOM/CRLF, trims values."""
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        if row is None:
            continue
        # skip fully blank rows (e.g. trailing newline artifacts)
        if all((v is None or str(v).strip() == "") for v in row.values()):
            continue
        rows.append({(k.strip() if k else k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    return rows


def normalize_ref(ref: Optional[str]) -> str:
    return (ref or "").strip().upper()


def to_number(value) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def parse_order_date(value: Optional[str]) -> Optional[datetime]:
    """orders.csv dates look like '2025-04-13 00:00:00'."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


_PAYMENT_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})$")


def parse_payment_date(value: Optional[str]) -> Optional[datetime]:
    """payments.csv dates look like '02/04/2025 18:39' -> DD/MM/YYYY HH:mm."""
    if not value:
        return None
    match = _PAYMENT_DATE_RE.match(value.strip())
    if not match:
        return None
    dd, mm, yyyy, hh, minute = (int(g) for g in match.groups())
    try:
        return datetime(yyyy, mm, dd, hh, minute)
    except ValueError:
        return None


def normalize_orders(raw_rows: list[dict]) -> list[dict]:
    """Returns normalized order dicts, flagging exact-duplicate export rows."""
    seen: set[str] = set()
    result = []
    for r in raw_rows:
        order_id = (r.get("order_id") or "").strip()
        fingerprint = json.dumps(r, sort_keys=True)
        is_duplicate_row = fingerprint in seen
        seen.add(fingerprint)

        result.append(
            {
                "order_id": order_id,
                "normalized_id": normalize_ref(order_id),
                "order_date": parse_order_date(r.get("order_date")),
                "customer_email": (r.get("customer_email") or "").strip() or None,
                "currency": (r.get("currency") or "").strip().upper(),
                "gross_amount": to_number(r.get("gross_amount")),
                "discount": to_number(r.get("discount")),
                "net_amount": to_number(r.get("net_amount")),
                "status": (r.get("status") or "").strip().lower(),
                "is_duplicate_row": is_duplicate_row,
            }
        )
    return result


def normalize_payments(raw_rows: list[dict]) -> list[dict]:
    result = []
    for r in raw_rows:
        order_reference = (r.get("order_reference") or "").strip()
        result.append(
            {
                "transaction_ref": (r.get("transaction_ref") or "").strip(),
                "processed_at": parse_payment_date(r.get("processed_at")),
                "order_reference": order_reference,
                "normalized_ref": normalize_ref(order_reference),
                "currency": (r.get("currency") or "").strip().upper(),
                "amount": to_number(r.get("amount")),
                "fee": to_number(r.get("fee")),
                "net_settled": to_number(r.get("net_settled")),
                "type": (r.get("type") or "").strip().lower(),
                "status": (r.get("status") or "").strip().lower(),
            }
        )
    return result