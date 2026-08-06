"""Tests for updating an existing bill (PUT /api/bills/<id>).

The new-bill screen keeps the form editable after a save and pushes any
further change through this endpoint, so the update path has to be as solid
as create. Runs against a temp DB — billing.db is never touched.
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

    init_db()

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(bills_bp, url_prefix="/api")
    app.teardown_appcontext(close_db)

    with app.app_context():
        d = get_db()
        d.execute("INSERT OR IGNORE INTO salespersons (name) VALUES ('Self')")
        d.execute(
            "INSERT OR IGNORE INTO cloth_types (type_name, normalized_name) VALUES ('Shirting','shirting')"
        )
        d.commit()

    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = "admin"
        s["username"] = "admin"
    return c


def _make_bill(client, **overrides):
    body = {
        "customer_name": "Test Cust",
        "customer_mobile": "9876543210",
        "bill_date": "2026-08-06",
        "salesperson_name": "Self",
        "payment_mode_type": "Cash",
        "advance_paid": 1000,
        "items": [{"cloth_type": "Shirting", "company_name": "ACME",
                   "quantity": 2, "unit_label": "m", "mrp": 500,
                   "discount_percent": 0}],
    }
    body.update(overrides)
    return client.post("/api/bills", json=body)


def test_update_persists_every_field(client):
    created = _make_bill(client).get_json()
    bill_id = created["id"]

    res = client.put(f"/api/bills/{bill_id}", json={
        "customer_name": "Renamed Cust",
        "customer_mobile": "9812345678",
        "bill_date": "2026-08-07",
        "salesperson_name": "Self",
        "payment_mode_type": "Cash",
        "advance_paid": 1800,
        "items": [{"cloth_type": "Shirting", "company_name": "ACME",
                   "quantity": 4, "unit_label": "m", "mrp": 500,
                   "discount_percent": 10}],
    })
    assert res.status_code == 200

    got = client.get(f"/api/bills/{bill_id}").get_json()
    assert got["customer_name_snapshot"] == "Renamed Cust"
    assert got["customer_mobile_snapshot"] == "9812345678"
    assert got["bill_date"] == "2026-08-07"
    assert got["final_total"] == 1800.0        # 4 × 500 less 10%
    assert got["advance_paid"] == 1800.0
    assert len(got["items"]) == 1              # replaced, not appended
    assert got["items"][0]["quantity"] == 4.0
    assert got["items"][0]["rate_after_disc"] == 450.0


def test_update_does_not_create_a_second_bill(client):
    created = _make_bill(client).get_json()
    client.put(f"/api/bills/{created['id']}", json={
        "customer_name": "Test Cust",
        "customer_mobile": "9876543210",
        "bill_date": "2026-08-06",
        "salesperson_name": "Self",
        "payment_mode_type": "Cash",
        "advance_paid": 0,
        "items": [{"cloth_type": "Shirting", "company_name": "ACME",
                   "quantity": 1, "unit_label": "m", "mrp": 500,
                   "discount_percent": 0}],
    })
    bills = client.get("/api/bills").get_json()
    assert len(bills) == 1
    assert bills[0]["bill_number"] == created["bill_number"]   # number is kept


def test_update_response_carries_the_share_fields(client):
    """The new-bill screen rebuilds its WhatsApp / share-link buttons from
    this response, so it must expose the same fields the create call does."""
    created = _make_bill(client).get_json()
    res = client.put(f"/api/bills/{created['id']}", json={
        "customer_name": "Test Cust",
        "customer_mobile": "9876543210",
        "bill_date": "2026-08-06",
        "salesperson_name": "Self",
        "payment_mode_type": "Cash",
        "advance_paid": 500,
        "items": [{"cloth_type": "Shirting", "company_name": "ACME",
                   "quantity": 1, "unit_label": "m", "mrp": 500,
                   "discount_percent": 0}],
    }).get_json()

    for field in ("id", "bill_number", "customer_name", "customer_mobile",
                  "share_link", "final_total", "advance_paid", "remaining",
                  "bill_date"):
        assert field in res, f"missing {field}"
    assert res["share_link"].endswith(created["bill_number"])


def test_update_rejects_advance_above_total(client):
    created = _make_bill(client).get_json()
    res = client.put(f"/api/bills/{created['id']}", json={
        "customer_name": "Test Cust",
        "customer_mobile": "9876543210",
        "bill_date": "2026-08-06",
        "salesperson_name": "Self",
        "payment_mode_type": "Cash",
        "advance_paid": 5000,
        "items": [{"cloth_type": "Shirting", "company_name": "ACME",
                   "quantity": 1, "unit_label": "m", "mrp": 500,
                   "discount_percent": 0}],
    })
    assert res.status_code == 400
    # Rejected update must leave the stored bill untouched
    assert client.get(f"/api/bills/{created['id']}").get_json()["final_total"] == 1000.0


def test_update_is_admin_only(client):
    """Staff may create bills but not update them — the new-bill screen relies
    on this to decide whether to offer post-save editing."""
    created = _make_bill(client).get_json()
    with client.session_transaction() as s:
        s["role"] = "staff"
    res = client.put(f"/api/bills/{created['id']}", json={
        "customer_name": "Test Cust",
        "customer_mobile": "9876543210",
        "bill_date": "2026-08-06",
        "salesperson_name": "Self",
        "payment_mode_type": "Cash",
        "advance_paid": 0,
        "items": [{"cloth_type": "Shirting", "company_name": "ACME",
                   "quantity": 1, "unit_label": "m", "mrp": 500,
                   "discount_percent": 0}],
    })
    assert res.status_code == 403


def test_update_missing_bill_is_404(client):
    res = client.put("/api/bills/9999", json={
        "customer_name": "Test Cust",
        "customer_mobile": "9876543210",
        "bill_date": "2026-08-06",
        "salesperson_name": "Self",
        "payment_mode_type": "Cash",
        "advance_paid": 0,
        "items": [{"cloth_type": "Shirting", "company_name": "ACME",
                   "quantity": 1, "unit_label": "m", "mrp": 500,
                   "discount_percent": 0}],
    })
    assert res.status_code == 404
