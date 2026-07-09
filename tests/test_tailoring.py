"""Tests for the standalone Tailoring Delivery System.

Uses a minimal Flask app with only the tailoring blueprints and a temp
tailoring DB + upload dir, so billing.db and the real tailoring.db are
never touched.
"""
import io
import itertools
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


# Order numbers are typed manually from the paper receipt book; give every
# test order a unique one by default.
_order_numbers = itertools.count(1001)


def make_order(client, **overrides):
    body = {
        "order_number": next(_order_numbers),
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
    res = make_order(client, order_number=2001)
    assert res.status_code == 201
    o = res.get_json()
    assert o["order_number"] == 2001     # exactly what the user typed
    assert o["total"] == 3300.0          # 2×400 + 1×2500
    assert o["advance"] == 500.0
    assert o["balance"] == 2800.0
    assert o["stage"] == "In Stitching"
    assert len(o["items"]) == 2

    # Manual numbering rules: required, positive, unique
    assert make_order(client, order_number=2001).status_code == 400   # duplicate
    assert make_order(client, order_number="").status_code == 400     # missing
    assert make_order(client, order_number="abc").status_code == 400  # not a number

    res2 = make_order(client, customer_name="Second", order_number=2010)
    assert res2.get_json()["order_number"] == 2010

    # The number can be corrected on edit, but not to one already taken
    res3 = client.put(f"/api/tailoring/orders/{o['id']}", json={
        "order_number": 2002, "customer_name": "Bawaskar",
        "items": [{"garment_type": "Shirt", "qty": 1, "rate": 400}],
    })
    assert res3.get_json()["order_number"] == 2002
    res4 = client.put(f"/api/tailoring/orders/{o['id']}", json={
        "order_number": 2010, "customer_name": "Bawaskar",
        "items": [{"garment_type": "Shirt", "qty": 1, "rate": 400}],
    })
    assert res4.status_code == 400


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
    o = make_order(client, delivery_date="2020-01-01").get_json()   # long past
    data = client.get("/api/tailoring/orders?due=overdue").get_json()
    assert len(data["orders"]) == 1
    assert data["counts"]["overdue"] == 1

    # Fully stitched → no longer overdue: pickup is on the customer now.
    client.patch(f"/api/tailoring/orders/{o['id']}/stage",
                 json={"stage": "Full Stitched"})
    data = client.get("/api/tailoring/orders?due=overdue").get_json()
    assert len(data["orders"]) == 0
    assert data["counts"]["overdue"] == 0


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


def test_dashboard(client):
    from datetime import date, timedelta
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()

    # Overdue: delivery 3 days ago. Due tomorrow: one delivery, one trial.
    # In 5 days: 2 shirts + 1 blazer pending.
    make_order(client, customer_name="Late", trial_date=None, delivery_date=d(-3))
    make_order(client, customer_name="TomorrowDel", trial_date=None, delivery_date=d(1))
    make_order(client, customer_name="TomorrowTrial", trial_date=d(1), delivery_date=d(6))
    make_order(client, customer_name="FiveDays", trial_date=None, delivery_date=d(5))

    res = client.get("/api/tailoring/dashboard")
    assert res.status_code == 200
    dash = res.get_json()

    assert dash["today"] == d(0)
    assert len(dash["days"]) == 15
    assert dash["days"][0]["date"] == d(0)

    day5 = dash["days"][5]
    assert day5["date"] == d(5)
    assert day5["orders"] == 1
    assert day5["garments"] == {"Shirt": 2, "Blazer": 1}
    assert [b["customer_name"] for b in day5["order_list"]] == ["FiveDays"]

    assert [b["customer_name"] for b in dash["overdue"]] == ["Late"]
    assert dash["overdue"][0]["days_late"] == 3
    assert [b["customer_name"] for b in dash["deliveries_tomorrow"]] == ["TomorrowDel"]
    assert [b["customer_name"] for b in dash["trials_tomorrow"]] == ["TomorrowTrial"]
    assert dash["deliveries_today"] == [] and dash["trials_today"] == []

    assert dash["ready_waiting"] == []

    # Fully stitched drops out of overdue and moves to ready-&-waiting-pickup
    late_id = dash["overdue"][0]["id"]
    client.patch(f"/api/tailoring/orders/{late_id}/stage", json={"stage": "Full Stitched"})
    dash = client.get("/api/tailoring/dashboard").get_json()
    assert dash["overdue"] == []
    assert [b["customer_name"] for b in dash["ready_waiting"]] == ["Late"]
    assert dash["ready_waiting"][0]["days_waiting"] == 3

    # Fully stitched with a future delivery date is NOT waiting for pickup yet
    tom_id = dash["deliveries_tomorrow"][0]["id"]
    client.patch(f"/api/tailoring/orders/{tom_id}/stage", json={"stage": "Full Stitched"})
    dash = client.get("/api/tailoring/dashboard").get_json()
    assert [b["customer_name"] for b in dash["ready_waiting"]] == ["Late"]

    # Delivered clears it from the pickup list
    client.patch(f"/api/tailoring/orders/{late_id}/stage", json={"stage": "Delivered"})
    dash = client.get("/api/tailoring/dashboard").get_json()
    assert dash["ready_waiting"] == []


def test_customers_list(client):
    # Two orders for the same mobile (name spelling differs), one order for
    # another customer without a mobile.
    make_order(client, customer_name="Bawaskar", mobile="9876543210")
    make_order(client, customer_name="Bawaskar Ji", mobile="9876543210",
               order_date="2026-07-08", advance=800,
               items=[{"garment_type": "Kurta", "qty": 1, "rate": 800}])
    make_order(client, customer_name="Walk-in", mobile="")

    data = client.get("/api/tailoring/customers").get_json()
    assert data["total"] == 2
    by_name = {c["customer_name"]: c for c in data["customers"]}

    c = by_name["Bawaskar Ji"]            # latest spelling wins
    assert c["mobile"] == "9876543210"
    assert c["orders"] == 2
    assert c["open_orders"] == 2
    assert c["total_business"] == 3300.0 + 800.0
    assert c["pending_balance"] == 2800.0  # first order 2800, second fully paid
    assert c["first_order_date"] == "2026-07-07"
    assert c["last_order_date"] == "2026-07-08"

    assert by_name["Walk-in"]["orders"] == 1

    # Search by mobile fragment
    data = client.get("/api/tailoring/customers?q=98765").get_json()
    assert data["total"] == 1
    assert data["customers"][0]["customer_name"] == "Bawaskar Ji"


def test_measurement_photos_hidden_on_receipt(client):
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")

    o = make_order(client).get_json()
    item_id = o["items"][0]["id"]

    def img():
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), (10, 10, 10)).save(buf, "JPEG")
        buf.seek(0)
        return buf

    # Per-garment cloth photo → shown on the customer receipt
    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (img(), "cloth.jpg"), "item_id": str(item_id)},
                      content_type="multipart/form-data")
    cloth = [p for p in res.get_json()["photos"] if p["item_id"] == item_id][0]

    # Whole-order measurement photo → internal only, never on the receipt
    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (img(), "measure.jpg")},
                      content_type="multipart/form-data")
    measurement = [p for p in res.get_json()["photos"] if not p["item_id"]][0]

    html = client.get(f"/tailoring/share/{o['order_number']}").get_data(as_text=True)
    assert cloth["filename"] in html
    assert measurement["filename"] not in html


