"""Standalone database module for the Tailoring Delivery System.

Deliberately independent from billing.db — tailoring data lives in its own
SQLite file (tailoring.db) with its own connection, schema and order-number
sequence, so the two systems never mix.
"""
import sqlite3
import os
from flask import g, has_app_context

TAILORING_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "tailoring.db")

IST_NOW = "datetime('now', '+5 hours', '+30 minutes')"

# Stitching stages in workflow order
STAGES = ["In Stitching", "Trial Ready", "Full Stitched", "Delivered"]

# Pre-printed garment list from the paper receipt book
GARMENT_TYPES = [
    "Trouser", "Shirt", "Kurta", "Payjama", "Safari",
    "Blazer", "Jacket", "West Coat", "Jodhpuri", "Sherwani",
]

# Order numbers continue the paper book series from here
ORDER_SEQ_START = 1001


def _open_connection():
    conn = sqlite3.connect(TAILORING_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_tailoring_db():
    """Return the per-request tailoring DB connection, cached in Flask g.
    Outside a request context (startup scripts) returns a plain connection."""
    if has_app_context():
        if 'tailoring_db' not in g:
            g.tailoring_db = _open_connection()
        return g.tailoring_db
    return _open_connection()


def close_tailoring_db(e=None):
    """Close the per-request connection. Register with app.teardown_appcontext."""
    db = g.pop('tailoring_db', None)
    if db is not None:
        db.close()


SCHEMA = f"""
    CREATE TABLE IF NOT EXISTS tailoring_orders (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number  INTEGER NOT NULL UNIQUE,
        order_date    TEXT NOT NULL,
        customer_name TEXT NOT NULL,
        mobile        TEXT,
        address       TEXT,
        trial_date    TEXT,
        delivery_date TEXT,
        total         REAL NOT NULL DEFAULT 0,
        advance       REAL NOT NULL DEFAULT 0,
        balance       REAL NOT NULL DEFAULT 0,
        payment_mode  TEXT,
        notes         TEXT,
        created_at    TEXT DEFAULT ({IST_NOW}),
        updated_at    TEXT DEFAULT ({IST_NOW})
    );

    CREATE TABLE IF NOT EXISTS tailoring_items (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id     INTEGER NOT NULL REFERENCES tailoring_orders(id) ON DELETE CASCADE,
        garment_type TEXT NOT NULL,
        qty          INTEGER NOT NULL DEFAULT 1,
        rate         REAL NOT NULL DEFAULT 0,
        amount       REAL NOT NULL DEFAULT 0,
        stage        TEXT NOT NULL DEFAULT 'In Stitching',
        notes        TEXT
    );

    CREATE TABLE IF NOT EXISTS tailoring_photos (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id   INTEGER NOT NULL REFERENCES tailoring_orders(id) ON DELETE CASCADE,
        item_id    INTEGER REFERENCES tailoring_items(id) ON DELETE SET NULL,
        filename   TEXT NOT NULL,
        created_at TEXT DEFAULT ({IST_NOW})
    );

    CREATE TABLE IF NOT EXISTS tailoring_order_seq (
        id       INTEGER PRIMARY KEY CHECK (id = 1),
        next_val INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_tailoring_items_order  ON tailoring_items(order_id);
    CREATE INDEX IF NOT EXISTS idx_tailoring_photos_order ON tailoring_photos(order_id);
    CREATE INDEX IF NOT EXISTS idx_tailoring_orders_dates ON tailoring_orders(delivery_date, trial_date);
"""


def init_tailoring_db(conn=None):
    """Create tables and seed the order-number sequence."""
    own = conn is None
    if own:
        conn = _open_connection()
    conn.executescript(SCHEMA)
    # Migration: photos gained an optional per-item link
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tailoring_photos)").fetchall()}
    if "item_id" not in cols:
        conn.execute(
            "ALTER TABLE tailoring_photos ADD COLUMN item_id INTEGER "
            "REFERENCES tailoring_items(id) ON DELETE SET NULL"
        )
    row = conn.execute("SELECT next_val FROM tailoring_order_seq WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO tailoring_order_seq (id, next_val) VALUES (1, ?)",
            (ORDER_SEQ_START,),
        )
    conn.commit()
    if own:
        conn.close()


def next_order_number(conn):
    """Reserve and return the next order number (1001, 1002, ...)."""
    row = conn.execute("SELECT next_val FROM tailoring_order_seq WHERE id = 1").fetchone()
    val = row["next_val"] if row else ORDER_SEQ_START
    conn.execute(
        "INSERT OR REPLACE INTO tailoring_order_seq (id, next_val) VALUES (1, ?)",
        (val + 1,),
    )
    return val
