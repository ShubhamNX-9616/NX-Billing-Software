import pytest
from unittest.mock import MagicMock
from services.billing import (
    validate_and_calculate_items,
    calculate_bill_totals,
    validate_payments,
    parse_advance,
)

CLOTH_TYPES = ["Shirting", "Suiting", "Readymade", "Stitching", "Gift Sets", "Accessories"]


def make_db(cloth_types=None):
    """Return a mock DB whose cloth_types query returns the given list."""
    db = MagicMock()
    rows = [{"type_name": ct, "has_company": 1} for ct in (cloth_types or CLOTH_TYPES)]
    db.execute.return_value.fetchall.return_value = rows
    return db


def make_item(**overrides):
    base = {
        "cloth_type":       "Shirting",
        "company_name":     "Raymonds",
        "quality_number":   "Q1",
        "quantity":         2.0,
        "mrp":              100.0,
        "discount_percent": 0.0,
    }
    base.update(overrides)
    return base


def make_calculated_items(pairs):
    """Helper: [(line_total, final_amount), ...] → list of item dicts for calculate_bill_totals."""
    return [
        {
            "line_total":      lt,
            "discount_amount": round(lt - fa, 2),
            "final_amount":    fa,
        }
        for lt, fa in pairs
    ]


# ─── validate_and_calculate_items ────────────────────────────────────────────

class TestValidateAndCalculateItems:
    def test_basic_calculation_with_discount(self):
        # qty=2, mrp=100, discount=10%
        # disc_per_unit=10, rate_after_disc=90, final_amount=180, line_total=200, discount_amount=20
        items = [make_item(quantity=2.0, mrp=100.0, discount_percent=10.0)]
        result = validate_and_calculate_items(make_db(), items)

        assert len(result) == 1
        r = result[0]
        assert r["line_total"]      == 200.0
        assert r["rate_after_disc"] == 90.0
        assert r["final_amount"]    == 180.0
        assert r["discount_amount"] == 20.0
        assert r["discount_percent"] == 10.0

    def test_shirting_unit_label_is_m(self):
        result = validate_and_calculate_items(make_db(), [make_item(cloth_type="Shirting")])
        assert result[0]["unit_label"] == "m"

    def test_suiting_unit_label_is_m(self):
        result = validate_and_calculate_items(make_db(), [make_item(cloth_type="Suiting")])
        assert result[0]["unit_label"] == "m"

    def test_readymade_unit_label_is_pcs(self):
        result = validate_and_calculate_items(make_db(), [make_item(cloth_type="Readymade")])
        assert result[0]["unit_label"] == "pcs"

    def test_stitching_unit_label_is_pcs(self):
        result = validate_and_calculate_items(make_db(), [make_item(cloth_type="Stitching")])
        assert result[0]["unit_label"] == "pcs"

    def test_zero_discount_no_change(self):
        items = [make_item(quantity=3.0, mrp=200.0, discount_percent=0.0)]
        result = validate_and_calculate_items(make_db(), items)
        assert result[0]["final_amount"]    == 600.0
        assert result[0]["discount_amount"] == 0.0

    def test_100_percent_discount(self):
        items = [make_item(quantity=2.0, mrp=100.0, discount_percent=100.0)]
        result = validate_and_calculate_items(make_db(), items)
        assert result[0]["final_amount"]    == 0.0
        assert result[0]["discount_amount"] == 200.0

    def test_rounding_applied_on_fractional_discount(self):
        # 33.33% of ₹100 → disc_per_unit=33.33, rate_after_disc=66.67
        items = [make_item(quantity=1.0, mrp=100.0, discount_percent=33.33)]
        result = validate_and_calculate_items(make_db(), items)
        assert result[0]["rate_after_disc"] == 66.67
        assert result[0]["final_amount"]    == 66.67

    def test_multiple_items_returned(self):
        items = [
            make_item(cloth_type="Shirting", quantity=2.0, mrp=100.0),
            make_item(cloth_type="Suiting",  quantity=1.0, mrp=500.0),
        ]
        result = validate_and_calculate_items(make_db(), items)
        assert len(result) == 2

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="items array cannot be empty"):
            validate_and_calculate_items(make_db(), [])

    def test_none_raises(self):
        with pytest.raises(ValueError, match="items array cannot be empty"):
            validate_and_calculate_items(make_db(), None)

    def test_invalid_cloth_type_raises(self):
        with pytest.raises(ValueError, match="invalid cloth_type"):
            validate_and_calculate_items(make_db(), [make_item(cloth_type="Denim")])

    def test_zero_quantity_raises(self):
        with pytest.raises(ValueError, match="quantity must be > 0"):
            validate_and_calculate_items(make_db(), [make_item(quantity=0)])

    def test_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="quantity must be > 0"):
            validate_and_calculate_items(make_db(), [make_item(quantity=-1)])

    def test_negative_mrp_raises(self):
        with pytest.raises(ValueError, match="mrp cannot be negative"):
            validate_and_calculate_items(make_db(), [make_item(mrp=-10)])

    def test_discount_above_100_raises(self):
        with pytest.raises(ValueError, match="discount_percent must be 0"):
            validate_and_calculate_items(make_db(), [make_item(discount_percent=101)])

    def test_negative_discount_raises(self):
        with pytest.raises(ValueError, match="discount_percent must be 0"):
            validate_and_calculate_items(make_db(), [make_item(discount_percent=-1)])

    def test_missing_quantity_raises(self):
        item = {"cloth_type": "Shirting", "mrp": 100.0}
        with pytest.raises(ValueError, match="quantity must be a number"):
            validate_and_calculate_items(make_db(), [item])

    def test_missing_mrp_raises(self):
        item = {"cloth_type": "Shirting", "quantity": 2.0}
        with pytest.raises(ValueError, match="mrp must be a number"):
            validate_and_calculate_items(make_db(), [item])

    def test_error_message_includes_item_number(self):
        items = [
            make_item(cloth_type="Shirting"),       # item 1 is valid
            make_item(cloth_type="Shirting", quantity=0),  # item 2 is invalid
        ]
        with pytest.raises(ValueError, match="Item 2"):
            validate_and_calculate_items(make_db(), items)


