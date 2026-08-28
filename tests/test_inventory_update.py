"""Tests for updating an existing inventory item (PUT /api/inventory/<id>).

Regression for a bug where clearing Quality No. on Edit Item raised
"NOT NULL constraint failed: inventory_items.quality_number" — the column
is NOT NULL DEFAULT '', but the route was coercing an empty string to None
before writing it. Runs against a temp DB — billing.db is never touched.
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


def test_update_with_blank_quality_number_succeeds(client):
    item_id = _make_item(client).get_json()["id"]

    res = client.put(f"/api/inventory/{item_id}", json={
        "mrp": 855, "cost_price": 455,
        "quality_number": "", "item_name": "TOSALDO", "shade_number": "",
    })
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["quality_number"] == ""


def test_update_preserves_nonblank_quality_number(client):
    item_id = _make_item(client).get_json()["id"]

    res = client.put(f"/api/inventory/{item_id}", json={
        "mrp": 900, "cost_price": 455, "quality_number": "Q99",
    })
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["quality_number"] == "Q99"
