from db import get_db
from utils import finite_float, r2, normalize_mobile, validate_indian_mobile

VALID_PAYMENT_METHODS = {"Cash", "Card", "UPI"}
MAX_PIECES = 1_000_000


def _amount_or_zero(raw, label):
    """Lenient money parse used for optional fields (advance, round-off): blank or
    unparseable text counts as 0, as it always has - but NaN / Infinity / absurdly
    large values are an error, because they would otherwise be saved as the amount."""
    try:
        float(raw or 0)
    except (TypeError, ValueError):
        return 0.0
    return finite_float(raw or 0, label)


def validate_inst_payments(payments):
    """Institution bills record payment rows exactly as sent; make sure each has a
    method and a real amount before it reaches the database. Raises ValueError."""
    if payments is None:
        return
    if not isinstance(payments, list):
        raise ValueError("payments must be an array")
    for p in payments:
        if not isinstance(p, dict) or not str(p.get("payment_method") or "").strip():
            raise ValueError("every payment needs a payment_method")
        try:
            amount = finite_float(p.get("amount"))
        except ValueError:
            raise ValueError("payment amount must be a number")
        if amount < 0:
            raise ValueError("payment amount cannot be negative")

_UNIT_LABEL = {"Shirting": "m", "Suiting": "m"}


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
            quantity = finite_float(item["quantity"])
        except (KeyError, ValueError):
            raise ValueError(f"{prefix}: quantity must be a number")
        try:
            mrp = finite_float(item["mrp"])
        except (KeyError, ValueError):
            raise ValueError(f"{prefix}: mrp must be a number")
        try:
            discount_percent = finite_float(item.get("discount_percent", 0))
        except ValueError:
            raise ValueError(f"{prefix}: discount_percent must be a number")

        raw_discount_amount = item.get("discount_amount")
        has_discount_amount = raw_discount_amount is not None
        if has_discount_amount:
            try:
                discount_amount_per_unit = finite_float(raw_discount_amount)
            except ValueError:
                raise ValueError(f"{prefix}: discount_amount must be a number")

        if cloth_type not in valid_cloth_types:
            raise ValueError(f"{prefix}: invalid cloth_type '{cloth_type}'")
        if quantity <= 0:
            raise ValueError(f"{prefix}: quantity must be > 0")
        if mrp <= 0:
            raise ValueError(f"{prefix}: mrp must be greater than 0")
        if not (0 <= discount_percent <= 100):
            raise ValueError(f"{prefix}: discount_percent must be 0–100")
        if has_discount_amount and not (0 <= discount_amount_per_unit <= mrp):
            raise ValueError(f"{prefix}: discount_amount must be between 0 and mrp")

        unit_label = _UNIT_LABEL.get(cloth_type, "pcs")
        # Prefer the rupee discount the client already rounded over recomputing
        # it from discount_percent: mrp -> /mrp*100 -> *mrp/100 is not exactly
        # invertible in floating point, so it can round a paisa off from what
        # the client itself displayed (bill #527).
        disc_per_unit = (
            r2(discount_amount_per_unit) if has_discount_amount
            else r2(mrp * discount_percent / 100)
        )
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

    round_off = r2(_amount_or_zero(round_off_raw, "round_off"))
    if r2(gross_final_total - round_off) < 0:
        raise ValueError("round_off cannot exceed bill total")

    final_total   = r2(gross_final_total - round_off)
    # Rounding up (negative round_off) is not a saving for the customer.
    total_savings = r2(total_discount + max(0.0, round_off))

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
    if payments is None:
        payments = []
    if not isinstance(payments, list):
        raise ValueError("payments must be an array")
    if not payments:
        return
    for p in payments:
        if (p.get("payment_method") or "") not in VALID_PAYMENT_METHODS:
            raise ValueError(f"payment_method must be one of {sorted(VALID_PAYMENT_METHODS)}")
        try:
            finite_float(p["amount"])
        except (KeyError, ValueError):
            raise ValueError("payment amount must be a number")
    payments_sum = r2(sum(finite_float(p["amount"]) for p in payments))
    if abs(payments_sum - final_total) > 0.01:
        raise ValueError(
            f"Payments sum ({payments_sum}) does not match final_total ({final_total})"
        )


def parse_advance(raw, final_total):
    """Parse advance_paid from raw input, validate, and return (advance_paid, remaining).
    Raises ValueError on invalid input."""
    advance_paid = r2(_amount_or_zero(raw, "advance_paid"))
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


def get_institution_bill_by_number(bill_number):
    """Fetch an institution bill with its items and payments by bill_number. Returns None if not found."""
    db = get_db()
    bill = db.execute(
        "SELECT * FROM institution_bills WHERE bill_number = ?", (bill_number,)
    ).fetchone()
    if not bill:
        return None
    items = db.execute(
        "SELECT * FROM institution_bill_items WHERE bill_id = ? ORDER BY id", (bill["id"],)
    ).fetchall()
    payments = db.execute(
        "SELECT payment_method, amount, paid_at FROM institution_bill_payments WHERE bill_id = ? ORDER BY id",
        (bill["id"],),
    ).fetchall()
    return {
        "bill":     dict(bill),
        "items":    [dict(i) for i in items],
        "payments": [dict(p) for p in payments],
    }


