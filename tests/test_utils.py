import pytest
from utils import r2, normalize_mobile, validate_indian_mobile, cloth_type_prefix


class TestR2:
    def test_rounds_half_up(self):
        assert r2(2.345) == 2.35

    def test_rounds_down_below_half(self):
        assert r2(2.344) == 2.34

    def test_integer_input(self):
        assert r2(5) == 5.0

    def test_negative_rounds_half_up(self):
        assert r2(-2.344) == -2.34

    def test_already_two_dp(self):
        assert r2(1.50) == 1.50

    def test_zero(self):
        assert r2(0) == 0.0


class TestNormalizeMobile:
    def test_plain_10_digit(self):
        assert normalize_mobile("9876543210") == "9876543210"

    def test_plus_91_prefix(self):
        assert normalize_mobile("+919876543210") == "9876543210"

    def test_91_prefix_12_digits(self):
        assert normalize_mobile("919876543210") == "9876543210"

    def test_leading_zero(self):
        assert normalize_mobile("09876543210") == "9876543210"

    def test_dashes_and_spaces(self):
        assert normalize_mobile("98765-43210") == "9876543210"

    def test_spaces(self):
        assert normalize_mobile("98765 43210") == "9876543210"


class TestValidateIndianMobile:
    @pytest.mark.parametrize("number", ["6876543210", "7876543210", "8876543210", "9876543210"])
    def test_valid_starting_digits(self, number):
        assert validate_indian_mobile(number) is True

    @pytest.mark.parametrize("number", ["5876543210", "4876543210", "1876543210", "0876543210"])
    def test_invalid_starting_digits(self, number):
        assert validate_indian_mobile(number) is False

    def test_too_short(self):
        assert validate_indian_mobile("987654321") is False

    def test_too_long(self):
        assert validate_indian_mobile("98765432100") is False

    def test_empty_string(self):
        assert validate_indian_mobile("") is False


class TestClothTypePrefix:
    @pytest.mark.parametrize("cloth_type,expected", [
        ("shirting",    "SHT"),
        ("suiting",     "SUT"),
        ("readymade",   "RDY"),
        ("stitching",   "STT"),
        ("gift sets",   "GFT"),
        ("accessories", "ACC"),
    ])
    def test_known_types(self, cloth_type, expected):
        assert cloth_type_prefix(cloth_type) == expected

    def test_unknown_type_returns_oth(self):
        assert cloth_type_prefix("denim") == "OTH"

    def test_case_insensitive(self):
        assert cloth_type_prefix("SHIRTING") == "SHT"
        assert cloth_type_prefix("Suiting") == "SUT"

    def test_none_returns_oth(self):
        assert cloth_type_prefix(None) == "OTH"

    def test_empty_string_returns_oth(self):
        assert cloth_type_prefix("") == "OTH"
