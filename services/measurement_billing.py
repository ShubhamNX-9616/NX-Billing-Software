"""Billing rules for the Measurements trial.

Mirrors the money rules of the Tailoring system so the numbers mean the same
thing to staff, but works only on measurements.db (m_orders / m_payments /
m_rates / m_counters) and never touches billing.db or tailoring.db.

    final total = stitching total (sum of garment amounts) + cloth balance
    advance     = sum of recorded payments
    balance     = final total - advance

Payments are the source of truth for the advance; every function here recomputes
the order's totals from the rows rather than adding and subtracting increments,
so the figures cannot drift.
"""
import math

from db.measurements import IST_NOW
from services.measurement_fields import STATUSES

ORDER_TYPES = ("general", "suit")
ORDER_PREFIX = {"general": "M-", "suit": "MS-"}
PAYMENT_MODES = ("Cash", "Phone Pay", "Card")


def parse_money(raw, label):
    """Blank -> 0. Returns (value, error): a non-negative, finite amount rounded
    to paise, or an error message."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return 0.0, None
    try:
        value = round(float(raw), 2)
    except (TypeError, ValueError):
        return None, f"{label} must be a number"
    if not math.isfinite(value):
        return None, f"{label} must be a number"
    if value < 0:
        return None, f"{label} cannot be negative"
    return value, None


def order_label(order_type, number):
    """Display label, e.g. M-0007 (general) or MS-0003 (suits)."""
    return f"{ORDER_PREFIX.get(order_type, 'M-')}{int(number):04d}"


def final_total(total, cloth_balance):
    return round((total or 0) + (cloth_balance or 0), 2)


def next_order_number(db, order_type):
    """Reserve the next number of this order type. Call inside the transaction
    that inserts the order: if that insert fails and rolls back, the number is
    released too, so there are no gaps. Counters only go up, so a deleted
    order's number is never reused."""
    name = f"order_{order_type}"
    db.execute("INSERT OR IGNORE INTO m_counters (name, value) VALUES (?, 0)", (name,))
    db.execute("UPDATE m_counters SET value = value + 1 WHERE name = ?", (name,))
    return db.execute("SELECT value FROM m_counters WHERE name = ?", (name,)).fetchone()[0]


def item_amount(rate, qty):
    return round((rate or 0) * (qty or 1), 2)


def stitching_total(db, order_id):
    row = db.execute("SELECT COALESCE(SUM(amount), 0) FROM m_measurements WHERE order_id = ?",
                     (order_id,)).fetchone()
    return round(row[0], 2)


def paid_total(db, order_id):
    row = db.execute("SELECT COALESCE(SUM(amount), 0) FROM m_payments WHERE order_id = ?",
                     (order_id,)).fetchone()
    return round(row[0], 2)


def payment_problem(db, order_id, new_total=None, new_cloth=None):
    """Return an error string if recording `new_total` / `new_cloth` would leave
    the order with more paid than owed, else None. Pass only what is changing."""
    order = db.execute("SELECT total, cloth_balance FROM m_orders WHERE id = ?",
                       (order_id,)).fetchone()
    total = order["total"] if new_total is None else new_total
    cloth = order["cloth_balance"] if new_cloth is None else new_cloth
    paid = paid_total(db, order_id)
    owed = final_total(total, cloth)
    if paid > owed:
        return (f"Already recorded Rs {paid:.2f} paid, which is more than the new total "
                f"of Rs {owed:.2f} - remove or lower a payment first")
    return None


def recompute_order(db, order_id):
    """Refresh total / advance / balance (and delivered_at) from the rows. Caller commits."""
    order = db.execute("SELECT cloth_balance FROM m_orders WHERE id = ?", (order_id,)).fetchone()
    total = stitching_total(db, order_id)
    advance = paid_total(db, order_id)
    balance = round(final_total(total, order["cloth_balance"]) - advance, 2)
    db.execute(
        f"UPDATE m_orders SET total = ?, advance = ?, balance = ?, "
        f"updated_at = ({IST_NOW}) WHERE id = ?",
        (total, advance, balance, order_id))
    sync_delivered(db, order_id)


def sync_delivered(db, order_id):
    """delivered_at is stamped once every garment reads Delivered, and cleared if
    any is rolled back - the hand-over is one event for the whole order."""
    statuses = [r["status"] for r in db.execute(
        "SELECT status FROM m_measurements WHERE order_id = ?", (order_id,)).fetchall()]
    if statuses and all(s == "Delivered" for s in statuses):
        db.execute(f"UPDATE m_orders SET delivered_at = COALESCE(delivered_at, {IST_NOW}) "
                   "WHERE id = ?", (order_id,))
    else:
        db.execute("UPDATE m_orders SET delivered_at = NULL WHERE id = ?", (order_id,))


def sync_item_dates(db, order_id):
    """Copy the order's dates onto its garment rows. The dashboard reads dates
    from the garment rows, so keeping them in step means an order shows up there
    without the dashboard needing to know about orders. Caller commits."""
    db.execute(
        "UPDATE m_measurements SET "
        "order_date = (SELECT order_date FROM m_orders WHERE id = ?), "
        "trial_date = (SELECT trial_date FROM m_orders WHERE id = ?), "
        "delivery_date = (SELECT delivery_date FROM m_orders WHERE id = ?) "
        "WHERE order_id = ?", (order_id, order_id, order_id, order_id))


def order_status(item_statuses):
    """Order-level status = the earliest stage among its garments."""
    if not item_statuses:
        return STATUSES[0]
    return min(item_statuses, key=lambda s: STATUSES.index(s) if s in STATUSES else 0)


def remember_rate(db, order_type, garment_type, rate):
    """Save a rate as the new default for that garment. A blank/zero rate is not
    remembered, so leaving the field empty never wipes a saved default."""
    if rate and rate > 0:
        db.execute(
            f"INSERT INTO m_rates (order_type, garment_type, rate, updated_at) "
            f"VALUES (?, ?, ?, {IST_NOW}) "
            f"ON CONFLICT(order_type, garment_type) DO UPDATE "
            f"SET rate = excluded.rate, updated_at = excluded.updated_at",
            (order_type, garment_type, rate))


def saved_rates(db):
    """{order_type: {garment_type: rate}} for pre-filling the order form."""
    out = {t: {} for t in ORDER_TYPES}
    for r in db.execute("SELECT order_type, garment_type, rate FROM m_rates"):
        out.setdefault(r["order_type"], {})[r["garment_type"]] = r["rate"]
    return out


def default_rate(db, order_type, garment_type):
    row = db.execute("SELECT rate FROM m_rates WHERE order_type = ? AND garment_type = ?",
                     (order_type, garment_type)).fetchone()
    return row["rate"] if row else 0.0
