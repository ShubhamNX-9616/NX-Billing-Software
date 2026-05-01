from db import get_db
from utils import r2

VALID_PAYMENT_METHODS = {"Cash", "Card", "UPI"}


def validate_and_calculate_items(db, items):
    """Validate items list against DB cloth types and compute per-item financials.
    Returns list of calculated item dicts. Raises ValueError on any invalid input."""
    if not items or not isinstance(items, list):
        raise ValueError("items array cannot be empty")

    valid_cloth_types = {
        row["type_name"]: dict(row)
        for row in db.execute("SELECT type_name, has_company FROM cloth_types").fetchall()
    }

    calculated_items = []
    for idx, item in enumerate(items):
        prefix         = f"Item {idx + 1}"
        cloth_type     = (item.get("cloth_type")     or "").strip()
        company_name   = (item.get("company_name")   or "").strip()
        quality_number = (item.get("quality_number") or "").strip() or None

        try:
            quantity = float(item["quantity"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{prefix}: quantity must be a number")
        try:
            mrp = float(item["mrp"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{prefix}: mrp must be a number")
        try:
            discount_percent = float(item.get("discount_percent", 0))
        except (TypeError, ValueError):
            raise ValueError(f"{prefix}: discount_percent must be a number")

        if cloth_type not in valid_cloth_types:
            raise ValueError(f"{prefix}: invalid cloth_type '{cloth_type}'")
        if quantity <= 0:
            raise ValueError(f"{prefix}: quantity must be > 0")
        if mrp < 0:
            raise ValueError(f"{prefix}: mrp cannot be negative")
        if not (0 <= discount_percent <= 100):
            raise ValueError(f"{prefix}: discount_percent must be 0–100")

        unit_label      = "m" if cloth_type in ("Shirting", "Suiting") else "pcs"
        disc_per_unit   = r2(mrp * discount_percent / 100)
        rate_after_disc = r2(mrp - disc_per_unit)
        final_amount    = r2(rate_after_disc * quantity)
        line_total      = r2(mrp * quantity)
        discount_amount = r2(line_total - final_amount)

        calculated_items.append({
            "cloth_type":       cloth_type,
            "company_name":     company_name,
            "quality_number":   quality_number,
            "quantity":         quantity,
            "unit_label":       unit_label,
            "mrp":              mrp,
            "line_total":       line_total,
            "discount_percent": discount_percent,
            "discount_amount":  discount_amount,
            "rate_after_disc":  rate_after_disc,
            "final_amount":     final_amount,
        })

    return calculated_items


def calculate_bill_totals(calculated_items, round_off_raw):
    """Compute bill-level totals from calculated items and raw round_off input.
    Returns dict with subtotal, total_discount, gross_final_total, round_off,
    final_total, total_savings. Raises ValueError on invalid round_off."""
    subtotal          = r2(sum(i["line_total"]      for i in calculated_items))
    total_discount    = r2(sum(i["discount_amount"] for i in calculated_items))
    gross_final_total = r2(sum(i["final_amount"]    for i in calculated_items))

    try:
        round_off = r2(float(round_off_raw or 0))
    except (TypeError, ValueError):
        round_off = 0.0
    if round_off < 0:
        raise ValueError("round_off cannot be negative")
    if round_off > gross_final_total:
        raise ValueError("round_off cannot exceed bill total")

    final_total   = r2(gross_final_total - round_off)
    total_savings = r2(total_discount + round_off)

    return {
        "subtotal":          subtotal,
        "total_discount":    total_discount,
        "gross_final_total": gross_final_total,
        "round_off":         round_off,
        "final_total":       final_total,
        "total_savings":     total_savings,
    }


def validate_payments(payments, final_total):
    """Validate payments list and confirm they sum to final_total.
    Raises ValueError on any invalid input."""
    if not payments or not isinstance(payments, list):
        raise ValueError("payments array cannot be empty")
    for p in payments:
        if (p.get("payment_method") or "") not in VALID_PAYMENT_METHODS:
            raise ValueError(f"payment_method must be one of {sorted(VALID_PAYMENT_METHODS)}")
        try:
            float(p["amount"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("payment amount must be a number")
    payments_sum = r2(sum(float(p["amount"]) for p in payments))
    if abs(payments_sum - final_total) > 0.01:
        raise ValueError(
            f"Payments sum ({payments_sum}) does not match final_total ({final_total})"
        )


def parse_advance(raw, final_total):
    """Parse advance_paid from raw input, validate, and return (advance_paid, remaining).
    Raises ValueError on invalid input."""
    try:
        advance_paid = r2(float(raw or 0))
    except (TypeError, ValueError):
        advance_paid = 0.0
    if advance_paid < 0:
        raise ValueError("advance_paid cannot be negative")
    if advance_paid > final_total:
        raise ValueError("advance_paid cannot exceed final_total")
    return advance_paid, r2(final_total - advance_paid)


def get_bill_by_number(bill_number):
    """Fetch a bill with its items and payments by bill_number. Returns None if not found."""
    db = get_db()
    bill = db.execute(
        "SELECT * FROM bills WHERE bill_number = ?", (bill_number,)
    ).fetchone()
    if not bill:
        return None
    items = db.execute(
        "SELECT * FROM bill_items WHERE bill_id = ? ORDER BY id", (bill["id"],)
    ).fetchall()
    payments = db.execute(
        "SELECT * FROM bill_payments WHERE bill_id = ? ORDER BY id", (bill["id"],)
    ).fetchall()
    return {
        "bill":     dict(bill),
        "items":    [dict(i) for i in items],
        "payments": [dict(p) for p in payments],
    }


def find_or_create_customer(db, customer_name, norm_mobile):
    """Return customer_id for norm_mobile, creating the customer if not found.
    The customer's stored name is never overwritten here — edits go through
    the customer management UI so bill-form typos don't corrupt the record."""
    existing = db.execute(
        "SELECT id FROM customers WHERE normalized_mobile = ?", (norm_mobile,)
    ).fetchone()
    if existing:
        return existing["id"]
    cursor = db.execute(
        "INSERT INTO customers (name, mobile, normalized_mobile) VALUES (?, ?, ?)",
        (customer_name, norm_mobile, norm_mobile),
    )
    return cursor.lastrowid
