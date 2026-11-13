"""Billing phase 1 tests for the Measurements trial: auto-numbered orders (general
and suits numbered separately), garment lines with rates, payments, cloth balance.

Reuses the temp-DB `client` fixture, so billing.db, tailoring.db and the real
measurements.db are never touched.
"""
import sqlite3
from datetime import date, timedelta

import pytest

from test_measurements import _login_as, client  # noqa: F401  (fixture import)


@pytest.fixture
def admin(client):  # noqa: F811
    _login_as(client, "admin")
    return client


def _cust(c, name="Ravi Kumar", mobile="9876543210"):
    r = c.post("/api/measurements/customers", json={"name": name, "mobile": mobile})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _item(garment="shirt", rate=500, values=None, **extra):
    return {"garment_type": garment, "rate": rate,
            "values": values if values is not None else {"length": "30"}, **extra}


def _order(c, cust, items=None, **extra):
    body = {"customer_id": cust["id"], "items": [_item()] if items is None else items, **extra}
    return c.post("/api/measurements/orders", json=body)


def _day(offset):
    import routes.measurements as mr
    return (date.fromisoformat(mr._today_ist()) + timedelta(days=offset)).isoformat()


# ---------------------------------------------------------------------------
# Schema / migration
# ---------------------------------------------------------------------------
def test_billing_tables_live_in_measurements_db_only(client):  # noqa: F811
    import db.measurements as mdb
    conn = sqlite3.connect(mdb.MEASUREMENTS_DB_PATH)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"m_orders", "m_payments", "m_rates", "m_counters"} <= tables
    assert not any(t.startswith("tailoring_") for t in tables)


def test_migration_upgrades_a_phase3_database(tmp_path, monkeypatch):
    """measurements.db files created by phases 1-3 have no billing columns."""
    import db.measurements as mdb
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE m_customers (id INTEGER PRIMARY KEY AUTOINCREMENT, mobile TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL, address TEXT, created_at TEXT);
        CREATE TABLE m_measurements (id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL, garment_type TEXT NOT NULL,
            values_json TEXT NOT NULL DEFAULT '{}', notes TEXT, image TEXT, order_date TEXT,
            trial_date TEXT, delivery_date TEXT, status TEXT NOT NULL DEFAULT 'Measured',
            created_at TEXT, updated_at TEXT);
        INSERT INTO m_customers (mobile, name) VALUES ('9876543210', 'Old Customer');
        INSERT INTO m_measurements (customer_id, garment_type) VALUES (1, 'shirt');
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(mdb, "MEASUREMENTS_DB_PATH", path)
    mdb.init_measurements_db()
    mdb.init_measurements_db()          # idempotent
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(m_measurements)")}
    row = conn.execute("SELECT order_id, qty, rate, amount FROM m_measurements").fetchone()
    conn.close()
    assert {"order_id", "qty", "rate", "amount"} <= cols
    assert row == (None, 1, 0, 0)       # the old measurement survives, unbilled


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------
def test_order_numbers_start_at_one_and_count_up(admin):
    cust = _cust(admin)
    a = _order(admin, cust).get_json()
    b = _order(admin, cust).get_json()
    assert (a["order_number"], b["order_number"]) == (1, 2)
    assert (a["label"], b["label"]) == ("M-0001", "M-0002")


def test_suit_orders_have_their_own_sequence(admin):
    cust = _cust(admin)
    _order(admin, cust)
    _order(admin, cust)
    s1 = _order(admin, cust, [_item("suit", 8000)], order_type="suit").get_json()
    s2 = _order(admin, cust, [_item("suit", 8000)], order_type="suit").get_json()
    g3 = _order(admin, cust).get_json()
    assert (s1["order_number"], s1["label"]) == (1, "MS-0001")
    assert s2["order_number"] == 2
    assert g3["order_number"] == 3          # the general sequence is unaffected