def calculate_inst_items(items):
    """Validate and calculate institution bill items.
    Returns (calc_items, subtotal). Raises ValueError on invalid input."""
    if not items or not isinstance(items, list):
        raise ValueError("At least one item is required")

    calc_items = []
    subtotal = 0.0
    for idx, item in enumerate(items):
        prefix = f"Item {idx + 1}"
        try:
            qty_per_pc = r2(finite_float(item.get("quantity_per_pc") or 0))
        except ValueError:
            raise ValueError(f"{prefix}: quantity_per_pc must be a number")
        try:
            rate_per_m = r2(finite_float(item.get("rate_per_m") or 0))
        except ValueError:
            raise ValueError(f"{prefix}: rate_per_m must be a number")
        try:
            no_of_pcs = int(item.get("no_of_pcs") or 0)
            if abs(no_of_pcs) > MAX_PIECES:
                raise ValueError("too many")
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{prefix}: no_of_pcs must be a whole number")
        try:
            stitching_per_unit = r2(finite_float(item.get("stitching_per_unit") or 0))
        except ValueError:
            raise ValueError(f"{prefix}: stitching_per_unit must be a number")

        total = r2((qty_per_pc * rate_per_m * no_of_pcs) + (no_of_pcs * stitching_per_unit))
        if no_of_pcs > 0 and total <= 0:
            raise ValueError(f"{prefix}: amount cannot be 0 — set a rate or stitching charge")
        subtotal += total
        calc_items.append({
            "cloth_type":         (item.get("cloth_type")     or "").strip(),
            "company_name":       (item.get("company_name")   or "").strip(),
            "quality_number":     (item.get("quality_number") or "").strip(),
            "item_code":          (item.get("item_code")      or "").strip(),
            "quantity_per_pc":    qty_per_pc,
            "rate_per_m":         rate_per_m,
            "no_of_pcs":          no_of_pcs,
            "stitching_per_unit": stitching_per_unit,
            "total":              total,
        })

    return calc_items, r2(subtotal)


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


def remove_customer_if_unused(db, customer_id):
    """Delete a customer left behind when a bill edit moved its only bill to
    another mobile number (a mistyped number would otherwise stay in the
    customers list for good). Only deletes when nothing references the row:
    no bills of any status and no loyalty gifts. Returns True if deleted."""
    if not customer_id:
        return False
    in_use = db.execute(
        """SELECT EXISTS(SELECT 1 FROM bills WHERE customer_id = ?)
               OR EXISTS(SELECT 1 FROM loyalty_gifts WHERE customer_id = ?)""",
        (customer_id, customer_id),
    ).fetchone()[0]
    if in_use:
        return False
    db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    return True


def normalize_and_validate_mobile(raw):
    """Normalize raw mobile and validate it's a valid Indian number.
    Raises ValueError if invalid."""
    norm = normalize_mobile(raw)
    if not validate_indian_mobile(norm):
        raise ValueError("Invalid Indian mobile number")
    return norm


def parse_inst_round_off(raw, subtotal):
    """Parse round_off for institution bills. Positive deducts from the subtotal,
    negative adds to it. Returns (round_off, final_total). Raises ValueError if
    the round-off would push the total below zero."""
    round_off = r2(_amount_or_zero(raw, "round_off"))
    final_total = r2(subtotal - round_off)
    if final_total < 0:
        raise ValueError("round_off cannot exceed bill total")
    return round_off, final_total


def parse_inst_advance(raw, final_total):
    """Parse advance_paid for institution bills. Clips remaining to 0 if advance exceeds total."""
    advance_paid = r2(_amount_or_zero(raw, "advance_paid"))
    return advance_paid, r2(max(0.0, final_total - advance_paid))


def parse_inst_advance_percent(raw, default=70.0):
    """Parse the advance_percent note shown on institution proforma invoices.
    Clamped to 0-100; falls back to default on bad input."""
    try:
        pct = finite_float(raw)
    except ValueError:
        return default
    return min(100.0, max(0.0, pct))


def apply_payment(raw_remaining, raw_advance, raw_amount):
    """Validate and compute a payment against a balance.
    Returns (remaining, amount, new_advance, new_remaining). Raises ValueError on bad input."""
    remaining = r2(float(raw_remaining or 0))
    try:
        amount = r2(finite_float(raw_amount or 0))
    except ValueError:
        raise ValueError("amount must be a number")
    if amount <= 0:
        raise ValueError("amount must be greater than 0")
    if amount > remaining:
        raise ValueError(f"amount ({amount}) exceeds balance due ({remaining})")
    return remaining, amount, r2(float(raw_advance or 0) + amount), r2(remaining - amount)


def compute_bill_display_fields(bill, items):
    """Compute gross_final_total and round_off for a bill GET response."""
    gross_final_total = r2(sum(float(i["final_amount"] or 0) for i in items))
    stored_round_off = float(bill["round_off"] or 0)
    if stored_round_off != 0:
        round_off = stored_round_off
    else:
        round_off = r2(gross_final_total - float(bill["final_total"] or 0))
    return gross_final_total, round_off