# ─── calculate_bill_totals ────────────────────────────────────────────────────

class TestCalculateBillTotals:
    def test_no_discount_no_round_off(self):
        items = make_calculated_items([(500.0, 500.0)])
        result = calculate_bill_totals(items, 0)

        assert result["subtotal"]          == 500.0
        assert result["total_discount"]    == 0.0
        assert result["gross_final_total"] == 500.0
        assert result["round_off"]         == 0.0
        assert result["final_total"]       == 500.0
        assert result["total_savings"]     == 0.0

    def test_discount_applied(self):
        # ₹200 line, ₹20 discount → final ₹180
        items = make_calculated_items([(200.0, 180.0)])
        result = calculate_bill_totals(items, 0)

        assert result["subtotal"]          == 200.0
        assert result["total_discount"]    == 20.0
        assert result["gross_final_total"] == 180.0
        assert result["final_total"]       == 180.0
        assert result["total_savings"]     == 20.0

    def test_round_off_reduces_final_total(self):
        items = make_calculated_items([(200.0, 181.50)])
        result = calculate_bill_totals(items, 1.50)

        assert result["round_off"]     == 1.50
        assert result["final_total"]   == 180.0

    def test_round_off_included_in_total_savings(self):
        # ₹500, ₹50 discount, ₹0.50 round-off → savings = ₹50.50
        items = make_calculated_items([(500.0, 450.0)])
        result = calculate_bill_totals(items, 0.50)

        assert result["total_savings"] == 50.50

    def test_multiple_items_summed(self):
        items = make_calculated_items([(200.0, 180.0), (300.0, 300.0)])
        result = calculate_bill_totals(items, 0)

        assert result["subtotal"]          == 500.0
        assert result["total_discount"]    == 20.0
        assert result["gross_final_total"] == 480.0

    def test_none_round_off_treated_as_zero(self):
        items = make_calculated_items([(100.0, 100.0)])
        result = calculate_bill_totals(items, None)
        assert result["round_off"] == 0.0

    def test_string_round_off_parsed(self):
        items = make_calculated_items([(100.0, 100.0)])
        result = calculate_bill_totals(items, "0.50")
        assert result["round_off"]   == 0.50
        assert result["final_total"] == 99.50

    def test_negative_round_off_raises(self):
        items = make_calculated_items([(200.0, 200.0)])
        with pytest.raises(ValueError, match="round_off cannot be negative"):
            calculate_bill_totals(items, -1)

    def test_round_off_exceeds_total_raises(self):
        items = make_calculated_items([(100.0, 100.0)])
        with pytest.raises(ValueError, match="round_off cannot exceed bill total"):
            calculate_bill_totals(items, 101)

    def test_round_off_equal_to_total_is_allowed(self):
        # The code uses `>`, not `>=`, so round_off == gross_final_total is valid
        items = make_calculated_items([(100.0, 100.0)])
        result = calculate_bill_totals(items, 100.0)
        assert result["final_total"] == 0.0


