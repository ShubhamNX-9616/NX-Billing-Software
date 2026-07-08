from datetime import date, timedelta

import pytest

from services.loyalty import (
    TIERS,
    get_tier_for_amount,
    is_loyalty_enabled,
    set_loyalty_enabled,
    get_activation_date,
    set_activation_date,
    get_current_cycle,
    get_cycle_spent,
    check_and_unlock_gifts,
    _add_years,
    _create_cycle,
)

TODAY = date.today()


@pytest.fixture
def ldb(db):
    """Extends the shared in-memory DB with the loyalty tables (final schema,
    matching migrations 21-25)."""
    db.executescript("""
        CREATE TABLE loyalty_settings (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            enabled         INTEGER NOT NULL DEFAULT 1,
            activation_date TEXT
        );

        CREATE TABLE loyalty_cycles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_number INTEGER NOT NULL,
            start_date   TEXT NOT NULL,
            end_date     TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE UNIQUE INDEX idx_loyalty_cycles_number ON loyalty_cycles(cycle_number);
        CREATE UNIQUE INDEX idx_loyalty_cycles_start  ON loyalty_cycles(start_date);

        CREATE TABLE loyalty_gifts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            tier        TEXT    NOT NULL,
            cycle_id    INTEGER REFERENCES loyalty_cycles(id),
            bill_id     INTEGER REFERENCES bills(id),
            given_at    TEXT,
            given_by    TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(customer_id, tier, cycle_id)
        );
    """)
    db.execute("INSERT INTO loyalty_settings (id, enabled) VALUES (1, 1)")
    db.commit()
    return db


@pytest.fixture
def customer_id(ldb):
    cur = ldb.execute(
        "INSERT INTO customers (name, mobile, normalized_mobile) VALUES (?, ?, ?)",
        ("Test Customer", "9876543210", "9876543210"),
    )
    return cur.lastrowid


_bill_seq = iter(range(1, 10_000))


def add_bill(db, customer_id, final_total, bill_date=None, status="active"):
    n = next(_bill_seq)
    cur = db.execute(
        """INSERT INTO bills (bill_number, customer_id, bill_date, final_total, status)
           VALUES (?, ?, ?, ?, ?)""",
        (f"SHN-{n:04d}/T", customer_id, (bill_date or TODAY).isoformat(), final_total, status),
    )
    return cur.lastrowid


def activate(db, start):
    db.execute(
        "UPDATE loyalty_settings SET activation_date = ? WHERE id = 1",
        (start.isoformat(),),
    )


# ----------------------------------------------------------------
# Tier thresholds
# ----------------------------------------------------------------
def test_tier_for_amount_below_first_threshold():
    assert get_tier_for_amount(0) is None
    assert get_tier_for_amount(9_999.99) is None


def test_tier_for_amount_exact_and_between_thresholds():
    assert get_tier_for_amount(10_000) == "silver"
    assert get_tier_for_amount(19_999) == "silver"
    assert get_tier_for_amount(20_000) == "gold"
    assert get_tier_for_amount(35_000) == "platinum"
    assert get_tier_for_amount(50_000) == "diamond"
    assert get_tier_for_amount(1_000_000) == "diamond"


# ----------------------------------------------------------------
# Enabled flag
# ----------------------------------------------------------------
def test_toggle_enabled(ldb):
    assert is_loyalty_enabled(ldb) is True
    set_loyalty_enabled(ldb, False)
    assert is_loyalty_enabled(ldb) is False
    set_loyalty_enabled(ldb, True)
    assert is_loyalty_enabled(ldb) is True


# ----------------------------------------------------------------
# Cycle creation and rollover
# ----------------------------------------------------------------
def test_no_cycle_without_activation_date(ldb):
    assert get_current_cycle(ldb) is None


def test_no_cycle_before_future_activation_date(ldb):
    activate(ldb, TODAY + timedelta(days=30))
    assert get_current_cycle(ldb) is None


def test_first_cycle_created_on_activation(ldb):
    start = TODAY - timedelta(days=10)
    activate(ldb, start)
    cycle = get_current_cycle(ldb)
    assert cycle["cycle_number"] == 1
    assert cycle["start_date"] == start.isoformat()
    assert cycle["end_date"] == _add_years(start, 1).isoformat()


def test_current_cycle_is_reused_not_duplicated(ldb):
    activate(ldb, TODAY - timedelta(days=10))
    first = get_current_cycle(ldb)
    second = get_current_cycle(ldb)
    assert first["id"] == second["id"]
    count = ldb.execute("SELECT COUNT(*) FROM loyalty_cycles").fetchone()[0]
    assert count == 1


def test_cycle_rolls_over_contiguously(ldb):
    start = TODAY - timedelta(days=400)  # cycle 1 has already ended
    activate(ldb, start)
    end1 = _add_years(start, 1)
    cycle = get_current_cycle(ldb)  # creates cycle 1, sees it ended, creates cycle 2
    assert cycle["cycle_number"] == 2
    assert cycle["start_date"] == end1.isoformat()


def test_between_cycles_with_future_activation(ldb):
    start = TODAY - timedelta(days=400)
    activate(ldb, start)
    get_current_cycle(ldb, today=start)  # materialize cycle 1 only
    activate(ldb, TODAY + timedelta(days=30))  # admin pushed next cycle out
    assert get_current_cycle(ldb) is None


