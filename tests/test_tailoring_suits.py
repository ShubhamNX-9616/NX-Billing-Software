"""Tests for the Suits Tailoring book — its own order-number/book-no scoping,
and its integration into the general Tailoring page's merged daily report.

Uses a minimal Flask app with both tailoring blueprint pairs and a temp
tailoring DB + upload dir, so billing.db and the real tailoring.db are
never touched.
"""
import itertools
import os
import sys
from datetime import timedelta

import pytest
from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db.tailoring as tdb
    import routes.tailoring as tr
    import routes.tailoring_suits as ts

    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", str(tmp_path / "tailoring_test.db"))
    monkeypatch.setattr(tr, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(ts, "UPLOAD_DIR", str(tmp_path / "uploads"))
    tdb.init_tailoring_db()

    app = Flask(
        __name__,
        template_folder=os.path.join(PROJECT_ROOT, "templates"),
        static_folder=os.path.join(PROJECT_ROOT, "static"),
    )
    app.secret_key = "test"
    app.register_blueprint(tr.tailoring_api_bp, url_prefix="/api")
    app.register_blueprint(tr.tailoring_pages_bp)
    app.register_blueprint(ts.tailoring_suit_api_bp, url_prefix="/api")
    app.register_blueprint(ts.tailoring_suit_pages_bp)
    app.teardown_appcontext(tdb.close_tailoring_db)

    @app.template_filter("format_date")
    def format_date_filter(date_str):
        return date_str or ""

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "tester"
            sess["role"] = "admin"
        yield c


_order_numbers = itertools.count(1)


def make_suit_order(client, **overrides):
    body = {
        "book_no": "1",
        "order_number": next(_order_numbers),
        "customer_name": "Deshmukh",
        "mobile": "9876543210",
        "order_date": "2026-07-07",
        "trial_date": "2026-07-15",
        "delivery_date": "2026-07-20",
        "advance": 500,
        "payment_mode": "Cash",
        "items": [{"garment_type": "Suit", "qty": 1, "rate": 3500}],
    }
    body.update(overrides)
    return client.post("/api/tailoring/suits/orders", json=body)


def test_meta_has_full_garment_list_and_no_default_book(client):
    from db.tailoring import GARMENT_TYPES
    meta = client.get("/api/tailoring/suits/meta").get_json()
    # Same garment list as the general Tailoring page, not just "Suit".
    assert meta["garment_types"] == GARMENT_TYPES
    assert "Suit" in meta["garment_types"]
    assert meta["last_book_no"] == ""


def test_create_requires_book_no(client):
    res = make_suit_order(client, book_no="")
    assert res.status_code == 400
    assert "book" in res.get_json()["error"].lower()


def test_book_no_scopes_order_number_uniqueness(client):
    # Same order number in the same book is rejected...
    res1 = make_suit_order(client, book_no="1", order_number=5)
    assert res1.status_code == 201
    res2 = make_suit_order(client, book_no="1", order_number=5)
    assert res2.status_code == 400
    assert "Book 1" in res2.get_json()["error"]

    # ...but the same order number in a different book is fine.
    res3 = make_suit_order(client, book_no="2", order_number=5)
    assert res3.status_code == 201


def test_last_book_no_sticks_after_a_save(client):
    make_suit_order(client, book_no="7")
    meta = client.get("/api/tailoring/suits/meta").get_json()
    assert meta["last_book_no"] == "7"

    make_suit_order(client, book_no="8")
    meta = client.get("/api/tailoring/suits/meta").get_json()
    assert meta["last_book_no"] == "8"


def test_update_order_can_change_book_no(client):
    o = make_suit_order(client, book_no="1", order_number=100).get_json()
    res = client.put(f"/api/tailoring/suits/orders/{o['id']}", json={
        "book_no": "2", "order_number": 100, "customer_name": "Deshmukh",
        "items": [{"garment_type": "Suit", "qty": 1, "rate": 3500}],
    })
    assert res.status_code == 200
    assert res.get_json()["book_no"] == "2"

    # Book 1's #100 is now free again for a fresh order.
    res2 = make_suit_order(client, book_no="1", order_number=100)
    assert res2.status_code == 201


def test_suit_dashboard_and_customers_smoke(client):
    make_suit_order(client, customer_name="Patil", book_no="3")
    dash = client.get("/api/tailoring/suits/dashboard").get_json()
    assert dash["days"][0]["date"]

    customers = client.get("/api/tailoring/suits/customers").get_json()
    assert customers["total"] == 1
    assert customers["customers"][0]["customer_name"] == "Patil"


def test_suit_receipt_share_page(client):
    o = make_suit_order(client, book_no="4", order_number=42,
                        customer_name="Kulkarni").get_json()
    res = client.get(f"/tailoring/suits/share/4/{o['order_number']}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Kulkarni" in html
    assert "42" in html

    assert client.get("/tailoring/suits/share/4/9999").status_code == 404
    # Wrong book for a real order number → not found (book-scoped lookup).
    assert client.get(f"/tailoring/suits/share/999/{o['order_number']}").status_code == 404


def test_daily_report_merges_suit_orders_with_general(client):
    import routes.tailoring as tr
    today = tr._ist_date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    overdue_date = (today - timedelta(days=2)).isoformat()

    # General tailoring order, overdue.
    client.post("/api/tailoring/orders", json={
        "order_number": 9001, "customer_name": "GeneralLate",
        "order_date": "2026-07-01", "delivery_date": overdue_date,
        "items": [{"garment_type": "Shirt", "qty": 1, "rate": 400}],
    })
    # Suit order, delivery due tomorrow.
    make_suit_order(client, book_no="9", order_number=1,
                    customer_name="SuitTomorrow", delivery_date=tomorrow)
    # Suit order, overdue.
    make_suit_order(client, book_no="9", order_number=2,
                    customer_name="SuitLate", delivery_date=overdue_date)

    html = client.get("/tailoring/report").get_data(as_text=True)
    assert "GeneralLate" in html
    assert "SuitTomorrow" in html
    assert "SuitLate" in html
    assert "Book 9" in html   # suit entries are tagged so numbers aren't confused
