"""Read-only health check of the shop's data.

Dates and money are stored as plain text / numbers with no database-level rules, so
a bad value saved before the app validated its input (a date typed as "31/11/2026",
a balance that no longer equals total minus paid) sits unnoticed and quietly drops
a bill out of a report. This looks for those, changes nothing, and is meant to be
run before relying on the new validation, and now and then afterwards:

    python scripts/check_data.py

The databases are opened read-only: it cannot modify them even by mistake.
"""
import os
import sqlite3
from urllib.request import pathname2url

from utils import valid_iso_date

TOLERANCE = 0.011        # a paisa of floating-point slack


def open_readonly(path):
    uri = "file:" + pathname2url(os.path.abspath(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                        (table,)).fetchone() is not None


def _problem(check, table, row_id, detail):
    return {"check": check, "table": table, "id": row_id, "detail": detail}


def _date_problems(conn, table, column, label, required, id_col="id"):
    """Rows whose date column is not a real YYYY-MM-DD. Timestamps ("2026-11-01
    12:30:00", used by payment rows) are judged on their date part."""
    out = []
    if not _table_exists(conn, table):
        return out
    for row in conn.execute(f"SELECT {id_col} AS rid, {column} AS value FROM {table}"):
        value = row["value"]
        if value is None or str(value).strip() == "":
            if required:
                out.append(_problem(label, table, row["rid"], f"{column} is empty"))
            continue
        if not valid_iso_date(str(value)[:10]) or (len(str(value)) > 10 and str(value)[10] not in " T"):
            out.append(_problem(label, table, row["rid"], f"{column} = {value!r}"))
    return out


def _math_problems(conn, table, label, sql, describe):
    out = []
    if not _table_exists(conn, table):
        return out
    for row in conn.execute(sql):
        out.append(_problem(label, table, row["id"], describe(row)))
    return out


def _precision_problems(conn, table, columns):
    """Money amounts are meant to be whole paise (2 decimals). A value such as 100.005
    or 33.3333333 means something skipped the rounding on its way in, and it will make
    a balance disagree with the printed figure by a fraction of a paisa."""
    out = []
    if not _table_exists(conn, table):
        return out
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for column in columns:
        if column not in existing:
            continue
        for row in conn.execute(
                f"SELECT id, {column} AS value FROM {table} "
                f"WHERE {column} IS NOT NULL AND ABS({column} - ROUND({column}, 2)) > 1e-9"):
            out.append(_problem("Amount with fractions of a paisa", table, row["id"],
                                f"{column} = {row['value']!r}"))
    return out


BILLING_MONEY = (
    ("bills", ("subtotal", "total_discount", "final_total", "total_savings", "round_off",
               "advance_paid", "remaining")),
    # bill_items.mrp is left out on purpose: a per-metre rate may legitimately carry more decimals
    ("bill_items", ("line_total", "discount_amount", "rate_after_disc", "final_amount")),
    ("bill_payments", ("amount",)),
    ("institution_bills", ("subtotal", "round_off", "final_total", "advance_paid", "remaining")),
    ("institution_bill_payments", ("amount",)),
)
TAILORING_MONEY = tuple(
    entry for prefix in ("tailoring_", "tailoring_suit_") for entry in (
        (prefix + "orders", ("total", "advance", "balance", "cloth_balance")),
        (prefix + "items", ("amount",)),   # rate may carry 3 decimals: 966.666 x 3 = 2900
        (prefix + "payments", ("amount",)),
    ))
MEASUREMENT_MONEY = (
    ("m_orders", ("total", "cloth_balance", "advance", "balance")),
    ("m_measurements", ("amount",)),
    ("m_payments", ("amount",)),
)


def check_billing(conn):
    problems = []
    problems += _date_problems(conn, "bills", "bill_date", "Bad bill date", required=True)
    problems += _date_problems(conn, "bill_payments", "paid_at", "Bad payment date", required=False)
    problems += _date_problems(conn, "institution_bills", "bill_date", "Bad bill date", required=True)
    problems += _date_problems(conn, "institution_bill_payments", "paid_at", "Bad payment date", required=False)

    problems += _math_problems(
        conn, "bills", "Balance does not match",
        f"SELECT id, bill_number, final_total, advance_paid, remaining FROM bills "
        f"WHERE ABS(remaining - (final_total - advance_paid)) > {TOLERANCE} AND status != 'cancelled'",
        lambda r: f"{r['bill_number']}: total {r['final_total']} - paid {r['advance_paid']} "
                  f"should leave {round(r['final_total'] - r['advance_paid'], 2)}, but remaining is {r['remaining']}")
    problems += _math_problems(
        conn, "bills", "Negative amount",
        "SELECT id, bill_number, final_total, advance_paid, remaining FROM bills "
        "WHERE final_total < 0 OR advance_paid < 0 OR remaining < -0.011",
        lambda r: f"{r['bill_number']}: total {r['final_total']}, paid {r['advance_paid']}, remaining {r['remaining']}")
    problems += _math_problems(
        conn, "bills", "Total does not match items",
        f"SELECT b.id, b.bill_number, b.final_total, b.round_off, "
        f"       ROUND(COALESCE(SUM(i.final_amount), 0), 2) AS items_total "
        f"FROM bills b LEFT JOIN bill_items i ON i.bill_id = b.id "
        f"GROUP BY b.id "
        # Early bills (before the round-off column existed) stored round_off = 0 while
        # the total had been rounded down; the app derives that rounding when it shows
        # them (compute_bill_display_fields). So with round_off = 0 only the dangerous
        # direction counts: a total HIGHER than its items. With a recorded round-off
        # the figures must match exactly.
        f"HAVING COUNT(i.id) > 0 AND ("
        f"  (b.round_off != 0 AND ABS(b.final_total - (items_total - b.round_off)) > {TOLERANCE})"
        f"  OR b.final_total > items_total - b.round_off + {TOLERANCE})",
        lambda r: f"{r['bill_number']}: items add up to {r['items_total']} (round-off {r['round_off']}) "
                  f"but the bill total is {r['final_total']}")
    problems += _math_problems(
        conn, "institution_bills", "Balance does not match",
        f"SELECT id, bill_number, final_total, advance_paid, remaining FROM institution_bills "
        f"WHERE advance_paid <= final_total "
        f"AND ABS(remaining - (final_total - advance_paid)) > {TOLERANCE} AND status != 'cancelled'",
        lambda r: f"{r['bill_number']}: total {r['final_total']} - paid {r['advance_paid']} "
                  f"should leave {round(r['final_total'] - r['advance_paid'], 2)}, but remaining is {r['remaining']}")
    for table, columns in BILLING_MONEY:
        problems += _precision_problems(conn, table, columns)
    return problems


def check_tailoring(conn):
    problems = []
    for table in ("tailoring_orders", "tailoring_suit_orders"):
        problems += _date_problems(conn, table, "order_date", "Bad order date", required=True)
        problems += _date_problems(conn, table, "trial_date", "Bad trial date", required=False)
        problems += _date_problems(conn, table, "delivery_date", "Bad delivery date", required=False)
        problems += _math_problems(
            conn, table, "Balance does not match",
            f"SELECT id, order_number, total, cloth_balance, advance, balance FROM {table} "
            f"WHERE ABS(balance - (total + cloth_balance - advance)) > {TOLERANCE}",
            lambda r: f"order {r['order_number']}: total {r['total']} + cloth {r['cloth_balance']} - "
                      f"paid {r['advance']} should leave "
                      f"{round(r['total'] + r['cloth_balance'] - r['advance'], 2)}, but balance is {r['balance']}")
        problems += _math_problems(
            conn, table, "Paid more than owed",
            f"SELECT id, order_number, total, cloth_balance, advance FROM {table} "
            f"WHERE advance > total + cloth_balance + {TOLERANCE}",
            lambda r: f"order {r['order_number']}: paid {r['advance']} against a total of "
                      f"{round(r['total'] + r['cloth_balance'], 2)}")
    problems += _date_problems(conn, "tailoring_payments", "paid_at", "Bad payment date", required=False)
    problems += _date_problems(conn, "tailoring_suit_payments", "paid_at", "Bad payment date", required=False)
    for table, columns in TAILORING_MONEY:
        problems += _precision_problems(conn, table, columns)
    return problems


def check_measurements(conn):
    problems = []
    problems += _date_problems(conn, "m_orders", "order_date", "Bad order date", required=True)
    problems += _date_problems(conn, "m_orders", "trial_date", "Bad trial date", required=False)
    problems += _date_problems(conn, "m_orders", "delivery_date", "Bad delivery date", required=False)
    problems += _math_problems(
        conn, "m_orders", "Balance does not match",
        f"SELECT id, order_type, order_number, total, cloth_balance, advance, balance FROM m_orders "
        f"WHERE ABS(balance - (total + cloth_balance - advance)) > {TOLERANCE}",
        lambda r: f"{r['order_type']} #{r['order_number']}: expected "
                  f"{round(r['total'] + r['cloth_balance'] - r['advance'], 2)}, balance is {r['balance']}")
    for table, columns in MEASUREMENT_MONEY:
        problems += _precision_problems(conn, table, columns)
    return problems


def run_checks(billing_path=None, tailoring_path=None, measurements_path=None):
    """Returns (problems, skipped). `skipped` lists databases that were not found."""
    problems, skipped = [], []
    for label, path, fn in (("billing.db", billing_path, check_billing),
                            ("tailoring.db", tailoring_path, check_tailoring),
                            ("measurements.db", measurements_path, check_measurements)):
        if not path or not os.path.exists(path):
            skipped.append(label)
            continue
        conn = open_readonly(path)
        try:
            for p in fn(conn):
                p["database"] = label
                problems.append(p)
        finally:
            conn.close()
    return problems, skipped


def format_report(problems, skipped, per_check=10):
    lines = []
    if skipped:
        lines.append("Not checked (file not found): " + ", ".join(skipped))
    if not problems:
        lines.append("No problems found.")
        return "\n".join(lines)
    groups = {}
    for p in problems:
        groups.setdefault((p["database"], p["table"], p["check"]), []).append(p)
    lines.append(f"{len(problems)} problem(s) found:\n")
    for (database, table, check), rows in sorted(groups.items()):
        lines.append(f"{check} - {database} / {table}: {len(rows)}")
        for p in rows[:per_check]:
            lines.append(f"    id {p['id']}: {p['detail']}")
        if len(rows) > per_check:
            lines.append(f"    ... and {len(rows) - per_check} more")
    return "\n".join(lines)
