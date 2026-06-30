import sqlite3
import pytest
from datetime import date
from unittest.mock import MagicMock, patch

from db.connection import current_fy, generate_bill_number, generate_inst_bill_number


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _with_bill_seq(next_val, fy):
    conn = _conn()
    conn.executescript("""
        CREATE TABLE bill_number_seq (
            id       INTEGER PRIMARY KEY,
            next_val INTEGER NOT NULL DEFAULT 0,
            fy       TEXT    NOT NULL DEFAULT ''
        );
    """)
    conn.execute(
        "INSERT INTO bill_number_seq (id, next_val, fy) VALUES (1, ?, ?)",
        (next_val, fy),
    )
    conn.commit()
    return conn


def _with_inst_seq(next_val=None, fy=None):
    conn = _conn()
    conn.executescript("""
        CREATE TABLE inst_bill_number_seq (
            id       INTEGER PRIMARY KEY,
            next_val INTEGER NOT NULL DEFAULT 0,
            fy       TEXT    NOT NULL DEFAULT ''
        );
    """)
    if next_val is not None:
        conn.execute(
            "INSERT INTO inst_bill_number_seq (id, next_val, fy) VALUES (1, ?, ?)",
            (next_val, fy),
        )
    conn.commit()
    return conn


def _mock_today(year, month):
    """Patch db.connection.date so date.today() returns the given year/month."""
    mock_date = MagicMock()
    mock_date.today.return_value = date(year, month, 15)
    return patch("db.connection.date", mock_date)


# ---------------------------------------------------------------------------
# current_fy
# ---------------------------------------------------------------------------

class TestCurrentFy:
    def test_april_opens_new_fy(self):
        with _mock_today(2026, 4):
            assert current_fy() == "26-27"

    def test_march_is_still_previous_fy(self):
        with _mock_today(2026, 3):
            assert current_fy() == "25-26"

    def test_january_is_still_previous_fy(self):
        with _mock_today(2026, 1):
            assert current_fy() == "25-26"

    def test_december_stays_in_current_fy(self):
        with _mock_today(2025, 12):
            assert current_fy() == "25-26"

    def test_boundary_march_to_april(self):
        with _mock_today(2025, 3):
            before = current_fy()
        with _mock_today(2025, 4):
            after = current_fy()
        assert before == "24-25"
        assert after  == "25-26"


# ---------------------------------------------------------------------------
# generate_bill_number
# ---------------------------------------------------------------------------

class TestGenerateBillNumber:
    def test_first_call_returns_0001(self):
        conn = _with_bill_seq(next_val=0, fy="25-26")
        with _mock_today(2025, 6):
            num = generate_bill_number(conn)
        assert num == "SHN-0001/25-26"

    def test_sequential_calls_increment(self):
        conn = _with_bill_seq(next_val=0, fy="25-26")
        with _mock_today(2025, 6):
            assert generate_bill_number(conn) == "SHN-0001/25-26"
            assert generate_bill_number(conn) == "SHN-0002/25-26"
            assert generate_bill_number(conn) == "SHN-0003/25-26"

    def test_fy_rollover_resets_to_0001(self):
        conn = _with_bill_seq(next_val=42, fy="25-26")
        with _mock_today(2026, 4):  # new FY 26-27
            num = generate_bill_number(conn)
        assert num == "SHN-0001/26-27"

    def test_fy_rollover_updates_seq_table(self):
        conn = _with_bill_seq(next_val=42, fy="25-26")
        with _mock_today(2026, 4):
            generate_bill_number(conn)
        row = conn.execute("SELECT next_val, fy FROM bill_number_seq WHERE id = 1").fetchone()
        assert row["next_val"] == 1
        assert row["fy"] == "26-27"

    def test_seq_table_increments_correctly(self):
        conn = _with_bill_seq(next_val=0, fy="25-26")
        with _mock_today(2025, 6):
            generate_bill_number(conn)
            generate_bill_number(conn)
        row = conn.execute("SELECT next_val FROM bill_number_seq WHERE id = 1").fetchone()
        assert row["next_val"] == 2

    def test_pads_single_digit_to_four(self):
        conn = _with_bill_seq(next_val=8, fy="25-26")
        with _mock_today(2025, 6):
            assert generate_bill_number(conn) == "SHN-0009/25-26"

    def test_four_digit_sequence_no_padding(self):
        conn = _with_bill_seq(next_val=999, fy="25-26")
        with _mock_today(2025, 6):
            assert generate_bill_number(conn) == "SHN-1000/25-26"

    def test_continues_after_rollover(self):
        conn = _with_bill_seq(next_val=99, fy="25-26")
        with _mock_today(2026, 4):
            assert generate_bill_number(conn) == "SHN-0001/26-27"
            assert generate_bill_number(conn) == "SHN-0002/26-27"


# ---------------------------------------------------------------------------
# generate_inst_bill_number
# ---------------------------------------------------------------------------

class TestGenerateInstBillNumber:
    def test_empty_table_starts_at_0001(self):
        conn = _with_inst_seq()  # no row
        with _mock_today(2025, 6):
            num = generate_inst_bill_number(conn)
        assert num == "INST-0001/25-26"

    def test_empty_table_inserts_seq_row(self):
        conn = _with_inst_seq()
        with _mock_today(2025, 6):
            generate_inst_bill_number(conn)
        row = conn.execute(
            "SELECT next_val, fy FROM inst_bill_number_seq WHERE id = 1"
        ).fetchone()
        assert row["next_val"] == 1
        assert row["fy"] == "25-26"

    def test_sequential_calls_increment(self):
        conn = _with_inst_seq()
        with _mock_today(2025, 6):
            assert generate_inst_bill_number(conn) == "INST-0001/25-26"
            assert generate_inst_bill_number(conn) == "INST-0002/25-26"
            assert generate_inst_bill_number(conn) == "INST-0003/25-26"

    def test_fy_rollover_resets_to_0001(self):
        conn = _with_inst_seq(next_val=15, fy="25-26")
        with _mock_today(2026, 4):
            num = generate_inst_bill_number(conn)
        assert num == "INST-0001/26-27"

    def test_fy_rollover_updates_seq_table(self):
        conn = _with_inst_seq(next_val=15, fy="25-26")
        with _mock_today(2026, 4):
            generate_inst_bill_number(conn)
        row = conn.execute(
            "SELECT next_val, fy FROM inst_bill_number_seq WHERE id = 1"
        ).fetchone()
        assert row["next_val"] == 1
        assert row["fy"] == "26-27"

    def test_pads_single_digit_to_four(self):
        conn = _with_inst_seq(next_val=8, fy="25-26")
        with _mock_today(2025, 6):
            assert generate_inst_bill_number(conn) == "INST-0009/25-26"

    def test_four_digit_sequence_no_padding(self):
        conn = _with_inst_seq(next_val=999, fy="25-26")
        with _mock_today(2025, 6):
            assert generate_inst_bill_number(conn) == "INST-1000/25-26"

    def test_continues_after_rollover(self):
        conn = _with_inst_seq(next_val=5, fy="25-26")
        with _mock_today(2026, 4):
            assert generate_inst_bill_number(conn) == "INST-0001/26-27"
            assert generate_inst_bill_number(conn) == "INST-0002/26-27"
