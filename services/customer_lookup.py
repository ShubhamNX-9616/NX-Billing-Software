"""Customer lookup shared by the Tailoring and Suits order forms.

Tailoring orders, suit orders and billing each keep their own customer
details (tailoring.db has no customers table; billing.db has one). This
merges all three into one index keyed by normalized mobile, so a customer
saved in any of them autofills in the others.
"""
import sqlite3
from utils import normalize_mobile

TAILORING_ORDERS = "tailoring_orders"
SUIT_ORDERS = "tailoring_suit_orders"


def _merge(index, name, mobile, address):
    norm = normalize_mobile(mobile or "")
    key = norm or "name:" + (name or "").strip().lower()
    c = index.setdefault(key, {"customer_name": "", "mobile": "", "address": ""})
    c["customer_name"] = name
    if mobile:
        c["mobile"] = mobile
    if address:
        c["address"] = address


def order_customers(tailoring_db):
    """Customers from tailoring and suit orders only (no billing), keyed by
    normalized mobile. Tailoring spellings win over suit ones, newest last."""
    index = {}
    for table in (SUIT_ORDERS, TAILORING_ORDERS):
        rows = tailoring_db.execute(
            f"SELECT customer_name, mobile, address FROM {table} "
            "ORDER BY order_number"
        ).fetchall()
        for r in rows:
            _merge(index, r["customer_name"], r["mobile"], r["address"])
    return index


def customer_index(tailoring_db, billing_db, own_table):
    """Name/mobile/address per customer across billing, tailoring and suits.

    Sources are merged lowest priority first — billing, then the other order
    book, then `own_table` — and rows ascend by order_number within each, so
    the most recent spelling and address from the section being used wins.
    """
    other_table = SUIT_ORDERS if own_table == TAILORING_ORDERS else TAILORING_ORDERS
    index = {}
    try:
        rows = billing_db.execute(
            "SELECT name AS customer_name, mobile, NULL AS address "
            "FROM customers ORDER BY id"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for r in rows:
        _merge(index, r["customer_name"], r["mobile"], r["address"])
    for table in (other_table, own_table):
        rows = tailoring_db.execute(
            f"SELECT customer_name, mobile, address FROM {table} "
            "ORDER BY order_number"
        ).fetchall()
        for r in rows:
            _merge(index, r["customer_name"], r["mobile"], r["address"])
    return index
