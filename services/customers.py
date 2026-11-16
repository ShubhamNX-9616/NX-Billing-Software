from utils import normalize_mobile


def get_customer_by_mobile(db, raw_mobile):
    """Normalize raw mobile and look up the customer. Returns (norm, customer_dict) or (norm, None)."""
    norm = normalize_mobile(raw_mobile)
    row = db.execute(
        "SELECT * FROM customers WHERE normalized_mobile = ?", (norm,)
    ).fetchone()
    return norm, dict(row) if row else None


def get_customer_stats(db, raw_mobile, exclude_bill_id=None):
    """Return billing stats for the customer with the given raw mobile number.
    Returns (norm, stats_dict, last_bill_dict_or_None).

    stats also carries the customer's unpaid balance on earlier bills: total_due (rupees)
    and due_bills (how many bills still have a balance). Cancelled bills never count.
    exclude_bill_id leaves one bill out of the due figure only - the edit-bill screen passes
    the bill being edited so its own balance is not reported as a "previous" due."""
    norm = normalize_mobile(raw_mobile)
    stats = db.execute("""
        SELECT COUNT(b.id)                        AS total_bills,
               ROUND(COALESCE(SUM(b.final_total), 0), 2)    AS total_spent
        FROM   customers c
        JOIN   bills b ON b.customer_id = c.id
        WHERE  c.normalized_mobile = ?
          AND  b.status != 'cancelled'
    """, (norm,)).fetchone()
    due = db.execute("""
        SELECT ROUND(COALESCE(SUM(b.remaining), 0), 2) AS total_due,
               COUNT(b.id)                             AS due_bills
        FROM   customers c
        JOIN   bills b ON b.customer_id = c.id
        WHERE  c.normalized_mobile = ?
          AND  b.status != 'cancelled'
          AND  b.remaining > 0.005
          AND  b.id != ?
    """, (norm, exclude_bill_id if exclude_bill_id is not None else -1)).fetchone()
    last = db.execute("""
        SELECT b.bill_number, b.bill_date, b.final_total
        FROM   bills b
        JOIN   customers c ON c.id = b.customer_id
        WHERE  c.normalized_mobile = ?
          AND  b.status != 'cancelled'
        ORDER  BY b.bill_date DESC, b.id DESC
        LIMIT  1
    """, (norm,)).fetchone()
    return norm, {**dict(stats), **dict(due)}, dict(last) if last else None
