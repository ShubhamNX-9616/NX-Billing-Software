"""Phase 2 tests for the Measurements trial: customers, measurements, photos
and the print slip. Reuses the temp-DB `client` fixture from test_measurements,
so billing.db, tailoring.db and the real measurements.db are never touched.
"""
import io

import pytest
from PIL import Image

from test_measurements import _login_as, client  # noqa: F401  (fixture import)


@pytest.fixture
def admin(client):  # noqa: F811
    _login_as(client, "admin")
    return client


def _add_customer(c, name="Ravi Kumar", mobile="9876543210", **extra):
    resp = c.post("/api/measurements/customers",
                  json={"name": name, "mobile": mobile, **extra})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _add_measurement(c, customer_id, garment="shirt", values=None, **extra):
    body = {"garment_type": garment,
            "values": values if values is not None else {"length": "30", "chest": "40"},
            **extra}
    return c.post(f"/api/measurements/customers/{customer_id}/measurements", json=body)


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "PNG")
    buf.seek(0)
    return buf


def _upload(c, measurement_id, name="fabric.png"):
    return c.post(f"/api/measurements/{measurement_id}/photo",
                  data={"photo": (_png(), name)}, content_type="multipart/form-data")


def test_meta_lists_garments_and_statuses(admin):
    data = admin.get("/api/measurements/meta").get_json()
    assert {g["type"] for g in data["garments"]} == {
        "shirt", "pant", "kurta", "suit", "jacket", "pyjama"}
    assert data["statuses"][0] == "Measured"
    shirt = next(g for g in data["garments"] if g["type"] == "shirt")
    assert any(f["key"] == "x_chest" for f in shirt["fields"])


def test_create_customer_normalizes_mobile(admin):
    c = _add_customer(admin, mobile="+91 98765 43210")
    assert c["mobile"] == "9876543210"
    assert c["measurements"] == []


def test_create_customer_validation(admin):
    assert admin.post("/api/measurements/customers",
                      json={"name": "", "mobile": "9876543210"}).status_code == 400
    assert admin.post("/api/measurements/customers",
                      json={"name": "A", "mobile": "12345"}).status_code == 400


def test_duplicate_mobile_returns_existing_customer(admin):
    first = _add_customer(admin)
    resp = admin.post("/api/measurements/customers",
                      json={"name": "Someone Else", "mobile": "098765 43210"})
    assert resp.status_code == 409
    assert resp.get_json()["customer"]["id"] == first["id"]


def test_search_by_name_and_mobile(admin):
    _add_customer(admin, "Ravi Kumar", "9876543210")
    _add_customer(admin, "Amit Shah", "9123456780")
    assert [c["name"] for c in admin.get("/api/measurements/customers?q=ami").get_json()] \
        == ["Amit Shah"]
    assert [c["name"] for c in admin.get("/api/measurements/customers?q=98765").get_json()] \
        == ["Ravi Kumar"]
    assert len(admin.get("/api/measurements/customers").get_json()) == 2


def test_update_customer_and_mobile_clash(admin):
    a = _add_customer(admin, "A", "9876543210")
    _add_customer(admin, "B", "9123456780")
    ok = admin.put(f"/api/measurements/customers/{a['id']}",
                   json={"name": "A Renamed", "mobile": "9876543210", "address": "Pune"})
    assert ok.status_code == 200 and ok.get_json()["name"] == "A Renamed"
    clash = admin.put(f"/api/measurements/customers/{a['id']}",
                      json={"name": "A", "mobile": "9123456780"})
    assert clash.status_code == 409


def test_create_measurement_saves_values_and_defaults(admin):
    cust = _add_customer(admin)
    resp = _add_measurement(admin, cust["id"], trial_date="2026-12-01",
                            delivery_date="2026-12-10", notes=" slim fit ")
    assert resp.status_code == 201
    m = resp.get_json()
    assert m["values"] == {"length": "30", "chest": "40"}
    assert m["status"] == "Measured"
    assert m["notes"] == "slim fit"
    assert m["order_date"]          # defaulted to today
    assert m["delivery_date"] == "2026-12-10"
    got = admin.get(f"/api/measurements/customers/{cust['id']}").get_json()
    assert [x["id"] for x in got["measurements"]] == [m["id"]]


def test_measurement_validation(admin):
    cust = _add_customer(admin)
    assert _add_measurement(admin, cust["id"], garment="cape").status_code == 400
    assert _add_measurement(admin, cust["id"], delivery_date="not-a-date").status_code == 400
    assert _add_measurement(admin, cust["id"],
                            values={"shirt_type": "Nonsense"}).status_code == 400
    assert _add_measurement(admin, cust["id"],
                            values={"length": "9" * 50}).status_code == 400
    assert admin.post("/api/measurements/customers/999/measurements",
                      json={"garment_type": "shirt"}).status_code == 404


