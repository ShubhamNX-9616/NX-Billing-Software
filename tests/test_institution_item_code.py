"""An institution bill item keeps the inventory code typed on its row.

Runs against a temp DB — billing.db is never touched.
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

    from db import close_db, init_db
    from routes.institution_bills import inst_bills_bp

    init_db()

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(inst_bills_bp, url_prefix="/api")
    app.teardown_appcontext(close_db)

    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = "admin"
        s["username"] = "admin"
    return c


def _body(code):
    return {
        "company_name": "Acme School",
        "bill_date": "2026-08-06",
        "payment_mode_type": "Cash",
        "items": [{"cloth_type": "Shirting", "company_name": "ACME", "quality_number": "Q1",
                   "item_code": code, "quantity_per_pc": 1.2, "rate_per_m": 100, "no_of_pcs": 5}],
        "payments": [],
    }


def test_item_code_saved_and_returned(client):
    res = client.post("/api/institution-bills", json=_body(" SHT-004 "))
    assert res.status_code == 201
    assert res.get_json()["items"][0]["item_code"] == "SHT-004"

    bill_id = res.get_json()["id"]
    got = client.get(f"/api/institution-bills/{bill_id}").get_json()
    assert got["items"][0]["item_code"] == "SHT-004"


def test_item_code_updated_and_optional(client):
    bill_id = client.post("/api/institution-bills", json=_body("SHT-004")).get_json()["id"]

    assert client.put(f"/api/institution-bills/{bill_id}", json=_body("")).status_code == 200
    got = client.get(f"/api/institution-bills/{bill_id}").get_json()
    assert not got["items"][0]["item_code"]

    assert client.put(f"/api/institution-bills/{bill_id}", json=_body("SUT-001")).status_code == 200
    got = client.get(f"/api/institution-bills/{bill_id}").get_json()
    assert got["items"][0]["item_code"] == "SUT-001"
