from db.connection import _open_connection, _current_fy
from utils import cloth_type_prefix as _cloth_prefix


# ----------------------------------------------------------------
# schema_version helpers
# ----------------------------------------------------------------

def _ensure_schema_version_table(conn):
    """Create schema_version if it doesn't exist. Returns True if just created."""
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if exists:
        return False
    conn.execute("""
        CREATE TABLE schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    return True


def _applied_versions(conn):
    return {row[0] for row in conn.execute("SELECT version FROM schema_version").fetchall()}


def _mark_applied(conn, version):
    conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (version,))


# ----------------------------------------------------------------
# Migrations
# ----------------------------------------------------------------

def _m01_baseline_schema(conn):
    """Full schema as of the initial release — all tables with all current columns."""
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
            round_off                REAL NOT NULL DEFAULT 0,
            advance_paid             REAL NOT NULL DEFAULT 0,
            remaining                REAL NOT NULL DEFAULT 0,
            salesperson_name         TEXT NOT NULL DEFAULT 'Self',
            payment_mode_type        TEXT NOT NULL,
            status                   TEXT NOT NULL DEFAULT 'active',
            created_at               TEXT DEFAULT (datetime('now','localtime')),
            updated_at               TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS bill_items (
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
            inventory_item_id INTEGER REFERENCES inventory_items(id),
            created_at        TEXT DEFAULT (datetime('now','localtime'))
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
            next_val INTEGER NOT NULL DEFAULT 0,
            fy       TEXT    NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS suppliers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS inventory_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cloth_type      TEXT NOT NULL,
            company_name    TEXT NOT NULL,
            quality_number  TEXT NOT NULL DEFAULT '',
            unit_label      TEXT NOT NULL DEFAULT 'm',
            current_stock   REAL NOT NULL DEFAULT 0,
            min_stock_alert REAL NOT NULL DEFAULT 5,
            mrp             REAL NOT NULL DEFAULT 0,
            notes           TEXT,
            item_code       TEXT UNIQUE,
            supplier_id     INTEGER REFERENCES suppliers(id),
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            updated_at      TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(cloth_type, company_name, quality_number)
        );

        CREATE TABLE IF NOT EXISTS inventory_transactions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id        INTEGER NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
            txn_type       TEXT NOT NULL,
            quantity       REAL NOT NULL,
            reference_type TEXT,
            reference_id   INTEGER,
            notes          TEXT,
            created_by     TEXT,
            created_at     TEXT DEFAULT (datetime('now','localtime'))
        );
    """)


def _m02_bills_extra_columns(conn):
    """Add columns that were introduced after the initial release."""
    bills_cols = {row[1] for row in conn.execute("PRAGMA table_info(bills)").fetchall()}
    for col, defn in [
        ("advance_paid",     "REAL NOT NULL DEFAULT 0"),
        ("remaining",        "REAL NOT NULL DEFAULT 0"),
        ("status",           "TEXT NOT NULL DEFAULT 'active'"),
        ("salesperson_name", "TEXT NOT NULL DEFAULT 'Self'"),
        ("round_off",        "REAL NOT NULL DEFAULT 0"),
    ]:
        if col not in bills_cols:
            conn.execute(f"ALTER TABLE bills ADD COLUMN {col} {defn}")