def test_deleted_order_number_is_not_reused(admin):
    cust = _cust(admin)
    a = _order(admin, cust).get_json()
    assert admin.delete(f"/api/measurements/orders/{a['id']}").status_code == 200
    assert _order(admin, cust).get_json()["order_number"] == 2


def test_failed_create_does_not_burn_a_number(admin, monkeypatch):
    import routes.measurement_orders as mo
    cust = _cust(admin)
    real = mo._insert_item

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(mo, "_insert_item", boom)
    assert _order(admin, cust).status_code == 500
    monkeypatch.setattr(mo, "_insert_item", real)
    assert admin.get("/api/measurements/orders").get_json() == []
    assert _order(admin, cust).get_json()["order_number"] == 1   # no gap


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def test_totals_qty_cloth_and_advance(admin):
    cust = _cust(admin)
    o = _order(admin, cust, [
        _item("shirt", 500, {"no_of_shirts": "3", "length": "30"}),   # 3 x 500
        _item("pant", 700),                                           # 1 x 700
    ], cloth_balance=300, advance=1000, payment_mode="UPI").get_json()
    assert o["total"] == 2200
    assert o["cloth_balance"] == 300 and o["final_total"] == 2500
    assert o["advance"] == 1000 and o["balance"] == 1500
    shirt = o["items"][0]
    assert (shirt["qty"], shirt["rate"], shirt["amount"]) == (3, 500, 1500)
    assert len(o["payments"]) == 1
    assert o["payments"][0]["amount"] == 1000 and o["payments"][0]["note"] == "Advance"
    assert o["payments"][0]["mode"] == "UPI" and o["payment_mode"] == "UPI"


def test_no_advance_means_no_payment_row(admin):
    o = _order(admin, _cust(admin)).get_json()
    assert o["payments"] == [] and o["advance"] == 0 and o["balance"] == 500


@pytest.mark.parametrize("extra,msg", [
    ({"advance": 9999}, "cannot exceed"),
    ({"advance": -5}, "negative"),
    ({"cloth_balance": -1}, "negative"),
    ({"advance": "abc"}, "number"),
    ({"order_type": "weird"}, "general or suit"),
    ({"trial_date": "31-12-2026"}, "Invalid trial date"),
    ({"items": []}, "at least one garment"),
    ({"items": [{"garment_type": "cape"}]}, "Choose a garment"),
    ({"items": [{"garment_type": "shirt", "rate": "x"}]}, "Rate must be a number"),
    ({"items": [{"garment_type": "shirt", "rate": -4}]}, "Rate cannot be negative"),
])
def test_create_order_validation(admin, extra, msg):
    cust = _cust(admin)
    r = _order(admin, cust, **extra)
    assert r.status_code == 400
    assert msg in r.get_json()["error"]
    assert admin.get("/api/measurements/orders").get_json() == []   # nothing half-saved


def test_create_requires_a_real_customer(admin):
    r = admin.post("/api/measurements/orders", json={"customer_id": 999, "items": [_item()]})
    assert r.status_code == 400


def test_rate_is_remembered_and_prefilled(admin):
    cust = _cust(admin)
    _order(admin, cust, [_item("shirt", 450)])
    meta = admin.get("/api/measurements/meta").get_json()
    assert meta["rates"]["general"]["shirt"] == 450
    assert "suit" in meta["order_types"] and "Cash" in meta["payment_modes"]
    # blank rate on the next order picks up the saved one
    o = _order(admin, cust, [{"garment_type": "shirt", "values": {}}]).get_json()
    assert o["items"][0]["rate"] == 450 and o["total"] == 450
    # an explicit 0 is honoured for that order but does not wipe the default
    z = _order(admin, cust, [_item("shirt", 0)]).get_json()
    assert z["total"] == 0
    assert admin.get("/api/measurements/meta").get_json()["rates"]["general"]["shirt"] == 450


