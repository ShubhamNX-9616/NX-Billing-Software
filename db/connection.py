import sqlite3
import os
from flask import g, has_app_context
from utils import ist_today

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "billing.db")

IST_NOW = "datetime('now', '+5 hours', '+30 minutes')"


def begin_write(conn):
    """Take SQLite's write lock now (BEGIN IMMEDIATE) instead of at the first write.

    Handlers that read a balance / stock level / counter and then write a value
    derived from it must call this BEFORE the read. Otherwise two requests at the
    same moment both read the same old value and both pass the check: two payments
    of the full balance, or two sales of the last piece, would both succeed. With
    the lock taken first, the second request waits (see busy_timeout) until the
    first has committed and then reads the updated figures. Works on any of the
    app's SQLite connections; the transaction ends at commit() / rollback(), or when
    the connection closes at the end of the request."""
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _open_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Now that the server runs threaded, two requests can genuinely write at
    # the same instant — wait up to 5s for the other's lock instead of
    # failing immediately with "database is locked".
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_db():
    """Return the per-request DB connection, cached in Flask g.
    Outside a request context (startup scripts) returns a plain connection."""
    if has_app_context():
        if 'db' not in g:
            g.db = _open_connection()
        return g.db
    return _open_connection()


def close_db(e=None):
    """Close the per-request connection. Register with app.teardown_appcontext."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def current_fy():
    """Return the current Indian financial year suffix, e.g. '26-27' for FY 2026-27.
    Uses today's date in IST, not the server's clock: on a UTC server the year would
    otherwise roll over 5.5 hours late, and bills in that window would carry the old
    financial year in their number."""
    today = ist_today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{str(start)[2:]}-{str(start + 1)[2:]}"


def generate_inst_bill_number(conn):
    fy = current_fy()
    row = conn.execute("SELECT next_val, fy FROM inst_bill_number_seq WHERE id = 1").fetchone()
    if row is None or row["fy"] != fy:
        new_val = 1
        conn.execute(
            "INSERT OR REPLACE INTO inst_bill_number_seq (id, next_val, fy) VALUES (1, ?, ?)",
            (new_val, fy),
        )
    else:
        conn.execute("UPDATE inst_bill_number_seq SET next_val = next_val + 1 WHERE id = 1")
        row = conn.execute("SELECT next_val FROM inst_bill_number_seq WHERE id = 1").fetchone()
        new_val = row["next_val"]
    return f"INST-{new_val:04d}/{fy}"


def generate_bill_number(conn):
    fy = current_fy()
    row = conn.execute("SELECT next_val, fy FROM bill_number_seq WHERE id = 1").fetchone()
    if row["fy"] != fy:
        # New financial year — reset counter to 1
        new_val = 1
        conn.execute(
            "UPDATE bill_number_seq SET next_val = ?, fy = ? WHERE id = 1",
            (new_val, fy),
        )
    else:
        conn.execute("UPDATE bill_number_seq SET next_val = next_val + 1 WHERE id = 1")
        row = conn.execute("SELECT next_val FROM bill_number_seq WHERE id = 1").fetchone()
        new_val = row["next_val"]
    return f"SHN-{new_val:04d}/{fy}"
