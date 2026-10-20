"""Tests for GET /api/inventory/by-code/<code>.

Typing the code without its hyphen ("sut001") must find the same item as
"SUT-001". Runs against a temp DB — billing.db is never touched.
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
    from routes.inventory import inventory_bp

    init_db()

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(inventory_bp, url_prefix="/api")
    app.teardown_appcontext(close_db)

    with app.app_context():
        d = get_db()
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


def _make_item(client, **overrides):
    body = {
        "cloth_type": "Shirting", "company_name": "Raymonds",
        "quality_number": "TOSALDO", "item_name": "TOSALDO",
        "mrp": 855, "cost_price": 455, "opening_stock": 5,
    }
    body.update(overrides)
    return client.post("/api/inventory", json=body)



def _code_of(client):
    res = _make_item(client)
    assert res.status_code in (200, 201), res.get_json()
    return res.get_json()["item_code"], res.get_json()["id"]


def test_exact_code_any_case(client):
    code, item_id = _code_of(client)
    res = client.get(f"/api/inventory/by-code/{code.lower()}")
    assert res.status_code == 200
    assert res.get_json()["id"] == item_id


def test_code_without_hyphen_matches(client):
    code, item_id = _code_of(client)
    assert "-" in code
    res = client.get(f"/api/inventory/by-code/{code.replace('-', '').lower()}")
    assert res.status_code == 200
    assert res.get_json()["id"] == item_id


def test_unknown_code_is_404(client):
    _code_of(client)
    assert client.get("/api/inventory/by-code/zzz999").status_code == 404
