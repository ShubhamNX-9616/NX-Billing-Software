"""Tailoring and Suits share one implementation (routes/tailoring_common.OrderBook).

These tests keep it that way:
- both books expose exactly the same API routes, differing only by URL prefix
- neither route module grows its own copy of a shared handler again
- the same operations give the same answers in both books (only the book number differs)
- the few real differences (book number, archive filter, list shape, photo names) hold
"""
import ast
import io
import itertools
import os
import sys

import pytest
from flask import Flask
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db.connection as conn_mod
    import db.tailoring as tdb
    import routes.tailoring as tr
    import routes.tailoring_suits as ts
    from db import close_db, init_db

    monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "billing_test.db"))
    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", str(tmp_path / "tailoring_test.db"))
    monkeypatch.setattr(tr, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(ts, "UPLOAD_DIR", str(tmp_path / "uploads"))
    init_db()
    tdb.init_tailoring_db()
    app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"))
    app.secret_key = "t"
    for bp in (tr.tailoring_api_bp, tr.tailoring_pages_bp, ts.tailoring_suit_api_bp, ts.tailoring_suit_pages_bp):
        app.register_blueprint(bp, url_prefix="/api" if bp.name.endswith("api") else "")
    app.teardown_appcontext(close_db)
    app.teardown_appcontext(tdb.close_tailoring_db)
    app.template_filter("format_date")(lambda v: v or "")
    app.context_processor(lambda: {"sv": "t", "current_user": {"role": "admin", "is_admin": True, "is_tailor": False},
                                   "server_today": "", "share_base_url": "", "tryon_url": "",
                                   "measurements_enabled": False})
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"], sess["username"], sess["role"] = 1, "t", "admin"
        c.app = app
        yield c


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
def _api_rules(app, bp_name):
    return {(r.rule, tuple(sorted(r.methods - {"HEAD", "OPTIONS"})), r.endpoint.split(".", 1)[1])
            for r in app.url_map.iter_rules() if r.endpoint.startswith(bp_name + ".")}


def test_both_books_expose_the_same_routes_under_their_own_prefix(client):
    t = _api_rules(client.app, "tailoring_api")
    s = _api_rules(client.app, "tailoring_suit_api")
    # the daily/weekly report, photo file and receipt live only in the general module (pages blueprint)
    shared_t = {(r.replace("/tailoring", "", 1), m, e) for r, m, e in t}
    shared_s = {(r.replace("/tailoring/suits", "", 1), m, e) for r, m, e in s}
    assert shared_t == shared_s
    assert len(t) == 21 and len(s) == 21
    assert all(r.startswith("/api/tailoring/") and "/suits" not in r for r, _, _ in t)
    assert all(r.startswith("/api/tailoring/suits/") for r, _, _ in s)


def test_every_route_in_the_table_has_a_handler():
    from routes.tailoring_common import OrderBook
    assert len(OrderBook.ROUTES) == 21
    for _, _, name in OrderBook.ROUTES:
        assert callable(getattr(OrderBook, name)), name


def test_route_modules_do_not_re_grow_their_own_copies():
    """The whole point of the shared module: a fix is made once."""
    from routes.tailoring_common import OrderBook
    shared = {name for _, _, name in OrderBook.ROUTES} | {
        "_ist_date", "_today_ist", "_is_overdue", "_derived_stage", "_final_total", "_parse_items",
        "_parse_order_number", "_split_off_unit", "_sync_stage_stamps", "_order_payload",
        "_order_payloads_bulk", "_remember_garment_rates", "_customer_index", "_order_brief"}
    for module in ("tailoring.py", "tailoring_suits.py"):
        tree = ast.parse(io.open(os.path.join(PROJECT_ROOT, "routes", module), encoding="utf-8-sig").read())
        own = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        assert not (own & shared), (module, sorted(own & shared))


def test_suits_module_stays_small():
    lines = io.open(os.path.join(PROJECT_ROOT, "routes", "tailoring_suits.py"), encoding="utf-8-sig").read().split("\n")
    assert len(lines) < 200, "routes/tailoring_suits.py is growing a copy of the shared code again"


def test_books_use_their_own_tables_and_nothing_leaks_between_them(client):
    import routes.tailoring as tr
    import routes.tailoring_suits as ts
    assert (tr.BOOK.orders, ts.BOOK.orders) == ("tailoring_orders", "tailoring_suit_orders")
    assert not ({tr.BOOK.items, tr.BOOK.photos, tr.BOOK.payments, tr.BOOK.rates} &
                {ts.BOOK.items, ts.BOOK.photos, ts.BOOK.payments, ts.BOOK.rates})
    client.post("/api/tailoring/orders", json={"order_number": 1, "customer_name": "A", "mobile": "9876543210",
                                               "items": [{"garment_type": "Shirt", "qty": 1, "rate": 100}]})
    assert client.get("/api/tailoring/suits/orders").get_json()["orders"] == []
    assert len(client.get("/api/tailoring/orders").get_json()["orders"]) == 1


def test_login_redirect_target_still_resolves(client):
    """routes/auth.py sends tailor users to url_for('tailoring_pages.tailoring_page')."""
    with client.app.test_request_context():
        from flask import url_for
        assert url_for("tailoring_pages.tailoring_page") == "/tailoring"
        assert url_for("tailoring_suit_pages.suit_page") == "/tailoring/suits"


def test_old_import_paths_still_work():
    """scripts/shrink_r2_photos.py and older tests import these from routes.tailoring."""
    from routes.tailoring import MAX_PHOTO_DIM, PHOTO_JPEG_QUALITY, UPLOAD_DIR, _ist_date  # noqa: F401
    from routes.tailoring_suits import UPLOAD_DIR as suit_dir, build_suit_report_entries  # noqa: F401
    assert MAX_PHOTO_DIM == 1400 and PHOTO_JPEG_QUALITY == 82


# ---------------------------------------------------------------------------
# Same operations, same answers
# ---------------------------------------------------------------------------
BOOKS = [("/api/tailoring", False), ("/api/tailoring/suits", True)]
_numbers = itertools.count(100)
DROP = {"id", "order_id", "item_id", "photo_id", "created_at", "updated_at", "paid_at", "delivered_at",
        "stitched_at", "filename", "book_no", "order_number", "url", "last_book_no"}


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in DROP}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


