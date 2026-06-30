import pytest
from services.billing import (
    calculate_bill_totals,
    parse_advance,
    validate_payments,
    calculate_inst_items,
    validate_and_calculate_items,
    find_or_create_customer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _items(line_total=1000.0, discount_amount=100.0, final_amount=900.0):
    return [{"line_total": line_total, "discount_amount": discount_amount, "final_amount": final_amount}]


# ---------------------------------------------------------------------------
# calculate_bill_totals
# ---------------------------------------------------------------------------

class TestCalculateBillTotals:
    def test_basic_totals(self):
        result = calculate_bill_totals(_items(), None)
        assert result["subtotal"] == 1000.0
        assert result["total_discount"] == 100.0
        assert result["gross_final_total"] == 900.0
        assert result["final_total"] == 900.0
        assert result["round_off"] == 0.0
        assert result["total_savings"] == 100.0

    def test_with_round_off(self):
        result = calculate_bill_totals(_items(), 0.50)
        assert result["final_total"] == 899.50
        assert result["round_off"] == 0.50
        assert result["total_savings"] == 100.50

    def test_multiple_items(self):
        items = [
            {"line_total": 1000.0, "discount_amount": 100.0, "final_amount": 900.0},
            {"line_total": 500.0,  "discount_amount": 0.0,   "final_amount": 500.0},
        ]
        result = calculate_bill_totals(items, None)
        assert result["subtotal"] == 1500.0
        assert result["gross_final_total"] == 1400.0
        assert result["total_discount"] == 100.0

    def test_round_off_exceeds_total_raises(self):
        with pytest.raises(ValueError, match="round_off cannot exceed"):
            calculate_bill_totals(_items(), 1000.0)

    def test_invalid_round_off_string_defaults_to_zero(self):
        result = calculate_bill_totals(_items(), "abc")
        assert result["round_off"] == 0.0
        assert result["final_total"] == 900.0

    def test_no_discount(self):
        items = [{"line_total": 500.0, "discount_amount": 0.0, "final_amount": 500.0}]
        result = calculate_bill_totals(items, None)
        assert result["total_discount"] == 0.0
        assert result["total_savings"] == 0.0


# ---------------------------------------------------------------------------
# parse_advance
# ---------------------------------------------------------------------------

class TestParseAdvance:
    def test_zero_advance(self):
        advance, remaining = parse_advance(None, 1000.0)
        assert advance == 0.0
        assert remaining == 1000.0

    def test_partial_advance(self):
        advance, remaining = parse_advance(400.0, 1000.0)
        assert advance == 400.0
        assert remaining == 600.0

    def test_full_advance(self):
        advance, remaining = parse_advance(1000.0, 1000.0)
        assert advance == 1000.0
        assert remaining == 0.0

    def test_advance_exceeds_total_raises(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            parse_advance(1001.0, 1000.0)

    def test_negative_advance_raises(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            parse_advance(-1.0, 1000.0)

    def test_string_zero_treated_as_zero(self):
        advance, remaining = parse_advance("0", 500.0)
        assert advance == 0.0
        assert remaining == 500.0


# ---------------------------------------------------------------------------
# validate_payments
# ---------------------------------------------------------------------------

class TestValidatePayments:
    def test_empty_list_is_allowed(self):
        validate_payments([], 1000.0)

    def test_none_is_allowed(self):
        validate_payments(None, 1000.0)

    def test_single_valid_payment(self):
        validate_payments([{"payment_method": "Cash", "amount": 1000.0}], 1000.0)

    def test_split_payment(self):
        payments = [
            {"payment_method": "Cash", "amount": 600.0},
            {"payment_method": "UPI",  "amount": 400.0},
        ]
        validate_payments(payments, 1000.0)

    def test_sum_mismatch_raises(self):
        payments = [{"payment_method": "Cash", "amount": 500.0}]
        with pytest.raises(ValueError, match="does not match"):
            validate_payments(payments, 1000.0)

    def test_invalid_method_raises(self):
        payments = [{"payment_method": "Cheque", "amount": 1000.0}]
        with pytest.raises(ValueError, match="payment_method"):
            validate_payments(payments, 1000.0)

    def test_all_valid_methods_accepted(self):
        for method in ("Cash", "Card", "UPI"):
            validate_payments([{"payment_method": method, "amount": 100.0}], 100.0)


# ---------------------------------------------------------------------------
# calculate_inst_items
# ---------------------------------------------------------------------------

class TestCalculateInstItems:
    def _item(self, qty_per_pc=2.0, rate_per_m=100.0, no_of_pcs=3, stitching=0.0):
        return {
            "cloth_type": "Shirting", "company_name": "X", "quality_number": "",
            "quantity_per_pc": qty_per_pc, "rate_per_m": rate_per_m,
            "no_of_pcs": no_of_pcs, "stitching_per_unit": stitching,
        }

    def test_basic_calculation(self):
        # 2.0m * 100/m * 3pcs = 600
        calc, subtotal = calculate_inst_items([self._item()])
        assert subtotal == 600.0
        assert calc[0]["total"] == 600.0

    def test_with_stitching(self):
        # (2 * 100 * 2) + (2 * 50) = 400 + 100 = 500
        calc, subtotal = calculate_inst_items([self._item(qty_per_pc=2.0, rate_per_m=100.0, no_of_pcs=2, stitching=50.0)])
        assert subtotal == 500.0

    def test_multiple_items_subtotal(self):
        items = [self._item(qty_per_pc=1.0, rate_per_m=100.0, no_of_pcs=2),   # 200
                 self._item(qty_per_pc=2.0, rate_per_m=150.0, no_of_pcs=1)]   # 300
        _, subtotal = calculate_inst_items(items)
        assert subtotal == 500.0

    def test_empty_items_raises(self):
        with pytest.raises(ValueError, match="At least one item"):
            calculate_inst_items([])

    def test_invalid_quantity_per_pc_raises(self):
        item = self._item()
        item["quantity_per_pc"] = "bad"
        with pytest.raises(ValueError, match="quantity_per_pc"):
            calculate_inst_items([item])

    def test_invalid_rate_per_m_raises(self):
        item = self._item()
        item["rate_per_m"] = "bad"
        with pytest.raises(ValueError, match="rate_per_m"):
            calculate_inst_items([item])

    def test_invalid_no_of_pcs_raises(self):
        item = self._item()
        item["no_of_pcs"] = "bad"
        with pytest.raises(ValueError, match="no_of_pcs"):
            calculate_inst_items([item])


# ---------------------------------------------------------------------------
# validate_and_calculate_items  (needs db fixture)
# ---------------------------------------------------------------------------

class TestValidateAndCalculateItems:
    def _item(self, cloth_type="Shirting", qty=2.0, mrp=500.0, discount=10.0):
        return {"cloth_type": cloth_type, "company_name": "Monti",
                "quantity": qty, "mrp": mrp, "discount_percent": discount}

    def test_shirting_uses_metre_unit(self, db):
        result = validate_and_calculate_items(db, [self._item("Shirting")])
        assert result[0]["unit_label"] == "m"

    def test_suiting_uses_metre_unit(self, db):
        result = validate_and_calculate_items(db, [self._item("Suiting")])
        assert result[0]["unit_label"] == "m"

    def test_readymade_uses_pcs_unit(self, db):
        result = validate_and_calculate_items(db, [self._item("Readymade")])
        assert result[0]["unit_label"] == "pcs"

    def test_discount_calculation(self, db):
        # mrp=500, qty=2, discount=10% → rate_after_disc=450, final=900, savings=100
        result = validate_and_calculate_items(db, [self._item(mrp=500.0, qty=2.0, discount=10.0)])
        item = result[0]
        assert item["rate_after_disc"] == 450.0
        assert item["final_amount"] == 900.0
        assert item["discount_amount"] == 100.0
        assert item["line_total"] == 1000.0

    def test_zero_discount(self, db):
        result = validate_and_calculate_items(db, [self._item(discount=0)])
        assert result[0]["rate_after_disc"] == result[0]["mrp"]
        assert result[0]["discount_amount"] == 0.0

    def test_empty_items_raises(self, db):
        with pytest.raises(ValueError, match="items array cannot be empty"):
            validate_and_calculate_items(db, [])

    def test_invalid_cloth_type_raises(self, db):
        with pytest.raises(ValueError, match="invalid cloth_type"):
            validate_and_calculate_items(db, [self._item("Denim")])

    def test_zero_quantity_raises(self, db):
        with pytest.raises(ValueError, match="quantity must be > 0"):
            validate_and_calculate_items(db, [self._item(qty=0)])

    def test_negative_quantity_raises(self, db):
        with pytest.raises(ValueError, match="quantity must be > 0"):
            validate_and_calculate_items(db, [self._item(qty=-1)])

    def test_negative_mrp_raises(self, db):
        with pytest.raises(ValueError, match="mrp cannot be negative"):
            validate_and_calculate_items(db, [self._item(mrp=-1)])

    def test_discount_above_100_raises(self, db):
        with pytest.raises(ValueError, match="discount_percent"):
            validate_and_calculate_items(db, [self._item(discount=101)])


# ---------------------------------------------------------------------------
# find_or_create_customer  (needs db fixture)
# ---------------------------------------------------------------------------

class TestFindOrCreateCustomer:
    def test_creates_new_customer(self, db):
        cid = find_or_create_customer(db, "Ravi Kumar", "9876543210")
        db.commit()
        row = db.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
        assert row["name"] == "Ravi Kumar"
        assert row["normalized_mobile"] == "9876543210"

    def test_returns_existing_on_same_mobile(self, db):
        id1 = find_or_create_customer(db, "Ravi Kumar", "9876543210")
        db.commit()
        id2 = find_or_create_customer(db, "Ravi K", "9876543210")
        db.commit()
        assert id1 == id2

    def test_different_mobile_creates_new_record(self, db):
        id1 = find_or_create_customer(db, "Ravi", "9876543210")
        db.commit()
        id2 = find_or_create_customer(db, "Ravi", "9999999999")
        db.commit()
        assert id1 != id2
        assert db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 2
