"""Tests for the standalone Tailoring Delivery System.

Uses a minimal Flask app with only the tailoring blueprints and a temp
tailoring DB + upload dir, so billing.db and the real tailoring.db are
never touched.
"""
import io
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db.tailoring as tdb
    import routes.tailoring as tr

    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", str(tmp_path / "tailoring_test.db"))
    monkeypatch.setattr(tr, "UPLOAD_DIR", str(tmp_path / "uploads"))
    tdb.init_tailoring_db()

    app = Flask(
        __name__,
        template_folder=os.path.join(PROJECT_ROOT, "templates"),
        static_folder=os.path.join(PROJECT_ROOT, "static"),
    )
    app.secret_key = "test"
    app.register_blueprint(tr.tailoring_api_bp, url_prefix="/api")
    app.register_blueprint(tr.tailoring_pages_bp)
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


def make_order(client, **overrides):
    body = {
        "customer_name": "Bawaskar",
        "mobile": "9876543210",
        "order_date": "2026-07-07",
        "trial_date": "2026-07-15",
        "delivery_date": "2026-07-20",
        "advance": 500,
        "payment_mode": "Cash",
        "items": [
            {"garment_type": "Shirt", "qty": 2, "rate": 400},
            {"garment_type": "Blazer", "qty": 1, "rate": 2500},
        ],
    }
    body.update(overrides)
    return client.post("/api/tailoring/orders", json=body)


def test_create_order_numbering_and_totals(client):
    res = make_order(client)
    assert res.status_code == 201
    o = res.get_json()
    assert o["order_number"] == 1001
    assert o["total"] == 3300.0          # 2×400 + 1×2500
    assert o["advance"] == 500.0
    assert o["balance"] == 2800.0
    assert o["stage"] == "In Stitching"
    assert len(o["items"]) == 2

    res2 = make_order(client, customer_name="Second")
    assert res2.get_json()["order_number"] == 1002


def test_create_order_validation(client):
    assert make_order(client, customer_name="").status_code == 400
    assert make_order(client, items=[]).status_code == 400
    assert make_order(client, advance=99999).status_code == 400
    assert make_order(client, items=[{"garment_type": "Shirt", "qty": 0, "rate": 100}]).status_code == 400


def test_item_stage_updates_and_derived_stage(client):
    o = make_order(client).get_json()
    shirt, blazer = o["items"]

    # Move blazer forward — order stays at earliest stage (In Stitching)
    res = client.patch(f"/api/tailoring/items/{blazer['id']}/stage",
                       json={"stage": "Trial Ready"})
    assert res.status_code == 200
    assert res.get_json()["stage"] == "In Stitching"

    # Move shirt forward too — now order is Trial Ready
    res = client.patch(f"/api/tailoring/items/{shirt['id']}/stage",
                       json={"stage": "Trial Ready"})
    assert res.get_json()["stage"] == "Trial Ready"

    # Invalid stage rejected
    res = client.patch(f"/api/tailoring/items/{shirt['id']}/stage",
                       json={"stage": "Bogus"})
    assert res.status_code == 400

    # Bulk: mark whole order Delivered
    res = client.patch(f"/api/tailoring/orders/{o['id']}/stage",
                       json={"stage": "Delivered"})
    assert res.get_json()["stage"] == "Delivered"
    assert all(i["stage"] == "Delivered" for i in res.get_json()["items"])


def test_list_filters_and_counts(client):
    a = make_order(client).get_json()
    make_order(client, customer_name="Patil", mobile="9000000001")
    client.patch(f"/api/tailoring/orders/{a['id']}/stage", json={"stage": "Delivered"})

    data = client.get("/api/tailoring/orders").get_json()
    assert data["counts"]["total"] == 2
    assert data["counts"]["stages"]["Delivered"] == 1
    assert data["counts"]["stages"]["In Stitching"] == 1

    data = client.get("/api/tailoring/orders?stage=Delivered").get_json()
    assert len(data["orders"]) == 1
    assert data["orders"][0]["id"] == a["id"]

    data = client.get("/api/tailoring/orders?q=Patil").get_json()
    assert len(data["orders"]) == 1
    assert data["orders"][0]["customer_name"] == "Patil"


def test_overdue_counting(client):
    make_order(client, delivery_date="2020-01-01")   # long past
    data = client.get("/api/tailoring/orders?due=overdue").get_json()
    assert len(data["orders"]) == 1
    assert data["counts"]["overdue"] == 1


def test_payment_update(client):
    o = make_order(client).get_json()
    res = client.patch(f"/api/tailoring/orders/{o['id']}/payment",
                       json={"advance": 3300, "payment_mode": "Phone Pay"})
    assert res.status_code == 200
    u = res.get_json()
    assert u["balance"] == 0.0
    assert u["payment_mode"] == "Phone Pay"

    # Cannot pay more than total
    res = client.patch(f"/api/tailoring/orders/{o['id']}/payment",
                       json={"advance": 5000})
    assert res.status_code == 400


