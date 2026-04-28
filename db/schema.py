from db.connection import _open_connection


def init_db():
    conn = _open_connection()
    try:
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

            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'staff',
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT DEFAULT (datetime('now','localtime')),
                updated_at    TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS bill_number_seq (
                id       INTEGER PRIMARY KEY CHECK (id = 1),
                next_val INTEGER NOT NULL DEFAULT 0
            );
        """)

        # Column migrations — idempotent, safe on every startup
        for stmt in [
            "ALTER TABLE bills ADD COLUMN advance_paid REAL NOT NULL DEFAULT 0",
            "ALTER TABLE bills ADD COLUMN remaining REAL NOT NULL DEFAULT 0",
            "ALTER TABLE bills ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "ALTER TABLE bills ADD COLUMN salesperson_name TEXT NOT NULL DEFAULT 'Self'",
        ]:
            try:
                conn.execute(stmt)
            except Exception:
                pass

        existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(bill_items)").fetchall()]
        if "rate_after_disc" not in existing_cols:
            conn.execute("ALTER TABLE bill_items ADD COLUMN rate_after_disc REAL NOT NULL DEFAULT 0")

        # Sync sequence table to current max bill number
        conn.execute("INSERT OR IGNORE INTO bill_number_seq (id, next_val) VALUES (1, 0)")
        conn.execute(
            "UPDATE bill_number_seq SET next_val = MAX(next_val, "
            "(SELECT COALESCE(MAX(CAST(SUBSTR(bill_number, 5) AS INTEGER)), 0) FROM bills)) "
            "WHERE id = 1"
        )

        _seed_cloth_types(conn)
        _seed_companies(conn)
        _seed_salespersons(conn)

        # Migrate: enable company dropdown for Stitching
        conn.execute(
            "UPDATE cloth_types SET has_company = 1 WHERE normalized_name = 'stitching'"
        )

        # Migrate: add Stitching garment types if missing
        conn.executemany(
            """
            INSERT OR IGNORE INTO companies
                (cloth_type, company_name, normalized_company_name, is_default)
            VALUES (?, ?, ?, 1)
            """,
            [
                ("Stitching", "Pant",   "pant"),
                ("Stitching", "Shirt",  "shirt"),
                ("Stitching", "Suit",   "suit"),
                ("Stitching", "Blazer", "blazer"),
                ("Stitching", "Kurta",  "kurta"),
                ("Stitching", "Pyjama", "pyjama"),
                ("Stitching", "Jacket", "jacket"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def _seed_cloth_types(conn):
    if conn.execute("SELECT COUNT(*) as cnt FROM cloth_types").fetchone()["cnt"] > 0:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO cloth_types (type_name, normalized_name, is_default, has_company) VALUES (?, ?, ?, ?)",
        [
            ("Shirting",  "shirting",  1, 1),
            ("Suiting",   "suiting",   1, 1),
            ("Readymade", "readymade", 1, 1),
            ("Stitching", "stitching", 1, 1),
        ],
    )


def _seed_companies(conn):
    if conn.execute("SELECT COUNT(*) as cnt FROM companies").fetchone()["cnt"] > 0:
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
        ("Stitching", "Pant"),
        ("Stitching", "Shirt"),
        ("Stitching", "Suit"),
        ("Stitching", "Blazer"),
        ("Stitching", "Kurta"),
        ("Stitching", "Pyjama"),
        ("Stitching", "Jacket"),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO companies (cloth_type, company_name, normalized_company_name, is_default) VALUES (?, ?, ?, 1)",
        [(ct, name, name.strip().lower()) for ct, name in defaults],
    )


def _seed_salespersons(conn):
    conn.executemany(
        "INSERT OR IGNORE INTO salespersons (name, normalized_name, is_default) VALUES (?, ?, 1)",
        [("Self", "self"), ("Geetesh", "geetesh")],
    )
