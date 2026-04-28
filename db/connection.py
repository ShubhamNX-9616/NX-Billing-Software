import sqlite3
import os
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


def generate_bill_number(conn):
    # Atomic increment: SQLite serializes concurrent writers on this single-row UPDATE,
    # eliminating the SELECT-MAX race condition that could produce duplicate bill numbers.
    conn.execute("UPDATE bill_number_seq SET next_val = next_val + 1 WHERE id = 1")
    row = conn.execute("SELECT next_val FROM bill_number_seq WHERE id = 1").fetchone()
    return f"SHN-{row['next_val']:04d}"