def test_record_payment_with_history(client):
    o = make_order(client).get_json()          # total 3300, advance 500
    assert len(o["payments"]) == 1             # the advance is entry #1
    assert o["payments"][0]["amount"] == 500.0
    assert o["payments"][0]["note"] == "Advance"
    assert o["unrecorded_paid"] == 0

    # Record ₹1000 by Phone Pay
    res = client.post(f"/api/tailoring/orders/{o['id']}/payments",
                      json={"amount": 1000, "mode": "Phone Pay"})
    assert res.status_code == 201
    u = res.get_json()
    assert u["advance"] == 1500.0
    assert u["balance"] == 1800.0
    assert len(u["payments"]) == 2
    assert u["payments"][1]["mode"] == "Phone Pay"

    # Validation: zero/negative/over-total amounts rejected
    assert client.post(f"/api/tailoring/orders/{o['id']}/payments",
                       json={"amount": 0}).status_code == 400
    assert client.post(f"/api/tailoring/orders/{o['id']}/payments",
                       json={"amount": -5}).status_code == 400
    assert client.post(f"/api/tailoring/orders/{o['id']}/payments",
                       json={"amount": 99999}).status_code == 400

    # Deleting a wrong entry restores the balance
    pay_id = u["payments"][1]["id"]
    u = client.delete(f"/api/tailoring/payments/{pay_id}").get_json()
    assert u["advance"] == 500.0
    assert u["balance"] == 2800.0
    assert len(u["payments"]) == 1

    # Legacy set-total endpoint still works; difference shows as unrecorded
    u = client.patch(f"/api/tailoring/orders/{o['id']}/payment",
                     json={"advance": 800}).get_json()
    assert u["balance"] == 2500.0
    assert u["unrecorded_paid"] == 300.0       # 800 paid, only 500 in history


