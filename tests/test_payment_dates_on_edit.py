"""Editing a bill must not wipe the dates of payments received on different days.

Dues are paid in instalments (30% one day, 40% another, the rest later), each
stored as its own bill_payments row with its own paid_at. The edit form only
sends one amount per method, so the edit route has to reconcile against the
stored rows instead of deleting and re-inserting them. Runs against a temp DB.
"""
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "billing_test.db"))

    from db import get_db, close_db, init_db
    from routes.bills import bills_bp
    from routes.institution_bills import inst_bills_bp

    init_db()

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bills_bp, url_prefix="/api")
    app.register_blueprint(inst_bills_bp, url_prefix="/api")
    app.teardown_appcontext(close_db)

    with app.app_context():
        d = get_db()
        d.execute("INSERT OR IGNORE INTO salespersons (name) VALUES ('Self')")
        d.execute("INSERT OR IGNORE INTO cloth_types (type_name, normalized_name) "
                  "VALUES ('Shirting','shirting')")
        d.commit()

    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = "admin"
        s["username"] = "admin"
    return c


def _rows(client, table, bill_id):
    from db import get_db
    with client.application.app_context():
        return [(r["payment_method"], r["amount"], r["paid_at"]) for r in get_db().execute(
            f"SELECT payment_method, amount, paid_at FROM {table} "
            f"WHERE bill_id = ? ORDER BY id", (bill_id,))]


# ---------------------------------------------------------------- normal bills
def _item(qty=2):
    return {"cloth_type": "Shirting", "company_name": "ACME", "quantity": qty,
            "unit_label": "m", "mrp": 500, "discount_percent": 0}


def _bill_body(advance, payments, **extra):
    body = {
        "customer_name": "Test Cust", "customer_mobile": "9876543210",
        "bill_date": "2026-08-06", "salesperson_name": "Self",
        "payment_mode_type": "Cash", "advance_paid": advance, "payments": payments,
        "items": [_item()],                                   # total 1000
    }
    body.update(extra)
    return body


def _bill_in_three_instalments(client):
    """Total 1000: 300 at billing, then 300 on 11-10 and 400 on 11-20."""
    bill_id = client.post("/api/bills", json=_bill_body(
        300, [{"payment_method": "Cash", "amount": 300}])).get_json()["id"]
    for amount, day in ((300, "2026-11-10"), (400, "2026-11-20")):
        r = client.post(f"/api/bills/{bill_id}/record-payment",
                        json={"payment_method": "Cash", "amount": amount, "paid_date": day})
        assert r.status_code == 200
    return bill_id


def _edit(client, bill_id, cash, **extra):
    res = client.put(f"/api/bills/{bill_id}", json=_bill_body(
        cash, [{"payment_method": "Cash", "amount": cash}], **extra))
    assert res.status_code == 200, res.get_json()


def test_editing_other_fields_keeps_every_instalment_date(client):
    bill_id = _bill_in_three_instalments(client)
    before = _rows(client, "bill_payments", bill_id)
    assert [r[2] for r in before] == [None, "2026-11-10", "2026-11-20"]

    # The form sends the 1000 total as a single Cash amount.
    _edit(client, bill_id, 1000, customer_name="Renamed Cust")
    assert _rows(client, "bill_payments", bill_id) == before


def test_lowering_the_total_trims_the_newest_instalments_first(client):
    bill_id = _bill_in_three_instalments(client)
    _edit(client, bill_id, 700)    # cuts the 400 (11-20) down to 100, keeps its date
    assert _rows(client, "bill_payments", bill_id) == [
        ("Cash", 300.0, None), ("Cash", 300.0, "2026-11-10"), ("Cash", 100.0, "2026-11-20")]

    _edit(client, bill_id, 600)    # drops the 11-20 instalment entirely
    assert _rows(client, "bill_payments", bill_id) == [
        ("Cash", 300.0, None), ("Cash", 300.0, "2026-11-10")]

    _edit(client, bill_id, 450)    # cuts into the 11-10 instalment, keeps its date
    assert _rows(client, "bill_payments", bill_id) == [
        ("Cash", 300.0, None), ("Cash", 150.0, "2026-11-10")]


def test_raising_the_total_adds_an_undated_row_and_keeps_old_dates(client):
    bill_id = _bill_in_three_instalments(client)
    _edit(client, bill_id, 1200, items=[_item(3)])            # bill is now 1500
    assert _rows(client, "bill_payments", bill_id) == [
        ("Cash", 300.0, None), ("Cash", 300.0, "2026-11-10"),
        ("Cash", 400.0, "2026-11-20"), ("Cash", 200.0, None)]


