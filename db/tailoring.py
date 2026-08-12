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
        cloth_balance REAL NOT NULL DEFAULT 0,
        notes         TEXT,
        delivered_at  TEXT,
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
        stitched_at  TEXT,
        notes        TEXT
    );

    CREATE TABLE IF NOT EXISTS tailoring_photos (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id   INTEGER NOT NULL REFERENCES tailoring_orders(id) ON DELETE CASCADE,
        item_id    INTEGER REFERENCES tailoring_items(id) ON DELETE SET NULL,
        filename   TEXT NOT NULL,
        created_at TEXT DEFAULT ({IST_NOW})
    );

    CREATE TABLE IF NOT EXISTS tailoring_payments (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES tailoring_orders(id) ON DELETE CASCADE,
        amount   REAL NOT NULL,
        mode     TEXT,
        note     TEXT,
        paid_at  TEXT DEFAULT ({IST_NOW})
    );

    CREATE INDEX IF NOT EXISTS idx_tailoring_items_order    ON tailoring_items(order_id);
    CREATE INDEX IF NOT EXISTS idx_tailoring_payments_order ON tailoring_payments(order_id);
    CREATE INDEX IF NOT EXISTS idx_tailoring_photos_order ON tailoring_photos(order_id);
    CREATE INDEX IF NOT EXISTS idx_tailoring_orders_dates ON tailoring_orders(delivery_date, trial_date);
"""


def init_tailoring_db(conn=None):
    """Create tables, applying migrations for columns added after first release."""
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
    # Migration: orders gained a separate balance for unpaid cloth cost,
    # distinct from the stitching total/advance/balance above
    order_cols = {r[1] for r in conn.execute("PRAGMA table_info(tailoring_orders)").fetchall()}
    if "cloth_balance" not in order_cols:
        conn.execute(
            "ALTER TABLE tailoring_orders ADD COLUMN cloth_balance REAL NOT NULL DEFAULT 0"
        )
    # Migration: orders gained a hand-over timestamp so the weekly report can
    # say *when* an order was delivered — item stages alone only say that it
    # was. Existing delivered orders are backfilled from updated_at, which is
    # bumped on every stage change, so it is the closest record we have. This
    # runs once, right after the column appears, so a later un-delivery (stage
    # rolled back) is not re-stamped on the next startup.
    if "delivered_at" not in order_cols:
        conn.execute("ALTER TABLE tailoring_orders ADD COLUMN delivered_at TEXT")
        conn.execute("""
            UPDATE tailoring_orders SET delivered_at = updated_at
            WHERE EXISTS (SELECT 1 FROM tailoring_items
                          WHERE order_id = tailoring_orders.id)
              AND NOT EXISTS (SELECT 1 FROM tailoring_items
                              WHERE order_id = tailoring_orders.id
                                AND stage != 'Delivered')
        """)
    # Migration: each garment gained the date its own stitching finished, so the
    # weekly report can count the pieces that came off the machine that week
    # rather than waiting for the rest of their order.
    #
    # Garments already finished when the column appears are backfilled, because
    # leaving them NULL is worse than an approximate date: the stamp is applied
    # by stage, so the next unrelated edit to an old delivered order would date
    # months-old work into the current week. Best guess in order — the hand-over
    # timestamp, else the promised delivery date (roughly when it came off the
    # machine, and unlike updated_at not bumped by later payments and edits),
    # else updated_at. Runs once, so a later roll-back is not re-stamped.
    item_cols = {r[1] for r in conn.execute("PRAGMA table_info(tailoring_items)").fetchall()}
    if "stitched_at" not in item_cols:
        conn.execute("ALTER TABLE tailoring_items ADD COLUMN stitched_at TEXT")
        conn.execute("""
            UPDATE tailoring_items SET stitched_at = (
                SELECT COALESCE(o.delivered_at, o.delivery_date, o.updated_at)
                FROM tailoring_orders o WHERE o.id = tailoring_items.order_id)
            WHERE stage IN ('Full Stitched', 'Delivered')
        """)
    # The stitching date briefly lived on the order before moving to the garment
    # above. Drop the leftover so nothing reads a column that no longer syncs.
    if "stitched_at" in order_cols:
        conn.execute("ALTER TABLE tailoring_orders DROP COLUMN stitched_at")
    conn.commit()
    if own:
        conn.close()