def test_unknown_value_keys_are_dropped(admin):
    cust = _add_customer(admin)
    m = _add_measurement(admin, cust["id"],
                         values={"length": "30", "bogus": "1", "shirt_type": "Manela"}).get_json()
    assert m["values"] == {"length": "30", "shirt_type": "Manela"}


def test_update_measurement_keeps_garment_type(admin):
    cust = _add_customer(admin)
    m = _add_measurement(admin, cust["id"]).get_json()
    resp = admin.put(f"/api/measurements/{m['id']}", json={
        "garment_type": "pant", "values": {"length": "32"}, "notes": "",
        "order_date": m["order_date"], "delivery_date": "2026-12-20"})
    assert resp.status_code == 200
    out = resp.get_json()
    assert out["garment_type"] == "shirt"
    assert out["values"] == {"length": "32"}
    assert out["delivery_date"] == "2026-12-20"


def test_status_update(admin):
    cust = _add_customer(admin)
    m = _add_measurement(admin, cust["id"]).get_json()
    ok = admin.patch(f"/api/measurements/{m['id']}/status", json={"status": "Trial Ready"})
    assert ok.status_code == 200 and ok.get_json()["status"] == "Trial Ready"
    assert admin.patch(f"/api/measurements/{m['id']}/status",
                       json={"status": "Nope"}).status_code == 400
    assert admin.patch("/api/measurements/999/status",
                       json={"status": "Delivered"}).status_code == 404


def test_photo_upload_replace_and_delete(admin, tmp_path):
    cust = _add_customer(admin)
    m = _add_measurement(admin, cust["id"]).get_json()
    up = _upload(admin, m["id"])
    assert up.status_code == 201
    url = up.get_json()["image_url"]
    assert url.startswith("/measurements/photos/")
    assert admin.get(url).status_code == 200
    folder = tmp_path / "uploads"
    assert len(list(folder.iterdir())) == 1

    _upload(admin, m["id"], "again.png")      # replaces, doesn't pile up
    assert len(list(folder.iterdir())) == 1

    assert admin.delete(f"/api/measurements/{m['id']}/photo").status_code == 200
    assert list(folder.iterdir()) == []
    assert admin.get(f"/api/measurements/{m['id']}").get_json()["image_url"] is None


def test_photo_rejects_non_image(admin):
    cust = _add_customer(admin)
    m = _add_measurement(admin, cust["id"]).get_json()
    resp = admin.post(f"/api/measurements/{m['id']}/photo",
                      data={"photo": (io.BytesIO(b"not an image"), "x.png")},
                      content_type="multipart/form-data")
    assert resp.status_code == 400


def test_delete_measurement_removes_photo_file(admin, tmp_path):
    cust = _add_customer(admin)
    m = _add_measurement(admin, cust["id"]).get_json()
    _upload(admin, m["id"])
    assert admin.delete(f"/api/measurements/{m['id']}").status_code == 200
    assert list((tmp_path / "uploads").iterdir()) == []
    assert admin.get(f"/api/measurements/{m['id']}").status_code == 404


def test_delete_customer_cascades(admin, tmp_path):
    cust = _add_customer(admin)
    m = _add_measurement(admin, cust["id"]).get_json()
    _upload(admin, m["id"])
    assert admin.delete(f"/api/measurements/customers/{cust['id']}").status_code == 200
    assert admin.get("/api/measurements/status").get_json() == {"customers": 0, "measurements": 0}
    assert list((tmp_path / "uploads").iterdir()) == []


def test_print_slip_renders_values(admin):
    cust = _add_customer(admin, "Ravi Kumar")
    m = _add_measurement(admin, cust["id"], garment="shirt", values={
        "no_of_shirts": "2", "shirt_type": "Manela", "length": "30",
        "front_1": "5", "front_2": "6", "back_1": "7"}).get_json()
    resp = admin.get(f"/measurements/{m['id']}/print")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "Ravi Kumar" in html and "Manela" in html
    assert "No of Shirts: 2" in html
    assert admin.get("/measurements/9999/print").status_code == 404


def test_new_endpoints_require_login(client):  # noqa: F811
    assert client.get("/api/measurements/customers").status_code in (401, 403)
    assert client.post("/api/measurements/customers", json={}).status_code in (401, 403)
    assert client.get("/measurements/1/print").status_code == 302


def test_photo_path_traversal_blocked(admin):
    assert admin.get("/measurements/photos/..%2F..%2Fapp.py").status_code == 404