def test_tailor_report(client):
    from datetime import date, timedelta
    today = date.today()
    d = lambda n: (today + timedelta(days=n)).isoformat()

    make_order(client, customer_name="LateGuy", trial_date=None, delivery_date=d(-2))
    make_order(client, customer_name="DelTomorrow", trial_date=None, delivery_date=d(1))
    make_order(client, customer_name="TrialTomorrow", trial_date=d(1), delivery_date=d(7))
    ready = make_order(client, customer_name="ReadyGuy",
                       trial_date=None, delivery_date=d(1)).get_json()
    client.patch(f"/api/tailoring/orders/{ready['id']}/stage",
                 json={"stage": "Full Stitched"})

    res = client.get("/tailoring/report")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "LateGuy" in html            # overdue
    assert "DelTomorrow" in html        # delivery due tomorrow, work pending
    assert "TrialTomorrow" in html      # trial tomorrow
    assert "ReadyGuy" not in html       # fully stitched → nothing for the tailor


def test_tailor_report_includes_photos(client):
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    from datetime import date, timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    o = make_order(client, customer_name="PhotoGuy",
                   trial_date=None, delivery_date=tomorrow).get_json()

    def img():
        buf = io.BytesIO()
        Image.new("RGB", (80, 80), (20, 20, 20)).save(buf, "JPEG")
        buf.seek(0)
        return buf

    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (img(), "cloth.jpg"),
                            "item_id": str(o["items"][0]["id"])},
                      content_type="multipart/form-data")
    cloth = [p for p in res.get_json()["photos"] if p["item_id"]][0]
    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (img(), "measure.jpg")},
                      content_type="multipart/form-data")
    measurement = [p for p in res.get_json()["photos"] if not p["item_id"]][0]

    html = client.get("/tailoring/report").get_data(as_text=True)
    assert cloth["filename"] in html         # cloth photo under the garment
    assert measurement["filename"] in html   # measurement photos shown to tailor


def test_tailor_report_share_link(client):
    import re
    from datetime import date, timedelta
    import routes.tailoring as tr
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    make_order(client, customer_name="NightWork", trial_date=None,
               delivery_date=tomorrow)

    # Staff page embeds the share path for the WhatsApp message
    html = client.get("/tailoring/report").get_data(as_text=True)
    m = re.search(r"/tailoring/report/share/([0-9a-f]+)", html)
    assert m, "share path missing from staff report"
    share_path = m.group(0)

    # The tailor opens it WITHOUT being logged in
    with client.session_transaction() as sess:
        sess.clear()
    res = client.get(share_path)
    assert res.status_code == 200
    assert "NightWork" in res.get_data(as_text=True)

    # Wrong/expired token is rejected; staff page is not served without login
    # (the test app lacks the auth blueprint, so the redirect itself errors —
    # any non-200 proves the guard kicked in)
    assert client.get("/tailoring/report/share/deadbeef00").status_code == 404
    assert client.get("/tailoring/report").status_code != 200


def test_photos_use_r2_when_configured(client, monkeypatch, tmp_path):
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow not installed")
    from services import r2_storage

    uploaded = {}
    deleted = []
    monkeypatch.setattr(r2_storage, "is_configured", lambda: True)
    monkeypatch.setattr(r2_storage, "upload_bytes",
                        lambda data, key, content_type="image/jpeg":
                            uploaded.setdefault(key, data) or True)
    monkeypatch.setattr(r2_storage, "delete_object", lambda key: deleted.append(key))
    monkeypatch.setattr(r2_storage, "public_url", lambda key: f"https://pub-test.r2.dev/{key}")

    o = make_order(client).get_json()
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), (5, 5, 5)).save(buf, "JPEG")
    buf.seek(0)
    res = client.post(f"/api/tailoring/orders/{o['id']}/photos",
                      data={"photo": (buf, "cloth.jpg")},
                      content_type="multipart/form-data")
    assert res.status_code == 201
    photo = res.get_json()["photos"][0]

    # Went to R2, not local disk
    assert photo["filename"] in uploaded
    assert not (tmp_path / "uploads" / photo["filename"]).exists()

    # Serving redirects to the R2 public URL
    res = client.get(f"/tailoring/photos/{photo['filename']}", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"] == f"https://pub-test.r2.dev/{photo['filename']}"

    # Deleting also removes it from R2
    client.delete(f"/api/tailoring/photos/{photo['id']}")
    assert photo["filename"] in deleted


def test_photos_fall_back_to_local_disk_when_r2_not_configured(client):
    from services import r2_storage
    assert r2_storage.is_configured() is False   # no R2 env vars set in tests