def test_rates_are_kept_separately_per_order_type(admin):
    cust = _cust(admin)
    _order(admin, cust, [_item("suit", 8000)], order_type="suit")
    rates = admin.get("/api/measurements/meta").get_json()["rates"]
    assert rates["suit"]["suit"] == 8000 and "suit" not in rates["general"]


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def test_record_and_delete_payments(admin):
    o = _order(admin, _cust(admin), advance=100).get_json()          # total 500
    r = admin.post(f"/api/measurements/orders/{o['id']}/payments",
                   json={"amount": 150, "mode": "Cash", "note": "Second"})
    assert r.status_code == 201
    p = r.get_json()
    assert p["advance"] == 250 and p["balance"] == 250 and len(p["payments"]) == 2
    pay_id = p["payments"][1]["id"]
    back = admin.delete(f"/api/measurements/payments/{pay_id}").get_json()
    assert back["advance"] == 100 and back["balance"] == 400


@pytest.mark.parametrize("body,msg", [
    ({"amount": 0}, "greater than zero"),
    ({"amount": -5}, "negative"),
    ({"amount": "x"}, "number"),
    ({"amount": 9999}, "more than the order total"),
    ({"amount": 10, "paid_at": "nope"}, "Invalid payment date"),
])
def test_payment_validation(admin, body, msg):
    o = _order(admin, _cust(admin)).get_json()
    r = admin.post(f"/api/measurements/orders/{o['id']}/payments", json=body)
    assert r.status_code == 400 and msg in r.get_json()["error"]
    assert admin.get(f"/api/measurements/orders/{o['id']}").get_json()["advance"] == 0


def test_cannot_overpay_across_several_payments(admin):
    o = _order(admin, _cust(admin), advance=400).get_json()          # total 500
    r = admin.post(f"/api/measurements/orders/{o['id']}/payments", json={"amount": 101})
    assert r.status_code == 400
    assert admin.post(f"/api/measurements/orders/{o['id']}/payments",
                      json={"amount": 100}).get_json()["balance"] == 0


def test_cloth_balance_update_and_guard(admin):
    o = _order(admin, _cust(admin), advance=400).get_json()          # total 500
    r = admin.put(f"/api/measurements/orders/{o['id']}", json={"cloth_balance": 200})
    assert r.status_code == 200
    got = r.get_json()
    assert got["final_total"] == 700 and got["balance"] == 300
    # cannot drop the cloth so low that more is paid than owed
    admin.post(f"/api/measurements/orders/{o['id']}/payments", json={"amount": 300})
    bad = admin.put(f"/api/measurements/orders/{o['id']}", json={"cloth_balance": 0})
    assert bad.status_code == 400 and "more than the new total" in bad.get_json()["error"]
    assert admin.get(f"/api/measurements/orders/{o['id']}").get_json()["cloth_balance"] == 200


# ---------------------------------------------------------------------------
# Order header, dates and the dashboard
# ---------------------------------------------------------------------------
def test_order_dates_flow_to_garments_and_dashboard(admin):
    cust = _cust(admin)
    o = _order(admin, cust, [_item("shirt"), _item("pant")],
               order_date=_day(0), trial_date=_day(1), delivery_date=_day(2)).get_json()
    assert {i["delivery_date"] for i in o["items"]} == {_day(2)}
    dash = admin.get("/api/measurements/dashboard").get_json()
    assert len(dash["trials_tomorrow"]) == 2
    assert dash["days"][2]["orders"] == 2
    # moving the delivery moves both garments
    r = admin.put(f"/api/measurements/orders/{o['id']}", json={"delivery_date": _day(5)})
    assert {i["delivery_date"] for i in r.get_json()["items"]} == {_day(5)}
    assert admin.get("/api/measurements/dashboard").get_json()["days"][5]["orders"] == 2


