"""Billing customer lookup also finds people who only exist in tailoring or
suit orders. Runs against temp billing + tailoring DBs — real ones untouched.
"""
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db.connection as conn_mod
    import db.tailoring as tdb
    monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "billing_test.db"))
    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", str(tmp_path / "tailoring_test.db"))

    from db import close_db, init_db
    from routes.customers import customers_bp

    init_db()
    tdb.init_tailoring_db()

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(customers_bp, url_prefix="/api")
    app.teardown_appcontext(close_db)
    app.teardown_appcontext(tdb.close_tailoring_db)

    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = "admin"
    return c


def _tailoring_order(table, number, name, mobile):
    from db.tailoring import get_tailoring_db
    d = get_tailoring_db()
    cols = "order_number, order_date, customer_name, mobile"
    extra = ", book_no" if table == "tailoring_suit_orders" else ""
    vals = "?, '2026-07-07', ?, ?" + (", '1'" if extra else "")
    d.execute(f"INSERT INTO {table} ({cols}{extra}) VALUES ({vals})",
              (number, name, mobile))
    d.commit()


def _billing_customer(name, mobile):
    from db import get_db
    from utils import normalize_mobile
    d = get_db()
    d.execute("INSERT INTO customers (name, mobile, normalized_mobile) VALUES (?,?,?)",
              (name, mobile, normalize_mobile(mobile)))
    d.commit()


@pytest.mark.parametrize("table", ["tailoring_orders", "tailoring_suit_orders"])
def test_search_finds_order_only_customer(client, table):
    with client.application.app_context():
        _tailoring_order(table, 1, "Order Only", "+91 98765 00010")

    data = client.get("/api/customers/search?mobile=9876500010").get_json()
    assert data["found"] is True
    assert data["customer"]["name"] == "Order Only"


def test_search_prefers_billing_record(client):
    with client.application.app_context():
        _billing_customer("Billing Name", "9876500011")
        _tailoring_order("tailoring_orders", 2, "Tailoring Name", "9876500011")

    data = client.get("/api/customers/search?mobile=9876500011").get_json()
    assert data["customer"]["name"] == "Billing Name"


def test_search_unknown_mobile_not_found(client):
    assert client.get("/api/customers/search?mobile=9999999999").get_json() == {"found": False}


def test_suggest_merges_without_duplicates(client):
    with client.application.app_context():
        _billing_customer("Rao Billing", "9876500012")
        _tailoring_order("tailoring_orders", 3, "Rao Tailoring", "9876500012")  # same person
        _tailoring_order("tailoring_suit_orders", 4, "Rao Suit", "9876500013")

    rows = client.get("/api/customers/suggest?q=rao").get_json()
    assert [(r["name"], r["mobile"]) for r in rows] == [
        ("Rao Billing", "9876500012"), ("Rao Suit", "9876500013"),
    ]
