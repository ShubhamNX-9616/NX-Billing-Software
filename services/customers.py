from utils import normalize_mobile


def get_customer_by_mobile(db, raw_mobile):
    """Normalize raw mobile and look up the customer. Returns (norm, customer_dict) or (norm, None)."""
    norm = normalize_mobile(raw_mobile)
    row = db.execute(
        "SELECT * FROM customers WHERE normalized_mobile = ?", (norm,)
    ).fetchone()
    return norm, dict(row) if row else None


def get_customer_stats(db, raw_mobile):
    """Return billing stats for the customer with the given raw mobile number.
    Returns (norm, stats_dict, last_bill_dict_or_None)."""
    norm = normalize_mobile(raw_mobile)
    stats = db.execute("""
        SELECT COUNT(b.id)                        AS total_bills,
               COALESCE(SUM(b.final_total), 0)    AS total_spent
        FROM   customers c
        JOIN   bills b ON b.customer_id = c.id
        WHERE  c.normalized_mobile = ?
          AND  b.status != 'cancelled'
    """, (norm,)).fetchone()
    last = db.execute("""
        SELECT b.bill_number, b.bill_date, b.final_total
        FROM   bills b
        JOIN   customers c ON c.id = b.customer_id
        WHERE  c.normalized_mobile = ?
          AND  b.status != 'cancelled'
        ORDER  BY b.bill_date DESC, b.id DESC
        LIMIT  1
    """, (norm,)).fetchone()
    return norm, dict(stats), dict(last) if last else None