def test_order_update_is_partial_and_validates(admin):
    o = _order(admin, _cust(admin), trial_date=_day(1), notes="keep", payment_mode="Cash").get_json()
    r = admin.put(f"/api/measurements/orders/{o['id']}", json={"delivery_date": _day(3)}).get_json()
    assert r["trial_date"] == _day(1) and r["notes"] == "keep" and r["delivery_date"] == _day(3)
    assert admin.put(f"/api/measurements/orders/{o['id']}",
                     json={"trial_date": "garbage"}).status_code == 400
    cleared = admin.put(f"/api/measurements/orders/{o['id']}", json={"trial_date": ""}).get_json()
    assert cleared["trial_date"] is None
    assert admin.put("/api/measurements/orders/999", json={}).status_code == 404


def test_order_delivered_when_every_garment_delivered(admin):
    o = _order(admin, _cust(admin), [_item("shirt"), _item("pant")]).get_json()
    a, b = o["items"][0]["id"], o["items"][1]["id"]
    admin.patch(f"/api/measurements/{a}/status", json={"status": "Delivered"})
    mid = admin.get(f"/api/measurements/orders/{o['id']}").get_json()
    assert mid["delivered_at"] is None and mid["status"] == "Measured"
    admin.patch(f"/api/measurements/{b}/status", json={"status": "Delivered"})
    done = admin.get(f"/api/measurements/orders/{o['id']}").get_json()
    assert done["delivered_at"] and done["status"] == "Delivered"
    admin.patch(f"/api/measurements/{b}/status", json={"status": "Trial Ready"})
    back = admin.get(f"/api/measurements/orders/{o['id']}").get_json()
    assert back["delivered_at"] is None and back["status"] == "Trial Ready"


# ---------------------------------------------------------------------------
# Garment lines on an order
# ---------------------------------------------------------------------------
def test_add_garment_to_existing_order(admin):
    o = _order(admin, _cust(admin), delivery_date=_day(4)).get_json()
    r = admin.post(f"/api/measurements/orders/{o['id']}/items", json=_item("kurta", 900))
    assert r.status_code == 201
    got = r.get_json()
    assert got["total"] == 1400 and len(got["items"]) == 2
    assert got["items"][1]["delivery_date"] == _day(4)        # inherits the order's dates
    assert admin.post(f"/api/measurements/orders/{o['id']}/items",
                      json={"garment_type": "cape"}).status_code == 400


def test_editing_a_garment_reprices_the_order(admin):
    o = _order(admin, _cust(admin), delivery_date=_day(3), advance=100).get_json()
    mid = o["items"][0]["id"]
    r = admin.put(f"/api/measurements/{mid}", json={
        "values": {"no_of_shirts": "2", "length": "31"}, "rate": 600,
        "delivery_date": _day(9)})                              # dates here must be ignored
    assert r.status_code == 200
    got = admin.get(f"/api/measurements/orders/{o['id']}").get_json()
    assert got["total"] == 1200 and got["balance"] == 1100
    assert got["items"][0]["delivery_date"] == _day(3)
    # lowering the price below what is already paid is refused
    admin.post(f"/api/measurements/orders/{o['id']}/payments", json={"amount": 1100})
    bad = admin.put(f"/api/measurements/{mid}", json={"values": {}, "rate": 100})
    assert bad.status_code == 400 and "more than the new total" in bad.get_json()["error"]
    assert admin.get(f"/api/measurements/orders/{o['id']}").get_json()["total"] == 1200


def test_deleting_a_garment_reprices_and_guards(admin):
    o = _order(admin, _cust(admin), [_item("shirt", 500), _item("pant", 700)],
               advance=1000).get_json()
    shirt, pant = o["items"][0]["id"], o["items"][1]["id"]
    # removing the pant leaves 500 owed but 1000 paid -> refused
    assert admin.delete(f"/api/measurements/{pant}").status_code == 400
    admin.delete(f"/api/measurements/payments/{o['payments'][0]['id']}")
    assert admin.delete(f"/api/measurements/{pant}").status_code == 200
    got = admin.get(f"/api/measurements/orders/{o['id']}").get_json()
    assert got["total"] == 500 and len(got["items"]) == 1
    # the last garment cannot be removed on its own
    last = admin.delete(f"/api/measurements/{shirt}")
    assert last.status_code == 400 and "delete the order" in last.get_json()["error"]


