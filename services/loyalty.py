import sqlite3
from datetime import date

TIERS = [
    ('silver',   10_000),
    ('gold',     20_000),
    ('platinum', 30_000),
    ('diamond',  50_000),
]


def get_tier_for_amount(spent):
    """Return the highest tier name reached for a given spend, or None."""
    tier = None
    for name, threshold in TIERS:
        if spent >= threshold:
            tier = name
    return tier


def is_loyalty_enabled(db):
    row = db.execute("SELECT enabled FROM loyalty_settings WHERE id = 1").fetchone()
    return bool(row["enabled"]) if row else True


def set_loyalty_enabled(db, enabled):
    db.execute("UPDATE loyalty_settings SET enabled = ? WHERE id = 1", (1 if enabled else 0,))


def get_activation_date(db):
    """Date (ISO string) that seeds the next loyalty cycle. Editing this only
    affects a cycle that hasn't started yet — see get_current_cycle."""
    row = db.execute("SELECT activation_date FROM loyalty_settings WHERE id = 1").fetchone()
    return row["activation_date"] if row else None


def set_activation_date(db, activation_date_str):
    """Set/update the activation date. Raises ValueError if the new date
    would land inside (or before) any cycle already recorded in
    loyalty_cycles — running or ended. Cycle rows are frozen once created,
    and a new cycle must never overlap an old one, or bills in the overlap
    would count toward both cycles and unlock duplicate gifts."""
    try:
        new_date = date.fromisoformat(activation_date_str)
    except (TypeError, ValueError):
        raise ValueError("Activation date must be a valid date (YYYY-MM-DD)")

    # Materialize the cycle that should currently be running (if any) so the
    # validation below always sees it.
    get_current_cycle(db)

    latest = db.execute(
        "SELECT * FROM loyalty_cycles ORDER BY start_date DESC LIMIT 1"
    ).fetchone()
    if latest is not None:
        end_date = date.fromisoformat(latest["end_date"])
        if new_date < end_date:
            raise ValueError(
                f"Activation date must be on or after the latest cycle's "
                f"end date ({latest['end_date']}) - it can only shift future cycles"
            )

    db.execute(
        "UPDATE loyalty_settings SET activation_date = ? WHERE id = 1",
        (new_date.isoformat(),),
    )


def _add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # source date was Feb 29 and target year isn't a leap year
        return d.replace(month=2, day=28, year=d.year + years)


def _create_cycle(db, cycle_number, start):
    end = _add_years(start, 1)
    try:
        cur = db.execute(
            "INSERT INTO loyalty_cycles (cycle_number, start_date, end_date) VALUES (?, ?, ?)",
            (cycle_number, start.isoformat(), end.isoformat()),
        )
    except sqlite3.IntegrityError:
        # A concurrent request created this cycle first — use its row.
        row = db.execute(
            "SELECT * FROM loyalty_cycles WHERE start_date = ?", (start.isoformat(),)
        ).fetchone()
        if row is None:
            raise
        return dict(row)
    # Keep activation_date in sync with the cycle actually running so that,
    # if the admin never edits it again, the next rollover stays contiguous.
    db.execute(
        "UPDATE loyalty_settings SET activation_date = ? WHERE id = 1",
        (start.isoformat(),),
    )
    row = db.execute("SELECT * FROM loyalty_cycles WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_current_cycle(db, today=None):
    """Return the currently running loyalty cycle as a dict, or None if the
    program hasn't started yet (no activation date reached) or is between
    cycles waiting on a future admin-set activation date.

    May insert a new loyalty_cycles row as a side effect when a cycle
    rolls over or starts for the first time — callers must db.commit()."""
    today = today or date.today()

    latest = db.execute(
        "SELECT * FROM loyalty_cycles ORDER BY start_date DESC LIMIT 1"
    ).fetchone()

    if latest is None:
        activation_date = get_activation_date(db)
        if not activation_date:
            return None
        start = date.fromisoformat(activation_date)
        if start > today:
            return None
        latest = _create_cycle(db, 1, start)
    else:
        latest = dict(latest)

    # Roll forward until the latest cycle covers today. A loop (not a single
    # step) because more than one full cycle may have elapsed since the last
    # request — e.g. a backdated activation date or a long idle period.
    while True:
        end_date = date.fromisoformat(latest["end_date"])
        if today < end_date:
            return latest

        # Latest cycle has ended — figure out when the next one starts.
        start_date = date.fromisoformat(latest["start_date"])
        next_start = end_date
        activation_date = get_activation_date(db)
        if activation_date:
            candidate = date.fromisoformat(activation_date)
            if candidate > start_date:
                next_start = candidate

        if next_start > today:
            return None

        latest = _create_cycle(db, latest["cycle_number"] + 1, next_start)


def get_cycle_spent(db, customer_id, cycle):
    """Sum of final_total for active bills belonging to customer within the
    given cycle's [start_date, end_date) window, keyed off bill_date."""
    row = db.execute(
        """
        SELECT COALESCE(SUM(final_total), 0) AS total
        FROM bills
        WHERE customer_id = ?
          AND status != 'cancelled'
          AND bill_date >= ?
          AND bill_date < ?
        """,
        (customer_id, cycle["start_date"], cycle["end_date"]),
    ).fetchone()
    return float(row["total"])


def check_and_unlock_gifts(db, customer_id, bill_id):
    """Insert loyalty_gifts rows for any newly crossed tier thresholds within
    the current loyalty cycle. Returns list of newly unlocked tier names
    (empty if none, or if the program is paused, or if no cycle is active)."""
    if not is_loyalty_enabled(db):
        return []

    cycle = get_current_cycle(db)
    if cycle is None:
        return []

    spent = get_cycle_spent(db, customer_id, cycle)

    existing = {
        row["tier"]
        for row in db.execute(
            "SELECT tier FROM loyalty_gifts WHERE customer_id = ? AND cycle_id = ?",
            (customer_id, cycle["id"]),
        ).fetchall()
    }

    newly_unlocked = []
    for tier_name, threshold in TIERS:
        if spent >= threshold and tier_name not in existing:
            db.execute(
                "INSERT INTO loyalty_gifts (customer_id, tier, cycle_id, bill_id) VALUES (?, ?, ?, ?)",
                (customer_id, tier_name, cycle["id"], bill_id),
            )
            newly_unlocked.append(tier_name)

    return newly_unlocked