LIST_ROW_KEYS = {"customer_name", "mobile", "trial_date", "delivery_date", "stage", "balance", "cloth_balance", "items"}


def _list_row(order):
    """Tailoring sends trimmed list rows, Suits full orders (OrderBook.slim_list): compare the common part."""
    row = {k: v for k, v in order.items() if k in LIST_ROW_KEYS}
    row["items"] = [{k: i[k] for k in ("garment_type", "qty", "stage")} for i in row["items"]]
    return row


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buf, "PNG")
    buf.seek(0)
    return buf


def _scenario(client, base, suits):
    """One long sequence of operations; returns the cleaned response of every step."""
    n = next(_numbers)
    out = []

    def call(method, url, **kw):
        r = getattr(client, method)(base + url, **kw)
        body = _clean(r.get_json()) if r.is_json else r.get_data(as_text=True)[:80]
        if isinstance(body, dict) and "counts" in body and "orders" in body:
            body["orders"] = [_list_row(o) for o in body["orders"]]       # list shape differs by design
        out.append((r.status_code, body))
        return r

    body = {"order_number": n, "customer_name": "Ravi", "mobile": "9876543210", "address": "Pune",
            "order_date": "2026-11-01", "trial_date": "2026-11-20", "delivery_date": "2026-11-25",
            "advance": 500, "payment_mode": "Cash", "cloth_balance": 100, "notes": "n",
            "items": [{"garment_type": "Shirt", "qty": 2, "rate": 600}, {"garment_type": "Pant", "qty": 1, "rate": 800}]}
    if suits:
        body["book_no"] = "1"
    order = call("post", "/orders", json=body).get_json()
    oid = order["id"]
    call("get", f"/orders/{oid}")
    call("get", "/orders")
    call("get", "/orders?stage=In Stitching&pay=due&sort=balance-desc")
    call("get", "/dashboard")
    call("get", "/customers")
    call("get", "/customers/search?mobile=9876543210")
    call("get", "/customers/suggest?q=Rav")
    call("get", "/meta")
    items = order["items"]
    call("patch", f"/items/{items[0]['id']}/stage", json={"stage": "Full Stitched"})
    call("post", f"/items/{items[0]['id']}/split", json={"qty": 1, "stage": "Trial Ready"})
    call("patch", f"/orders/{oid}/stage", json={"stage": "Trial Ready"})
    call("patch", f"/orders/{oid}/payment", json={"advance": 600, "payment_mode": "UPI"})
    call("patch", f"/orders/{oid}/cloth-balance", json={"cloth_balance": 50})
    pay = call("post", f"/orders/{oid}/payments", json={"amount": 100, "mode": "Cash"}).get_json()
    call("post", f"/orders/{oid}/payments", json={"amount": 99999})
    call("delete", f"/payments/{pay['payments'][-1]['id']}")
    upd = dict(body, customer_name="Renamed", delivery_date="2026-12-01")
    upd["items"] = [{"id": items[1]["id"], "garment_type": "Pant", "qty": 2, "rate": 800},
                    {"garment_type": "Coat", "qty": 1, "rate": 2000}]
    call("put", f"/orders/{oid}", json=upd)
    ph = call("post", f"/orders/{oid}/photos", data={"photo": (_png(), "a.png")},
              content_type="multipart/form-data").get_json()
    call("patch", f"/photos/{ph['photos'][0]['id']}/stage", json={"stage": "Trial Ready"})
    call("delete", f"/photos/{ph['photos'][0]['id']}")
    call("get", "/orders")
    call("delete", f"/orders/{oid}")
    call("get", f"/orders/{oid}")
    return out


