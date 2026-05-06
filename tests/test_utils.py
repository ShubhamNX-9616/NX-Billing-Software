import pytest
from utils import r2, normalize_mobile, validate_indian_mobile, cloth_type_prefix


class TestR2:
    def test_rounds_down(self):
        assert r2(1.004) == 1.0

    def test_rounds_up_at_half(self):
        assert r2(1.005) == 1.01

    def test_half_up_not_bankers(self):
        # Python's built-in round(2.225, 2) gives 2.22 (banker's rounding).
        # r2 must give 2.23 (half-up), which matters for GST and discount math.
        assert r2(2.225) == 2.23
        assert r2(2.235) == 2.24

    def test_integer_input(self):
        assert r2(100) == 100.0

    def test_zero(self):
        assert r2(0) == 0.0

    def test_returns_float(self):
        assert isinstance(r2(1.5), float)

    def test_two_decimal_already_exact(self):
        assert r2(99.99) == 99.99

    def test_large_amount(self):
        assert r2(12345.675) == 12345.68


class TestNormalizeMobile:
    def test_plain_10_digits(self):
        assert normalize_mobile("9876543210") == "9876543210"

    def test_strip_plus91(self):
        assert normalize_mobile("+919876543210") == "9876543210"

    def test_strip_91_prefix_12_digits(self):
        assert normalize_mobile("919876543210") == "9876543210"

    def test_strip_leading_zero(self):
        assert normalize_mobile("09876543210") == "9876543210"

    def test_strip_spaces(self):
        assert normalize_mobile("98765 43210") == "9876543210"

    def test_strip_dashes(self):
        assert normalize_mobile("98765-43210") == "9876543210"


class TestValidateIndianMobile:
    def test_valid_starts_with_9(self):
        assert validate_indian_mobile("9876543210") is True

    def test_valid_starts_with_6(self):
        assert validate_indian_mobile("6000000000") is True

    def test_valid_starts_with_7(self):
        assert validate_indian_mobile("7123456789") is True

    def test_valid_starts_with_8(self):
        assert validate_indian_mobile("8123456789") is True

    def test_invalid_starts_with_5(self):
        assert validate_indian_mobile("5876543210") is False

    def test_invalid_starts_with_1(self):
        assert validate_indian_mobile("1234567890") is False

    def test_invalid_too_short(self):
        assert validate_indian_mobile("987654321") is False

    def test_invalid_too_long(self):
        assert validate_indian_mobile("98765432101") is False

    def test_invalid_empty(self):
        assert validate_indian_mobile("") is False


class TestClothTypePrefix:
    @pytest.mark.parametrize("cloth_type,expected", [
        ("Shirting",    "SHT"),
        ("Suiting",     "SUT"),
        ("Readymade",   "RDY"),
        ("Stitching",   "STT"),
        ("Gift Sets",   "GFT"),
        ("Accessories", "ACC"),
    ])
    def test_known_types(self, cloth_type, expected):
        assert cloth_type_prefix(cloth_type) == expected

    def test_case_insensitive_upper(self):
        assert cloth_type_prefix("SHIRTING") == "SHT"

    def test_case_insensitive_lower(self):
        assert cloth_type_prefix("suiting") == "SUT"

    def test_strips_whitespace(self):
        assert cloth_type_prefix("  Shirting  ") == "SHT"

    def test_unknown_type_returns_oth(self):
        assert cloth_type_prefix("Denim") == "OTH"

    def test_none_returns_oth(self):
        assert cloth_type_prefix(None) == "OTH"

    def test_empty_string_returns_oth(self):
        assert cloth_type_prefix("") == "OTH"