def test_changing_the_method_replaces_the_rows(client):
    bill_id = _bill_in_three_instalments(client)
    res = client.put(f"/api/bills/{bill_id}", json=_bill_body(
        1000, [{"payment_method": "UPI", "amount": 1000}], payment_mode_type="UPI"))
    assert res.status_code == 200
    assert _rows(client, "bill_payments", bill_id) == [("UPI", 1000.0, None)]


def test_combination_keeps_dates_per_method(client):
    bill_id = client.post("/api/bills", json=_bill_body(
        300, [{"payment_method": "Cash", "amount": 300}])).get_json()["id"]
    client.post(f"/api/bills/{bill_id}/record-payment",
                json={"payment_method": "UPI", "amount": 200, "paid_date": "2026-11-12"})
    client.post(f"/api/bills/{bill_id}/record-payment",
                json={"payment_method": "Cash", "amount": 100, "paid_date": "2026-11-15"})

    res = client.put(f"/api/bills/{bill_id}", json=_bill_body(
        600, [{"payment_method": "Cash", "amount": 400},
              {"payment_method": "UPI", "amount": 200}], payment_mode_type="Combination"))
    assert res.status_code == 200
    assert _rows(client, "bill_payments", bill_id) == [
        ("Cash", 300.0, None), ("UPI", 200.0, "2026-11-12"), ("Cash", 100.0, "2026-11-15")]


def test_a_bill_with_no_payments_still_saves_new_ones(client):
    bill_id = client.post("/api/bills", json=_bill_body(0, [])).get_json()["id"]
    _edit(client, bill_id, 400)
    assert _rows(client, "bill_payments", bill_id) == [("Cash", 400.0, None)]


# ----------------------------------------------------------- institution bills
def _inst_body(advance, payments, **extra):
    body = {
        "company_name": "Acme School", "bill_date": "2026-08-06",
        "payment_mode_type": "Cash", "advance_paid": advance, "payments": payments,
        "items": [{"cloth_type": "Shirting", "company_name": "ACME", "quality_number": "Q1",
                   "quantity_per_pc": 1.2, "rate_per_m": 100, "no_of_pcs": 5}],   # total 600
    }
    body.update(extra)
    return body


def _inst_in_three_instalments(client):
    """Total 600: 180 at billing, then 180 on 11-10 and 240 on 11-20."""
    bill_id = client.post("/api/institution-bills", json=_inst_body(
        180, [{"payment_method": "Cash", "amount": 180}])).get_json()["id"]
    for amount, day in ((180, "2026-11-10"), (240, "2026-11-20")):
        r = client.post(f"/api/institution-bills/{bill_id}/record-payment",
                        json={"payment_method": "Cash", "amount": amount, "paid_date": day})
        assert r.status_code == 200
    return bill_id


def test_institution_edit_keeps_every_instalment_date(client):
    bill_id = _inst_in_three_instalments(client)
    before = _rows(client, "institution_bill_payments", bill_id)
    assert [r[2] for r in before] == [None, "2026-11-10", "2026-11-20"]

    res = client.put(f"/api/institution-bills/{bill_id}", json=_inst_body(
        600, [{"payment_method": "Cash", "amount": 600}], company_name="Renamed School"))
    assert res.status_code == 200
    assert _rows(client, "institution_bill_payments", bill_id) == before


def test_institution_lowering_trims_newest_first_and_raising_adds_undated(client):
    bill_id = _inst_in_three_instalments(client)
    res = client.put(f"/api/institution-bills/{bill_id}", json=_inst_body(
        300, [{"payment_method": "Cash", "amount": 300}]))
    assert res.status_code == 200
    assert _rows(client, "institution_bill_payments", bill_id) == [
        ("Cash", 180.0, None), ("Cash", 120.0, "2026-11-10")]

    res = client.put(f"/api/institution-bills/{bill_id}", json=_inst_body(
        400, [{"payment_method": "Cash", "amount": 400}]))
    assert res.status_code == 200
    assert _rows(client, "institution_bill_payments", bill_id) == [
        ("Cash", 180.0, None), ("Cash", 120.0, "2026-11-10"), ("Cash", 100.0, None)]


def test_institution_cheque_method_is_handled(client):
    bill_id = client.post("/api/institution-bills", json=_inst_body(
        200, [{"payment_method": "Cheque", "amount": 200}],
        payment_mode_type="Cheque")).get_json()["id"]
    client.post(f"/api/institution-bills/{bill_id}/record-payment",
                json={"payment_method": "Cheque", "amount": 100, "paid_date": "2026-11-10"})

    res = client.put(f"/api/institution-bills/{bill_id}", json=_inst_body(
        300, [{"payment_method": "Cheque", "amount": 300}], payment_mode_type="Cheque"))
    assert res.status_code == 200
    assert _rows(client, "institution_bill_payments", bill_id) == [
        ("Cheque", 200.0, None), ("Cheque", 100.0, "2026-11-10")]