def test_the_same_operations_give_the_same_answers_in_both_books(client):
    tailoring = _scenario(client, "/api/tailoring", False)
    suits = _scenario(client, "/api/tailoring/suits", True)
    assert len(tailoring) == len(suits) > 20
    for i, (a, b) in enumerate(zip(tailoring, suits)):
        assert a == b, f"step {i}: tailoring {a} != suits {b}"


# ---------------------------------------------------------------------------
# The genuine differences
# ---------------------------------------------------------------------------
def test_suits_orders_need_a_book_number_and_numbers_are_per_book(client):
    base = "/api/tailoring/suits/orders"
    item = [{"garment_type": "Suit", "qty": 1, "rate": 3000}]
    mk = lambda **kw: {"order_number": 7, "customer_name": "A", "mobile": "9876543210", "items": item, **kw}  # noqa: E731
    assert client.post(base, json=mk()).status_code == 400                           # no book
    assert client.post(base, json=mk(book_no="1")).status_code == 201
    dup = client.post(base, json=mk(book_no="1"))
    assert dup.status_code == 400 and "already exists in Book 1" in dup.get_json()["error"]
    assert client.post(base, json=mk(book_no="2")).status_code == 201                # same number, new book
    # tailoring has no book number: the same number twice is refused outright
    t = "/api/tailoring/orders"
    assert client.post(t, json=mk()).status_code == 201
    dup = client.post(t, json=mk())
    assert dup.status_code == 400 and dup.get_json()["error"] == "Order number 7 already exists"


def test_suit_order_can_move_to_another_book_but_not_onto_an_existing_number(client):
    base = "/api/tailoring/suits/orders"
    item = [{"garment_type": "Suit", "qty": 1, "rate": 3000}]
    a = client.post(base, json={"book_no": "1", "order_number": 1, "customer_name": "A", "mobile": "9876543210", "items": item}).get_json()
    client.post(base, json={"book_no": "2", "order_number": 1, "customer_name": "B", "mobile": "9876543211", "items": item})
    r = client.put(f"{base}/{a['id']}", json={"book_no": "2", "order_number": 1, "customer_name": "A", "items": item})
    assert r.status_code == 400 and "already exists in Book 2" in r.get_json()["error"]
    r = client.put(f"{base}/{a['id']}", json={"book_no": "3", "order_number": 1, "customer_name": "A", "items": item})
    assert r.status_code == 200 and r.get_json()["book_no"] == "3"


def test_meta_remembers_the_last_book_only_for_suits(client):
    assert "last_book_no" not in client.get("/api/tailoring/meta").get_json()
    assert client.get("/api/tailoring/suits/meta").get_json()["last_book_no"] == ""
    client.post("/api/tailoring/suits/orders", json={"book_no": "5", "order_number": 1, "customer_name": "A",
                                                     "items": [{"garment_type": "Suit", "qty": 1, "rate": 1}]})
    assert client.get("/api/tailoring/suits/meta").get_json()["last_book_no"] == "5"


def test_only_tailoring_hides_imported_archive_orders_and_trims_its_list(client):
    import db.tailoring as tdb
    import sqlite3
    c = sqlite3.connect(tdb.TAILORING_DB_PATH)
    for table in ("tailoring_orders", "tailoring_suit_orders"):
        extra = ", book_no" if "suit" in table else ""
        vals = ", '1'" if "suit" in table else ""
        c.execute(f"INSERT INTO {table} (order_number, order_date, customer_name, notes{extra}) "
                  f"VALUES (1, '2020-01-01', 'Old Customer', 'Imported from Drive archive batch 1'{vals})")
    c.commit()
    c.close()
    assert client.get("/api/tailoring/orders").get_json()["orders"] == []                   # hidden from the board
    assert len(client.get("/api/tailoring/orders?q=Old").get_json()["orders"]) == 1          # still searchable
    assert len(client.get("/api/tailoring/suits/orders").get_json()["orders"]) == 1          # suits has no archive
    row = client.get("/api/tailoring/orders?q=Old").get_json()["orders"][0]
    assert "photo_count" in row and "photos" not in row                                      # tailoring: trimmed rows
    full = client.get("/api/tailoring/suits/orders").get_json()["orders"][0]
    assert "photos" in full and "photo_count" not in full                                    # suits: full orders


def test_photo_files_keep_distinct_names_per_book(client, tmp_path):
    for base, body in (("/api/tailoring", {"order_number": 1}), ("/api/tailoring/suits", {"order_number": 1, "book_no": "1"})):
        o = client.post(base + "/orders", json={**body, "customer_name": "A", "mobile": "9876543210",
                                                "items": [{"garment_type": "Shirt", "qty": 1, "rate": 10}]}).get_json()
        client.post(f"{base}/orders/{o['id']}/photos", data={"photo": (_png(), "a.png")}, content_type="multipart/form-data")
    names = sorted(os.listdir(tmp_path / "uploads"))
    assert len(names) == 2 and names[0].startswith("order") and names[1].startswith("suitorder")