def test_update_order_preserves_kept_item_stage(client):
    o = make_order(client).get_json()
    shirt = o["items"][0]
    client.patch(f"/api/tailoring/items/{shirt['id']}/stage",
                 json={"stage": "Full Stitched"})

    # Edit: keep shirt (by id) with new rate, drop blazer, add kurta
    res = client.put(f"/api/tailoring/orders/{o['id']}", json={
        "customer_name": "Bawaskar",
        "advance": 0,
        "items": [
            {"id": shirt["id"], "garment_type": "Shirt", "qty": 2, "rate": 450},
            {"garment_type": "Kurta", "qty": 1, "rate": 800},
        ],
    })
    assert res.status_code == 200
    u = res.get_json()
    assert u["total"] == 1700.0          # 2×450 + 800
    by_type = {i["garment_type"]: i for i in u["items"]}
    assert set(by_type) == {"Shirt", "Kurta"}
    assert by_type["Shirt"]["stage"] == "Full Stitched"   # survived the edit
    assert by_type["Kurta"]["stage"] == "In Stitching"


def test_photo_upload_and_delete(client, tmp_path):
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    o = make_order(client).get_json()

    buf = io.BytesIO()
    Image.new("RGB", (2000, 1500), (180, 30, 30)).save(buf, "JPEG")
    buf.seek(0)
    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (buf, "cloth.jpg")},
                      content_type="multipart/form-data")
    assert res.status_code == 201
    photos = res.get_json()["photos"]
    assert len(photos) == 1

    # Saved file exists and was resized to the max dimension
    path = tmp_path / "uploads" / photos[0]["filename"]
    assert path.exists()
    with Image.open(path) as saved:
        assert max(saved.size) <= 1400

    # Served over the public photo route
    res = client.get(f"/tailoring/photos/{photos[0]['filename']}")
    assert res.status_code == 200
    res.close()   # release the file handle so Windows allows deletion below

    # Delete removes DB row and file
    res = client.delete(f"/api/tailoring/photos/{photos[0]['id']}")
    assert res.status_code == 200
    assert not path.exists()

    # Garbage upload rejected
    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (io.BytesIO(b"not an image"), "x.jpg")},
                      content_type="multipart/form-data")
    assert res.status_code == 400


def test_per_item_photos_and_multiple(client):
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    o = make_order(client).get_json()
    shirt = o["items"][0]

    def png():
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), (10, 90, 200)).save(buf, "JPEG")
        buf.seek(0)
        return buf

    # Two photos on the shirt line (e.g. two different shirts)
    for _ in range(2):
        res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                          data={"photo": (png(), "cloth.jpg"), "item_id": str(shirt["id"])},
                          content_type="multipart/form-data")
        assert res.status_code == 201

    # One general (whole-order) photo
    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (png(), "cloth.jpg")},
                      content_type="multipart/form-data")
    assert res.status_code == 201
    u = res.get_json()

    by_type = {i["garment_type"]: i for i in u["items"]}
    assert len(by_type["Shirt"]["photos"]) == 2
    assert len(by_type["Blazer"]["photos"]) == 0
    assert len(u["general_photos"]) == 1
    assert len(u["photos"]) == 3

    # item_id must belong to this order
    other = make_order(client, customer_name="Other").get_json()
    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (png(), "c.jpg"), "item_id": str(other['items'][0]['id'])},
                      content_type="multipart/form-data")
    assert res.status_code == 400

    # Removing the shirt line on edit keeps its photos as general (order-level)
    res = client.put(f"/api/tailoring/orders/{o['id']}", json={
        "customer_name": "Bawaskar",
        "advance": 0,
        "items": [{"id": o["items"][1]["id"], "garment_type": "Blazer", "qty": 1, "rate": 2500}],
    })
    assert res.status_code == 200
    u = res.get_json()
    assert len(u["photos"]) == 3
    assert len(u["general_photos"]) == 3


def test_photo_item_id_migration(tmp_path, monkeypatch):
    """Old DBs without the item_id column get it added on init."""
    import sqlite3
    import db.tailoring as tdb

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE tailoring_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        created_at TEXT)""")
    conn.commit()
    conn.close()

    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", path)
    tdb.init_tailoring_db()

    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tailoring_photos)").fetchall()}
    conn.close()
    assert "item_id" in cols


def test_receipt_page(client):
    o = make_order(client).get_json()
    res = client.get(f"/tailoring/share/{o['order_number']}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Tailoring Needs" in html
    assert "Bawaskar" in html
    assert "Shirt" in html and "Blazer" in html

    assert client.get("/tailoring/share/99999").status_code == 404


def test_delete_order(client):
    o = make_order(client).get_json()
    res = client.delete(f"/api/tailoring/orders/{o['id']}")
    assert res.status_code == 200
    assert client.get(f"/api/tailoring/orders/{o['id']}").status_code == 404


def test_staff_can_delete_order(client):
    o = make_order(client).get_json()
    with client.session_transaction() as sess:
        sess["role"] = "staff"
    res = client.delete(f"/api/tailoring/orders/{o['id']}")
    assert res.status_code == 200
    assert client.get(f"/api/tailoring/orders/{o['id']}").status_code == 404
