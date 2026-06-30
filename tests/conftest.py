import sqlite3
import pytest


@pytest.fixture
def db():
    """In-memory SQLite DB with the minimal schema needed by service tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE cloth_types (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            type_name       TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            is_default      INTEGER DEFAULT 0,
            has_company     INTEGER DEFAULT 1
        );

        CREATE TABLE customers (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              TEXT NOT NULL,
            mobile            TEXT NOT NULL,
            normalized_mobile TEXT NOT NULL UNIQUE,
            created_at        TEXT,
            updated_at        TEXT
        );

        CREATE TABLE bills (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_number              TEXT NOT NULL UNIQUE,
            customer_id              INTEGER,
            customer_name_snapshot   TEXT NOT NULL DEFAULT '',
            customer_mobile_snapshot TEXT NOT NULL DEFAULT '',
            bill_date                TEXT NOT NULL DEFAULT '',
            subtotal                 REAL NOT NULL DEFAULT 0,
            total_discount           REAL NOT NULL DEFAULT 0,
            final_total              REAL NOT NULL DEFAULT 0,
            total_savings            REAL NOT NULL DEFAULT 0,
            round_off                REAL NOT NULL DEFAULT 0,
            advance_paid             REAL NOT NULL DEFAULT 0,
            remaining                REAL NOT NULL DEFAULT 0,
            salesperson_name         TEXT NOT NULL DEFAULT 'Self',
            payment_mode_type        TEXT NOT NULL DEFAULT 'Cash',
            status                   TEXT NOT NULL DEFAULT 'active',
            created_at               TEXT,
            updated_at               TEXT
        );

        CREATE TABLE bill_items (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id           INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
            cloth_type        TEXT NOT NULL,
            company_name      TEXT NOT NULL,
            quality_number    TEXT,
            quantity          REAL NOT NULL,
            unit_label        TEXT NOT NULL,
            mrp               REAL NOT NULL,
            line_total        REAL NOT NULL DEFAULT 0,
            discount_percent  REAL NOT NULL DEFAULT 0,
            discount_amount   REAL NOT NULL DEFAULT 0,
            rate_after_disc   REAL NOT NULL DEFAULT 0,
            final_amount      REAL NOT NULL,
            inventory_item_id INTEGER
        );
    """)
    conn.executemany(
        "INSERT INTO cloth_types (type_name, normalized_name) VALUES (?, ?)",
        [
            ("Shirting",  "shirting"),
            ("Suiting",   "suiting"),
            ("Readymade", "readymade"),
            ("Stitching", "stitching"),
        ],
    )
    conn.commit()
    yield conn
    conn.close()
