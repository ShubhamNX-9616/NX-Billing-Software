import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# The shop runs on Indian Standard Time, but the server may not (PythonAnywhere
# runs on UTC, 5.5 hours behind). date.today() / datetime.now() would follow the
# server's clock, so "today", the financial year and loyalty cycles would flip
# at the wrong moment. Anything date-related uses these instead.
IST = timezone(timedelta(hours=5, minutes=30))


def ist_now():
    """Current time in IST (timezone-aware)."""
    return datetime.now(IST)


def ist_today():
    """Today's calendar date in IST, whatever the server's own timezone is."""
    return ist_now().date()


_CLOTH_PREFIX_MAP = {
    'shirting':    'SHT',
    'suiting':     'SUT',
    'readymade':   'RDY',
    'stitching':   'STT',
    'gift sets':   'GFT',
    'accessories': 'ACC',
}


def cloth_type_prefix(cloth_type):
    """Return the 3-letter item-code prefix for a given cloth type."""
    return _CLOTH_PREFIX_MAP.get((cloth_type or '').strip().lower(), 'OTH')


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


# Largest money / quantity value accepted from a request. Far beyond any real bill,
# but small enough that multiplying two accepted values can never overflow to inf.
MAX_AMOUNT = 1e12


# Dates are stored as text (YYYY-MM-DD) and compared as text everywhere: the bill
# search ranges, the monthly analytics, loyalty cycles, delivery boards. A value
# like "yesterday" or "31/11/2026" saved once simply drops out of those, silently.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
MIN_YEAR, MAX_YEAR = 2000, 2100


def valid_iso_date(raw):
    """True only for a real calendar date written exactly as YYYY-MM-DD, in a
    plausible year range (so a mistyped year such as 0226 or 20266 is refused)."""
    text = str(raw or "").strip()
    if not _ISO_DATE.fullmatch(text):
        return False
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return MIN_YEAR <= parsed.year <= MAX_YEAR


def clean_iso_date(raw, label="Date"):
    """A date typed into a form: '' / None -> None; a valid YYYY-MM-DD -> itself;
    anything else raises ValueError with a message fit to show the user."""
    text = str(raw or "").strip()
    if not text:
        return None
    if not valid_iso_date(text):
        raise ValueError(f"{label} must be a real date (YYYY-MM-DD)")
    return text


def finite_float(raw, label="Value"):
    """float(raw) for numbers typed into a form: rejects anything that is not a
    real, reasonably sized number. Python's float() happily accepts "nan" and
    "inf" (and JSON can carry NaN/Infinity), and NaN slips through every
    `< 0` / `> total` check because comparisons with NaN are always False -
    so it would be saved. Raises ValueError with a message fit to show the user."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a number")
    if abs(value) > MAX_AMOUNT:
        raise ValueError(f"{label} is too large")
    return value


def money_float(raw, label="Amount"):
    """A rupee amount typed into a form, as a real number rounded to whole paise.

    Money is stored as a REAL rounded to 2 decimals (see the "Money" note in
    CLAUDE.md). An input such as 100.005 or 33.333333 must not be saved as typed: it
    would make a balance or a payment total disagree with the figure printed on the
    receipt by a fraction of a paisa, and those fractions add up. Raises ValueError
    exactly like finite_float."""
    return r2(finite_float(raw, label))


def r2(n):
    """Round to 2 dp using round-half-up, matching JavaScript's Math.round behaviour."""
    return float(Decimal(str(n)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