def test_add_years_handles_feb_29():
    assert _add_years(date(2024, 2, 29), 1) == date(2025, 2, 28)
    assert _add_years(date(2024, 3, 1), 1) == date(2025, 3, 1)


def test_create_cycle_race_returns_existing_row(ldb):
    start = TODAY - timedelta(days=10)
    first = _create_cycle(ldb, 1, start)
    # Same start again (as if a concurrent request won the insert race)
    second = _create_cycle(ldb, 1, start)
    assert second["id"] == first["id"]
    count = ldb.execute("SELECT COUNT(*) FROM loyalty_cycles").fetchone()[0]
    assert count == 1


# ----------------------------------------------------------------
# Activation date validation
# ----------------------------------------------------------------
def test_set_activation_date_rejects_garbage(ldb):
    with pytest.raises(ValueError):
        set_activation_date(ldb, "not-a-date")
    with pytest.raises(ValueError):
        set_activation_date(ldb, None)


def test_set_activation_date_before_program_starts(ldb):
    start = TODAY + timedelta(days=5)
    set_activation_date(ldb, start.isoformat())
    assert get_activation_date(ldb) == start.isoformat()


def test_set_activation_date_rejects_date_inside_running_cycle(ldb):
    activate(ldb, TODAY - timedelta(days=10))
    get_current_cycle(ldb)  # materialize the running cycle
    with pytest.raises(ValueError):
        set_activation_date(ldb, TODAY.isoformat())


def test_set_activation_date_rejects_overlap_with_ended_cycle(ldb):
    """Even between cycles, a new activation date must not fall inside an
    already-ended cycle, or bills in the overlap would count twice."""
    start = TODAY - timedelta(days=400)
    activate(ldb, start)
    get_current_cycle(ldb, today=start)  # materialize cycle 1 only
    activate(ldb, TODAY + timedelta(days=60))  # now between cycles

    inside_old_cycle = start + timedelta(days=100)
    with pytest.raises(ValueError):
        set_activation_date(ldb, inside_old_cycle.isoformat())


def test_set_activation_date_allows_on_or_after_latest_cycle_end(ldb):
    start = TODAY - timedelta(days=10)
    activate(ldb, start)
    cycle = get_current_cycle(ldb)
    set_activation_date(ldb, cycle["end_date"])  # exactly at end — allowed
    assert get_activation_date(ldb) == cycle["end_date"]


# ----------------------------------------------------------------
# Cycle spend
# ----------------------------------------------------------------
def test_cycle_spent_counts_only_active_bills_in_window(ldb, customer_id):
    activate(ldb, TODAY - timedelta(days=10))
    cycle = get_current_cycle(ldb)

    add_bill(ldb, customer_id, 5_000)
    add_bill(ldb, customer_id, 3_000, status="cancelled")            # excluded
    add_bill(ldb, customer_id, 2_000, bill_date=TODAY - timedelta(days=100))  # before cycle

    assert get_cycle_spent(ldb, customer_id, cycle) == 5_000


# ----------------------------------------------------------------
# Gift unlocking
# ----------------------------------------------------------------
def test_no_gifts_below_first_threshold(ldb, customer_id):
    activate(ldb, TODAY - timedelta(days=10))
    bill = add_bill(ldb, customer_id, 9_999)
    assert check_and_unlock_gifts(ldb, customer_id, bill) == []


def test_gift_unlocked_at_threshold(ldb, customer_id):
    activate(ldb, TODAY - timedelta(days=10))
    bill = add_bill(ldb, customer_id, 10_000)
    assert check_and_unlock_gifts(ldb, customer_id, bill) == ["silver"]


def test_big_bill_unlocks_multiple_tiers_at_once(ldb, customer_id):
    activate(ldb, TODAY - timedelta(days=10))
    bill = add_bill(ldb, customer_id, 55_000)
    assert check_and_unlock_gifts(ldb, customer_id, bill) == [
        "silver", "gold", "platinum", "diamond",
    ]


def test_gift_not_unlocked_twice(ldb, customer_id):
    activate(ldb, TODAY - timedelta(days=10))
    bill1 = add_bill(ldb, customer_id, 12_000)
    assert check_and_unlock_gifts(ldb, customer_id, bill1) == ["silver"]
    bill2 = add_bill(ldb, customer_id, 1_000)
    assert check_and_unlock_gifts(ldb, customer_id, bill2) == []


def test_no_gifts_while_paused_then_catch_up_on_resume(ldb, customer_id):
    activate(ldb, TODAY - timedelta(days=10))
    set_loyalty_enabled(ldb, False)
    bill1 = add_bill(ldb, customer_id, 15_000)
    assert check_and_unlock_gifts(ldb, customer_id, bill1) == []

    set_loyalty_enabled(ldb, True)
    bill2 = add_bill(ldb, customer_id, 6_000)  # total 21k → silver + gold
    assert check_and_unlock_gifts(ldb, customer_id, bill2) == ["silver", "gold"]


def test_no_gifts_without_active_cycle(ldb, customer_id):
    bill = add_bill(ldb, customer_id, 60_000)
    assert check_and_unlock_gifts(ldb, customer_id, bill) == []
    assert ldb.execute("SELECT COUNT(*) FROM loyalty_gifts").fetchone()[0] == 0
