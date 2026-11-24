"""An invoice saved without a supplier can be given one afterwards.

The inventory screens call PUT /api/invoices/<id> with the invoice's own number
and date plus the chosen supplier. Batch items read their supplier name through
the invoice, so this is how a missed supplier gets fixed. Temp DB only.
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
    from routes.invoices import invoices_bp
    from routes.suppliers import suppliers_bp

    init_db()

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(invoices_bp, url_prefix="/api")
    app.register_blueprint(suppliers_bp, url_prefix="/api")
    app.teardown_appcontext(close_db)

    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
        s["role"] = "admin"
        s["username"] = "admin"
    return c


def _invoice_without_supplier(client):
    res = client.post("/api/invoices", json={
        "invoice_number": "FS/2627/003312", "invoice_date": "2026-11-19"})
    assert res.status_code == 201
    assert res.get_json()["supplier_id"] is None
    return res.get_json()


def _supplier(client, name="Rashi Enterprise"):
    return client.post("/api/suppliers", json={"name": name}).get_json()


def test_supplier_can_be_set_on_a_saved_invoice(client):
    inv = _invoice_without_supplier(client)
    sup = _supplier(client)

    res = client.put(f"/api/invoices/{inv['id']}", json={
        "invoice_number": inv["invoice_number"], "invoice_date": inv["invoice_date"],
        "supplier_id": sup["id"]})
    assert res.status_code == 200
    assert res.get_json()["supplier_name"] == "Rashi Enterprise"

    listed = {i["id"]: i for i in client.get("/api/invoices").get_json()}
    assert listed[inv["id"]]["supplier_id"] == sup["id"]
    assert listed[inv["id"]]["supplier_name"] == "Rashi Enterprise"


def test_supplier_can_be_changed_and_cleared(client):
    inv = _invoice_without_supplier(client)
    a, b = _supplier(client, "Rashi Enterprise"), _supplier(client, "Sudarshan Linen")
    base = {"invoice_number": inv["invoice_number"], "invoice_date": inv["invoice_date"]}

    client.put(f"/api/invoices/{inv['id']}", json={**base, "supplier_id": a["id"]})
    res = client.put(f"/api/invoices/{inv['id']}", json={**base, "supplier_id": b["id"]})
    assert res.get_json()["supplier_name"] == "Sudarshan Linen"

    res = client.put(f"/api/invoices/{inv['id']}", json={**base, "supplier_id": ""})
    assert res.get_json()["supplier_id"] is None


def test_editing_number_or_date_alone_keeps_the_supplier(client):
    sup = _supplier(client)
    inv = client.post("/api/invoices", json={
        "invoice_number": "A1", "invoice_date": "2026-11-19",
        "supplier_id": sup["id"]}).get_json()

    res = client.put(f"/api/invoices/{inv['id']}", json={
        "invoice_number": "A1-fixed", "invoice_date": "2026-11-20"})
    assert res.get_json()["supplier_id"] == sup["id"]      # field omitted: untouched