def test_unbilled_measurements_still_work_as_before(admin):
    cust = _cust(admin)
    r = admin.post(f"/api/measurements/customers/{cust['id']}/measurements",
                   json={"garment_type": "shirt", "values": {}, "delivery_date": _day(2)})
    m = r.get_json()
    assert m["order_id"] is None and m["rate"] == 0 and m["amount"] == 0
    upd = admin.put(f"/api/measurements/{m['id']}",
                    json={"values": {}, "delivery_date": _day(6)}).get_json()
    assert upd["delivery_date"] == _day(6)                      # standalone rows keep own dates
    assert admin.delete(f"/api/measurements/{m['id']}").status_code == 200


# ---------------------------------------------------------------------------
# Listing, deleting, customers
# ---------------------------------------------------------------------------
def test_list_orders_filters(admin):
    ravi = _cust(admin, "Ravi Kumar", "9876543210")
    sunil = _cust(admin, "Sunil Shah", "9123456789")
    o1 = _order(admin, ravi).get_json()
    _order(admin, sunil, [_item("suit", 8000)], order_type="suit")
    def ids(qs):
        return [x["label"] for x in admin.get("/api/measurements/orders" + qs).get_json()]
    assert ids("") == ["MS-0001", "M-0001"]                      # newest first
    assert ids("?q=sunil") == ["MS-0001"]
    assert ids("?q=98765") == ["M-0001"]
    assert ids("?q=1") == ["MS-0001", "M-0001"]                  # number match, both have number 1
    assert ids("?type=suit") == ["MS-0001"]
    assert ids(f"?customer_id={ravi['id']}") == ["M-0001"]
    admin.patch(f"/api/measurements/{o1['items'][0]['id']}/status", json={"status": "Delivered"})
    assert ids("?open=1") == ["MS-0001"]
    row = admin.get("/api/measurements/orders?type=suit").get_json()[0]
    assert row["customer_name"] == "Sunil Shah" and row["total"] == 8000
    assert row["garments"] == [{"garment_type": "suit", "label": "Suit", "qty": 1}]


def test_delete_order_removes_everything_including_photos(admin, tmp_path):
    import io
    import os
    from PIL import Image
    o = _order(admin, _cust(admin), advance=100).get_json()
    buf = io.BytesIO()
    Image.new("RGB", (30, 30), "red").save(buf, "PNG")
    buf.seek(0)
    admin.post(f"/api/measurements/{o['items'][0]['id']}/photo",
               data={"photo": (buf, "f.png")}, content_type="multipart/form-data")
    folder = tmp_path / "uploads"
    assert len(os.listdir(folder)) == 1
    assert admin.delete(f"/api/measurements/orders/{o['id']}").status_code == 200
    assert os.listdir(folder) == []
    import db.measurements as mdb
    conn = sqlite3.connect(mdb.MEASUREMENTS_DB_PATH)
    left = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("m_orders", "m_payments", "m_measurements")]
    conn.close()
    assert left == [0, 0, 0]
    assert admin.delete(f"/api/measurements/orders/{o['id']}").status_code == 404


def test_customer_with_orders_cannot_be_deleted(admin):
    busy, idle = _cust(admin, "Busy", "9000000001"), _cust(admin, "Idle", "9000000002")
    _order(admin, busy)
    r = admin.delete(f"/api/measurements/customers/{busy['id']}")
    assert r.status_code == 409 and "billing orders" in r.get_json()["error"]
    assert admin.delete(f"/api/measurements/customers/{idle['id']}").status_code == 200


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("method,url", [
    ("get", "/api/measurements/orders"),
    ("post", "/api/measurements/orders"),
    ("get", "/api/measurements/orders/1"),
    ("put", "/api/measurements/orders/1"),
    ("delete", "/api/measurements/orders/1"),
    ("post", "/api/measurements/orders/1/items"),
    ("post", "/api/measurements/orders/1/payments"),
    ("delete", "/api/measurements/payments/1"),
])
def test_billing_endpoints_require_login(client, method, url):  # noqa: F811
    assert getattr(client, method)(url).status_code in (401, 403)


