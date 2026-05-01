import sqlite3
import os
from datetime import date
from flask import g, has_app_context

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "billing.db")


def _open_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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


def _current_fy():
    """Return the current Indian financial year suffix, e.g. '26-27' for FY 2026-27."""
    today = date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{str(start)[2:]}-{str(start + 1)[2:]}"


def generate_bill_number(conn):
    fy = _current_fy()
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