# ─── validate_payments ───────────────────────────────────────────────────────

class TestValidatePayments:
    def test_valid_cash(self):
        validate_payments([{"payment_method": "Cash", "amount": 500.0}], 500.0)

    def test_valid_card(self):
        validate_payments([{"payment_method": "Card", "amount": 1000.0}], 1000.0)

    def test_valid_upi(self):
        validate_payments([{"payment_method": "UPI", "amount": 750.0}], 750.0)

    def test_valid_split_cash_and_upi(self):
        payments = [
            {"payment_method": "Cash", "amount": 300.0},
            {"payment_method": "UPI",  "amount": 200.0},
        ]
        validate_payments(payments, 500.0)

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError, match="payment_method must be one of"):
            validate_payments([{"payment_method": "Cheque", "amount": 100.0}], 100.0)

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="payments array cannot be empty"):
            validate_payments([], 100.0)

    def test_none_raises(self):
        with pytest.raises(ValueError, match="payments array cannot be empty"):
            validate_payments(None, 100.0)

    def test_underpayment_raises(self):
        with pytest.raises(ValueError, match="does not match final_total"):
            validate_payments([{"payment_method": "Cash", "amount": 400.0}], 500.0)

    def test_overpayment_raises(self):
        with pytest.raises(ValueError, match="does not match final_total"):
            validate_payments([{"payment_method": "Cash", "amount": 600.0}], 500.0)

    def test_missing_amount_raises(self):
        with pytest.raises(ValueError, match="payment amount must be a number"):
            validate_payments([{"payment_method": "Cash"}], 0.0)

    def test_non_numeric_amount_raises(self):
        with pytest.raises(ValueError, match="payment amount must be a number"):
            validate_payments([{"payment_method": "Cash", "amount": "abc"}], 0.0)

    def test_within_1_paisa_tolerance_passes(self):
        # 499.999 rounds to 500.00 via r2, so diff is 0 — within 0.01 tolerance
        validate_payments([{"payment_method": "Cash", "amount": 499.999}], 500.0)


# ─── parse_advance ────────────────────────────────────────────────────────────

class TestParseAdvance:
    def test_zero_advance(self):
        advance, remaining = parse_advance(0, 1000.0)
        assert advance   == 0.0
        assert remaining == 1000.0

    def test_partial_advance(self):
        advance, remaining = parse_advance(500, 1000.0)
        assert advance   == 500.0
        assert remaining == 500.0

    def test_full_advance(self):
        advance, remaining = parse_advance(1000, 1000.0)
        assert advance   == 1000.0
        assert remaining == 0.0

    def test_none_defaults_to_zero(self):
        advance, remaining = parse_advance(None, 500.0)
        assert advance   == 0.0
        assert remaining == 500.0

    def test_string_input_parsed(self):
        advance, remaining = parse_advance("250.50", 500.0)
        assert advance   == 250.50
        assert remaining == 249.50

    def test_rounding_applied(self):
        # r2(33.333) = 33.33, r2(100 - 33.33) = 66.67
        advance, remaining = parse_advance("33.333", 100.0)
        assert advance   == 33.33
        assert remaining == 66.67

    def test_negative_advance_raises(self):
        with pytest.raises(ValueError, match="advance_paid cannot be negative"):
            parse_advance(-100, 1000.0)

    def test_advance_exceeds_total_raises(self):
        with pytest.raises(ValueError, match="advance_paid cannot exceed final_total"):
            parse_advance(1001, 1000.0)