def test_tailor_role_is_blocked_from_billing(client):  # noqa: F811
    _login_as(client, "tailor")
    assert client.get("/api/measurements/orders").status_code in (401, 403)
    assert client.post("/api/measurements/orders", json={}).status_code in (401, 403)


def test_staff_can_bill(client):  # noqa: F811
    _login_as(client, "staff")
    cust = _cust(client)
    assert _order(client, cust, advance=100).status_code == 201


# ---------------------------------------------------------------------------
# Dashboard rows carry the order label + balance
# ---------------------------------------------------------------------------
def test_dashboard_rows_show_order_label_and_balance(admin):
    cust = _cust(admin)
    _order(admin, cust, [_item("shirt", 500), _item("pant", 700)],
           delivery_date=_day(0), advance=200)
    _order(admin, cust, [_item("suit", 8000)], order_type="suit", delivery_date=_day(0))
    # an old-style standalone measurement has no order, so no billing fields
    admin.post(f"/api/measurements/customers/{cust['id']}/measurements",
               json={"garment_type": "kurta", "values": {}, "delivery_date": _day(0)})
    rows = admin.get("/api/measurements/dashboard").get_json()["deliveries_today"]
    by_label = {}
    for r in rows:
        by_label.setdefault(r["order_label"], []).append(r)
    assert {b["balance"] for b in by_label["M-0001"]} == {1000}
    assert len(by_label["M-0001"]) == 2           # the order's balance repeats per garment
    assert by_label["MS-0001"][0]["balance"] == 8000
    plain = by_label[None][0]
    assert plain["order_id"] is None and plain["balance"] is None


# ---------------------------------------------------------------------------
# Receipt page
# ---------------------------------------------------------------------------
def test_receipt_renders_totals_and_payments(admin):
    o = _order(admin, _cust(admin), [_item("shirt", 500, {"no_of_shirts": "2"}), _item("pant", 700)],
               cloth_balance=300, advance=1000, payment_mode="Cash",
               notes="Wedding rush").get_json()
    r = admin.get(f"/measurements/orders/{o['id']}/receipt")
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert "M-0001" in page and "Ravi Kumar" in page and "9876543210" in page
    assert "1,700.00" in page          # stitching 2x500 + 700
    assert "2,000.00" in page          # final total with cloth
    assert "Cloth balance" in page and "300.00" in page
    assert "Balance due" in page and "1,000.00" in page
    assert "Advance" in page and "Wedding rush" in page
    assert "trial" in page.lower()


def test_receipt_fully_paid_and_suit_label(admin):
    o = _order(admin, _cust(admin), [_item("suit", 8000)], order_type="suit", advance=8000).get_json()
    page = admin.get(f"/measurements/orders/{o['id']}/receipt").get_data(as_text=True)
    assert "MS-0001" in page and "Fully paid" in page and "Balance due" not in page
    assert "Suits" in page


def test_receipt_escapes_html(admin):
    cust = _cust(admin, "<script>alert(1)</script>", "9000000009")
    o = _order(admin, cust, notes="<img src=x onerror=1>").get_json()
    page = admin.get(f"/measurements/orders/{o['id']}/receipt").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page and "<img src=x" not in page
    assert "&lt;script&gt;" in page


def test_receipt_missing_order_and_access(client):  # noqa: F811
    assert client.get("/measurements/orders/1/receipt").status_code == 302    # not logged in
    _login_as(client, "tailor")
    assert client.get("/measurements/orders/1/receipt").status_code == 302    # role blocked
    _login_as(client, "admin")
    assert client.get("/measurements/orders/999/receipt").status_code == 404
