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

    -- Billing (trial). An order groups the garments taken for one customer and
    -- carries the money: total / cloth balance / advance / balance. General
    -- orders and Suits orders are numbered separately (see m_counters), so the
    -- same number can exist once in each. Numbers are generated, never typed.
    CREATE TABLE IF NOT EXISTS m_orders (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        order_type    TEXT NOT NULL DEFAULT 'general',
        order_number  INTEGER NOT NULL,
        customer_id   INTEGER NOT NULL REFERENCES m_customers(id) ON DELETE CASCADE,
        order_date    TEXT NOT NULL,
        trial_date    TEXT,
        delivery_date TEXT,
        total         REAL NOT NULL DEFAULT 0,
        cloth_balance REAL NOT NULL DEFAULT 0,
        advance       REAL NOT NULL DEFAULT 0,
        balance       REAL NOT NULL DEFAULT 0,
        payment_mode  TEXT,
        notes         TEXT,
        delivered_at  TEXT,
        created_at    TEXT DEFAULT ({IST_NOW}),
        updated_at    TEXT DEFAULT ({IST_NOW}),
        UNIQUE(order_type, order_number)
    );

    CREATE TABLE IF NOT EXISTS m_payments (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES m_orders(id) ON DELETE CASCADE,
        amount   REAL NOT NULL,
        mode     TEXT,
        note     TEXT,
        paid_at  TEXT DEFAULT ({IST_NOW})
    );

    -- Last-used stitching rate per garment, per order type, to pre-fill the next order.
    CREATE TABLE IF NOT EXISTS m_rates (
        order_type   TEXT NOT NULL,
        garment_type TEXT NOT NULL,
        rate         REAL NOT NULL,
        updated_at   TEXT DEFAULT ({IST_NOW}),
        PRIMARY KEY (order_type, garment_type)
    );

    -- Order-number sequences. A counter only ever goes up, so a deleted order's
    -- number is never handed out again.
    CREATE TABLE IF NOT EXISTS m_counters (
        name  TEXT PRIMARY KEY,
        value INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_m_orders_customer ON m_orders(customer_id);
    CREATE INDEX IF NOT EXISTS idx_m_orders_dates    ON m_orders(delivery_date, trial_date);
    CREATE INDEX IF NOT EXISTS idx_m_payments_order  ON m_payments(order_id);
"""

# Columns added to m_measurements after its first release (phases 1-3 databases
# already exist on disk, so these are applied as additive migrations).
_MEASUREMENT_MIGRATIONS = (
    ("order_id", "INTEGER REFERENCES m_orders(id) ON DELETE SET NULL"),
    ("qty",      "INTEGER NOT NULL DEFAULT 1"),
    ("rate",     "REAL NOT NULL DEFAULT 0"),
    ("amount",   "REAL NOT NULL DEFAULT 0"),
)


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
    existing = {r[1] for r in conn.execute("PRAGMA table_info(m_measurements)").fetchall()}
    for col, ddl in _MEASUREMENT_MIGRATIONS:
        if col not in existing:
            conn.execute(f"ALTER TABLE m_measurements ADD COLUMN {col} {ddl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_m_measurements_order ON m_measurements(order_id)")
    for name in ("order_general", "order_suit"):
        conn.execute("INSERT OR IGNORE INTO m_counters (name, value) VALUES (?, 0)", (name,))
    conn.commit()
    if own:
        conn.close()