def _m03_bill_items_rate_after_disc(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(bill_items)").fetchall()}
    if "rate_after_disc" not in existing:
        conn.execute("ALTER TABLE bill_items ADD COLUMN rate_after_disc REAL NOT NULL DEFAULT 0")


def _m04_bill_items_inventory_item_id(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(bill_items)").fetchall()}
    if "inventory_item_id" not in existing:
        conn.execute(
            "ALTER TABLE bill_items ADD COLUMN inventory_item_id INTEGER REFERENCES inventory_items(id)"
        )


def _m05_inventory_item_code(conn):
    inv_cols = {row[1] for row in conn.execute("PRAGMA table_info(inventory_items)").fetchall()}
    if "item_code" not in inv_cols:
        conn.execute("ALTER TABLE inventory_items ADD COLUMN item_code TEXT")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_item_code ON inventory_items(item_code)"
        )
        items = conn.execute("SELECT id, cloth_type FROM inventory_items ORDER BY id").fetchall()
        counters = {}
        for item in items:
            prefix = _cloth_prefix(item[1])
            counters[prefix] = counters.get(prefix, 0) + 1
            code = f"{prefix}-{counters[prefix]:03d}"
            conn.execute("UPDATE inventory_items SET item_code = ? WHERE id = ?", (code, item[0]))


def _m06_inventory_supplier_id(conn):
    inv_cols = {row[1] for row in conn.execute("PRAGMA table_info(inventory_items)").fetchall()}
    if "supplier_id" not in inv_cols:
        conn.execute(
            "ALTER TABLE inventory_items ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id)"
        )


def _m07_cloth_type_gift_accessories(conn):
    for type_name, normalized_name in [("Gift Sets", "gift sets"), ("Accessories", "accessories")]:
        conn.execute(
            "INSERT OR IGNORE INTO cloth_types (type_name, normalized_name, is_default, has_company)"
            " VALUES (?, ?, 1, 1)",
            (type_name, normalized_name),
        )


def _m08_bill_number_seq_fy(conn):
    seq_cols = {row[1] for row in conn.execute("PRAGMA table_info(bill_number_seq)").fetchall()}
    if "fy" not in seq_cols:
        conn.execute("ALTER TABLE bill_number_seq ADD COLUMN fy TEXT NOT NULL DEFAULT ''")


def _m09_seed_defaults(conn):
    _seed_cloth_types(conn)
    _seed_companies(conn)
    _seed_salespersons(conn)


def _m10_stitching_company_dropdown(conn):
    conn.execute("UPDATE cloth_types SET has_company = 1 WHERE normalized_name = 'stitching'")


def _m11_stitching_garment_types(conn):
    conn.executemany(
        "INSERT OR IGNORE INTO companies"
        " (cloth_type, company_name, normalized_company_name, is_default) VALUES (?, ?, ?, 1)",
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


MIGRATIONS = [
    (1,  _m01_baseline_schema),
    (2,  _m02_bills_extra_columns),
    (3,  _m03_bill_items_rate_after_disc),
    (4,  _m04_bill_items_inventory_item_id),
    (5,  _m05_inventory_item_code),
    (6,  _m06_inventory_supplier_id),
    (7,  _m07_cloth_type_gift_accessories),
    (8,  _m08_bill_number_seq_fy),
    (9,  _m09_seed_defaults),
    (10, _m10_stitching_company_dropdown),
    (11, _m11_stitching_garment_types),
]


# ----------------------------------------------------------------
# Startup sync — runs every boot, always idempotent
# ----------------------------------------------------------------

def _sync_bill_number_seq(conn):
    """Ensure the sequence row exists for the current FY and is ahead of the max bill number."""
    fy = _current_fy()
    conn.execute(
        "INSERT OR IGNORE INTO bill_number_seq (id, next_val, fy) VALUES (1, 0, ?)", (fy,)
    )
    conn.execute("UPDATE bill_number_seq SET fy = ? WHERE id = 1 AND fy = ''", (fy,))
    conn.execute(
        "UPDATE bill_number_seq SET next_val = MAX(next_val, "
        "(SELECT COALESCE(MAX(CAST(SUBSTR(bill_number, 5) AS INTEGER)), 0) "
        "FROM bills WHERE bill_number LIKE ?)) "
        "WHERE id = 1",
        (f"SHN-%/{fy}",),
    )


# ----------------------------------------------------------------
# init_db — called once at app startup
# ----------------------------------------------------------------

def init_db():
    conn = _open_connection()
    try:
        is_new = _ensure_schema_version_table(conn)

        if is_new:
            # First time running with the migration system on an existing database:
            # stamp all migrations as applied without re-running them.
            bills_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='bills'"
            ).fetchone()
            if bills_exists:
                for version, _ in MIGRATIONS:
                    _mark_applied(conn, version)
                _sync_bill_number_seq(conn)
                conn.commit()
                return

        applied = _applied_versions(conn)
        for version, fn in MIGRATIONS:
            if version not in applied:
                fn(conn)
                _mark_applied(conn, version)

        _sync_bill_number_seq(conn)
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------
# Seed helpers (called by _m09_seed_defaults)
# ----------------------------------------------------------------

def _seed_cloth_types(conn):
    if conn.execute("SELECT COUNT(*) as cnt FROM cloth_types").fetchone()["cnt"] > 0:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO cloth_types (type_name, normalized_name, is_default, has_company)"
        " VALUES (?, ?, ?, ?)",
        [
            ("Shirting",    "shirting",    1, 1),
            ("Suiting",     "suiting",     1, 1),
            ("Readymade",   "readymade",   1, 1),
            ("Stitching",   "stitching",   1, 1),
            ("Gift Sets",   "gift sets",   1, 1),
            ("Accessories", "accessories", 1, 1),
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
        "INSERT OR IGNORE INTO companies"
        " (cloth_type, company_name, normalized_company_name, is_default) VALUES (?, ?, ?, 1)",
        [(ct, name, name.strip().lower()) for ct, name in defaults],
    )


def _seed_salespersons(conn):
    conn.executemany(
        "INSERT OR IGNORE INTO salespersons (name, normalized_name, is_default) VALUES (?, ?, 1)",
        [("Self", "self"), ("Geetesh", "geetesh")],
    )
