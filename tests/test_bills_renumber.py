import pytest
from routes.bills import _renumber_bills_after_delete


def _insert_bill(db, bill_number):
    db.execute(
        "INSERT INTO bills (bill_number, customer_name_snapshot, customer_mobile_snapshot,"
        " bill_date, payment_mode_type) VALUES (?, 'Test', '9876543210', '2025-01-01', 'Cash')",
        (bill_number,),
    )


def _delete_bill(db, bill_number):
    """Simulate the DELETE that happens in the route before renumbering is called."""
    db.execute("DELETE FROM bills WHERE bill_number = ?", (bill_number,))


def _bill_numbers(db):
    return sorted(r["bill_number"] for r in db.execute("SELECT bill_number FROM bills").fetchall())


class TestRenumberBillsAfterDelete:
    def test_deleting_middle_bill_shifts_higher_bills_down(self, db):
        _insert_bill(db, "SHN-0001/25-26")
        _insert_bill(db, "SHN-0002/25-26")
        _insert_bill(db, "SHN-0003/25-26")
        _delete_bill(db, "SHN-0002/25-26")
        db.commit()

        _renumber_bills_after_delete(db, 2, "25-26")
        db.commit()

        # 0003 should shift down to 0002; 0001 unchanged
        assert _bill_numbers(db) == ["SHN-0001/25-26", "SHN-0002/25-26"]

    def test_deleting_first_bill_shifts_all_others_down(self, db):
        _insert_bill(db, "SHN-0001/25-26")
        _insert_bill(db, "SHN-0002/25-26")
        _insert_bill(db, "SHN-0003/25-26")
        _delete_bill(db, "SHN-0001/25-26")
        db.commit()

        _renumber_bills_after_delete(db, 1, "25-26")
        db.commit()

        # 0002→0001, 0003→0002
        assert _bill_numbers(db) == ["SHN-0001/25-26", "SHN-0002/25-26"]

    def test_deleting_last_bill_leaves_others_unchanged(self, db):
        _insert_bill(db, "SHN-0001/25-26")
        _insert_bill(db, "SHN-0002/25-26")
        _delete_bill(db, "SHN-0002/25-26")
        db.commit()

        _renumber_bills_after_delete(db, 2, "25-26")
        db.commit()

        assert _bill_numbers(db) == ["SHN-0001/25-26"]

    def test_only_bill_leaves_table_empty(self, db):
        _insert_bill(db, "SHN-0001/25-26")
        _delete_bill(db, "SHN-0001/25-26")
        db.commit()

        _renumber_bills_after_delete(db, 1, "25-26")
        db.commit()

        assert _bill_numbers(db) == []

    def test_different_fy_bills_are_not_renumbered(self, db):
        _insert_bill(db, "SHN-0001/25-26")
        _insert_bill(db, "SHN-0002/25-26")
        _insert_bill(db, "SHN-0001/24-25")  # different FY — must stay untouched
        _delete_bill(db, "SHN-0001/25-26")
        db.commit()

        _renumber_bills_after_delete(db, 1, "25-26")
        db.commit()

        numbers = _bill_numbers(db)
        assert "SHN-0001/24-25" in numbers   # other FY untouched
        assert "SHN-0001/25-26" in numbers   # 0002 shifted down to 0001

    def test_legacy_format_renumbers_within_no_fy_bills_only(self, db):
        _insert_bill(db, "SHN-0001")
        _insert_bill(db, "SHN-0002")
        _insert_bill(db, "SHN-0003")
        _delete_bill(db, "SHN-0001")
        db.commit()

        _renumber_bills_after_delete(db, 1, None)
        db.commit()

        assert _bill_numbers(db) == ["SHN-0001", "SHN-0002"]

    def test_legacy_format_does_not_affect_fy_bills(self, db):
        _insert_bill(db, "SHN-0001")
        _insert_bill(db, "SHN-0002")
        _insert_bill(db, "SHN-0001/25-26")  # FY bill — must not be touched
        _delete_bill(db, "SHN-0001")
        db.commit()

        _renumber_bills_after_delete(db, 1, None)
        db.commit()

        numbers = _bill_numbers(db)
        assert "SHN-0001/25-26" in numbers   # FY bill untouched
        assert "SHN-0001" in numbers          # 0002 shifted to 0001
