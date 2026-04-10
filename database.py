import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "billing.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT NOT NULL,
                mobile            TEXT NOT NULL,
                normalized_mobile TEXT NOT NULL UNIQUE,
                created_at        TEXT DEFAULT (datetime('now','localtime')),
                updated_at        TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS cloth_types (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                type_name       TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                is_default      INTEGER DEFAULT 0,
                has_company     INTEGER DEFAULT 1,
                created_at      TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS companies (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                cloth_type              TEXT NOT NULL,
                company_name            TEXT NOT NULL,
                normalized_company_name TEXT NOT NULL,
                is_default              INTEGER DEFAULT 0,
                created_at              TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(cloth_type, normalized_company_name)
            );

            CREATE TABLE IF NOT EXISTS salespersons (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                is_default      INTEGER DEFAULT 0,
                created_at      TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS bills (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_number              TEXT NOT NULL UNIQUE,
                customer_id              INTEGER REFERENCES customers(id),
                customer_name_snapshot   TEXT NOT NULL,
                customer_mobile_snapshot TEXT NOT NULL,
                bill_date                TEXT NOT NULL,
                subtotal                 REAL NOT NULL DEFAULT 0,
                total_discount           REAL NOT NULL DEFAULT 0,
                final_total              REAL NOT NULL DEFAULT 0,
                total_savings            REAL NOT NULL DEFAULT 0,
                advance_paid             REAL NOT NULL DEFAULT 0,
                remaining                REAL NOT NULL DEFAULT 0,
                salesperson_name         TEXT NOT NULL DEFAULT 'Self',
                payment_mode_type        TEXT NOT NULL,
                status                   TEXT NOT NULL DEFAULT 'active',
                created_at               TEXT DEFAULT (datetime('now','localtime')),
                updated_at               TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS bill_items (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id          INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
                cloth_type       TEXT NOT NULL,
                company_name     TEXT NOT NULL,
                quality_number   TEXT,
                quantity         REAL NOT NULL,
                unit_label       TEXT NOT NULL,
                mrp              REAL NOT NULL,
                line_total       REAL NOT NULL DEFAULT 0,
                discount_percent REAL NOT NULL DEFAULT 0,
                discount_amount  REAL NOT NULL DEFAULT 0,
                rate_after_disc  REAL NOT NULL DEFAULT 0,
                final_amount     REAL NOT NULL,
                created_at       TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS bill_payments (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id        INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
                payment_method TEXT NOT NULL,
                amount         REAL NOT NULL
            );
        """)
        # Migrate bills table: add advance_paid and remaining if missing
        try:
            conn.execute("ALTER TABLE bills ADD COLUMN advance_paid REAL NOT NULL DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE bills ADD COLUMN remaining REAL NOT NULL DEFAULT 0")
        except Exception:
            pass

        # Migrate existing databases: add rate_after_disc if missing
        existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(bill_items)").fetchall()]
        if "rate_after_disc" not in existing_cols:
            conn.execute("ALTER TABLE bill_items ADD COLUMN rate_after_disc REAL NOT NULL DEFAULT 0")
        # Migrate bills table: add status column if missing
        try:
            conn.execute("ALTER TABLE bills ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE bills ADD COLUMN salesperson_name TEXT NOT NULL DEFAULT 'Self'")
        except Exception:
            pass
        seed_cloth_types(conn)
        seed_companies(conn)
        seed_salespersons(conn)


def seed_cloth_types(conn):
    row = conn.execute("SELECT COUNT(*) as cnt FROM cloth_types").fetchone()
    if row["cnt"] > 0:
        return
    defaults = [
        ("Shirting",  "shirting",  1, 1),
        ("Suiting",   "suiting",   1, 1),
        ("Readymade", "readymade", 1, 1),
        ("Stitching", "stitching", 1, 0),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO cloth_types (type_name, normalized_name, is_default, has_company)
        VALUES (?, ?, ?, ?)
        """,
        defaults,
    )


def seed_companies(conn):
    row = conn.execute("SELECT COUNT(*) as cnt FROM companies").fetchone()
    if row["cnt"] > 0:
        return

    defaults = [
        ("Shirting",  "Monti"),
        ("Shirting",  "Raymonds"),
        ("Shirting",  "Arvind"),
        ("Suiting",   "Raymond"),
        ("Suiting",   "Siyarams"),
        ("Suiting",   "Mayur"),
        ("Suiting",   "Augustus"),
        ("Readymade", "Shubh"),
    ]

    conn.executemany(
        """
        INSERT OR IGNORE INTO companies
            (cloth_type, company_name, normalized_company_name, is_default)
        VALUES (?, ?, ?, 1)
        """,
        [(ct, name, name.strip().lower()) for ct, name in defaults],
    )


def seed_salespersons(conn):
    defaults = [
        ("Self", "self"),
        ("Geetesh", "geetesh"),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO salespersons (name, normalized_name, is_default)
        VALUES (?, ?, 1)
        """,
        defaults,
    )


def generate_bill_number(conn):
    row = conn.execute("SELECT MAX(bill_number) as max_bn FROM bills").fetchone()
    max_bn = row["max_bn"]
    if max_bn is None:
        return "SHN-0001"
    try:
        numeric = int(max_bn.split("-")[1])
    except (IndexError, ValueError):
        numeric = 0
    return f"SHN-{numeric + 1:04d}"
