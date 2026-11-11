"""Standalone database module for the Measurements trial.

Deliberately independent from billing.db and tailoring.db — measurements live
in their own SQLite file (measurements.db) with their own connection and
schema, so the trial can be changed or deleted without touching either of the
existing systems. Customers are keyed on normalized mobile number.
"""
import os
import sqlite3

from flask import g, has_app_context

from utils import normalize_mobile

MEASUREMENTS_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "measurements.db")

IST_NOW = "datetime('now', '+5 hours', '+30 minutes')"

SCHEMA = f"""
    CREATE TABLE IF NOT EXISTS m_customers (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        mobile     TEXT NOT NULL UNIQUE,
        name       TEXT NOT NULL,
        address    TEXT,
        created_at TEXT DEFAULT ({IST_NOW})
    );

    CREATE TABLE IF NOT EXISTS m_measurements (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id   INTEGER NOT NULL REFERENCES m_customers(id) ON DELETE CASCADE,
        garment_type  TEXT NOT NULL,
        values_json   TEXT NOT NULL DEFAULT '{{}}',
        notes         TEXT,
        image         TEXT,
        order_date    TEXT,
        trial_date    TEXT,
        delivery_date TEXT,
        status        TEXT NOT NULL DEFAULT 'Measured',
        created_at    TEXT DEFAULT ({IST_NOW}),
        updated_at    TEXT DEFAULT ({IST_NOW})
    );

    CREATE INDEX IF NOT EXISTS idx_m_measurements_customer ON m_measurements(customer_id);
    CREATE INDEX IF NOT EXISTS idx_m_measurements_dates
        ON m_measurements(delivery_date, trial_date);
"""


def _open_connection():
    conn = sqlite3.connect(MEASUREMENTS_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.create_function("norm_mobile", 1, lambda m: normalize_mobile(m or ""))
    return conn


def get_measurements_db():
    """Per-request measurements DB connection, cached in Flask g. Outside a
    request context (startup scripts) returns a plain connection."""
    if has_app_context():
        if "measurements_db" not in g:
            g.measurements_db = _open_connection()
        return g.measurements_db
    return _open_connection()


def close_measurements_db(e=None):
    """Close the per-request connection. Register with app.teardown_appcontext."""
    db = g.pop("measurements_db", None)
    if db is not None:
        db.close()


def init_measurements_db(conn=None):
    """Create the measurements tables if they don't exist yet."""
    own = conn is None
    if own:
        conn = _open_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    if own:
        conn.close()
