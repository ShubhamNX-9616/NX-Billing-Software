import re
from decimal import Decimal, ROUND_HALF_UP


def normalize_mobile(raw):
    """Strip non-digits, remove leading +91 or 0, return last 10 digits."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return digits


def validate_indian_mobile(norm_mobile):
    """Return True if norm_mobile is a valid 10-digit Indian number (starts with 6-9)."""
    return bool(re.fullmatch(r"[6-9]\d{9}", norm_mobile))


def r2(n):
    """Round to 2 dp using round-half-up, matching JavaScript's Math.round behaviour."""
    return float(Decimal(str(n)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
