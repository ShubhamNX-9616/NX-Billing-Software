"""Regression tests for four bugs found in the production-readiness audit:

1. Deleting a bill that had unlocked a loyalty gift failed (foreign key).
2. A brand-new database was seeded with only two of the six cloth types.
3. Item codes repeated once a prefix passed 999 (text sort vs number sort).
4. "nan" / "inf" / absurdly large numbers were accepted as money amounts - NaN
   slips past every `< 0` and `> total` check, so it was stored.

Everything runs against temp databases; the real billing.db / tailoring.db are
never touched.
"""
import itertools
import json
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

from utils import MAX_AMOUNT, finite_float  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db.connection as conn_mod
    import db.tailoring as tdb
    import routes.tailoring as tr
    import routes.tailoring_suits as ts
    from db import close_db, init_db
    from routes.bills import bills_bp
    from routes.institution_bills import inst_bills_bp
    from routes.inventory import inventory_bp

    monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "billing_test.db"))
    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", str(tmp_path / "tailoring_test.db"))
    monkeypatch.setattr(tr, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(ts, "UPLOAD_DIR", str(tmp_path / "uploads"))
    init_db()
    tdb.init_tailoring_db()

    app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"),
                static_folder=os.path.join(PROJECT_ROOT, "static"))
    app.secret_key = "test"
    for bp in (bills_bp, inst_bills_bp, inventory_bp, tr.tailoring_api_bp, ts.tailoring_suit_api_bp):
        app.register_blueprint(bp, url_prefix="/api")
    app.teardown_appcontext(close_db)
    app.teardown_appcontext(tdb.close_tailoring_db)

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
            sess["username"] = "tester"
            sess["role"] = "admin"
        yield c


def _raw(client, method, url, body):
    """Send JSON exactly as a browser could, including NaN / Infinity literals."""
    return getattr(client, method)(url, data=json.dumps(body), content_type="application/json")


def _billing_conn():
    import db.connection as conn_mod
    return conn_mod._open_connection()


# ---------------------------------------------------------------------------
# finite_float
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("12.5", 12.5), (7, 7.0), (" 3 ", 3.0), (0, 0.0), ("-4", -4.0), (MAX_AMOUNT, MAX_AMOUNT),
])
def test_finite_float_accepts_real_numbers(raw, expected):
    assert finite_float(raw) == expected


@pytest.mark.parametrize("raw", [
    "nan", "NaN", "inf", "-inf", "Infinity", float("nan"), float("inf"), float("-inf"),
    "abc", "", None, [], {}, "1e999", MAX_AMOUNT * 10, "1e13",
])
def test_finite_float_rejects_everything_else(raw):
    with pytest.raises(ValueError):
        finite_float(raw, "Rate")


def test_finite_float_message_names_the_field():
    with pytest.raises(ValueError, match="Advance must be a number"):
        finite_float("nan", "Advance")
    with pytest.raises(ValueError, match="Advance is too large"):
        finite_float("1e13", "Advance")


# ---------------------------------------------------------------------------
# 2. Fresh install seeding
# ---------------------------------------------------------------------------
def test_fresh_database_gets_all_six_cloth_types(client):
    conn = _billing_conn()
    names = {r["type_name"] for r in conn.execute("SELECT type_name FROM cloth_types")}
    conn.close()
    assert names == {"Shirting", "Suiting", "Readymade", "Stitching", "Gift Sets", "Accessories"}


def test_fresh_database_gets_default_companies_and_salespersons(client):
    conn = _billing_conn()
    companies = {(r["cloth_type"], r["company_name"]) for r in conn.execute("SELECT * FROM companies")}
    people = {r["name"] for r in conn.execute("SELECT name FROM salespersons")}
    stitching_has_company = conn.execute(
        "SELECT has_company FROM cloth_types WHERE normalized_name = 'stitching'").fetchone()[0]
    conn.close()
    assert ("Suiting", "Raymond") in companies and ("Stitching", "Shirt") in companies
    assert {"Self", "Geetesh"} <= people
    assert stitching_has_company == 1


def test_reinitialising_does_not_duplicate_seed_rows(client):
    from db import init_db
    conn = _billing_conn()
    before = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("cloth_types", "companies", "salespersons")]
    conn.close()
    init_db()
    init_db()
    conn = _billing_conn()
    after = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("cloth_types", "companies", "salespersons")]
    conn.close()
    assert before == after


# ---------------------------------------------------------------------------
# 3. Item codes
# ---------------------------------------------------------------------------
def _add_item(conn, code, cloth="Suiting"):
    conn.execute("INSERT INTO inventory_items (cloth_type, company_name, item_code) VALUES (?, 'X', ?)",
                 (cloth, code))


def test_item_code_starts_at_001(client):
    from services.inventory import next_item_code
    conn = _billing_conn()
    assert next_item_code(conn, "Suiting") == "SUT-001"
    conn.close()


def test_item_code_keeps_counting_past_999(client):
    from services.inventory import next_item_code
    conn = _billing_conn()
    for n in (997, 998, 999):
        _add_item(conn, f"SUT-{n:03d}")
    assert next_item_code(conn, "Suiting") == "SUT-1000"
    _add_item(conn, "SUT-1000")
    # the old lookup sorted as text, where "SUT-999" > "SUT-1000", and repeated SUT-1000 here
    assert next_item_code(conn, "Suiting") == "SUT-1001"
    _add_item(conn, "SUT-1001")
    assert next_item_code(conn, "Suiting") == "SUT-1002"
    conn.close()


def test_item_code_ignores_other_prefixes_and_junk(client):
    from services.inventory import next_item_code
    conn = _billing_conn()
    _add_item(conn, "SUT-004")
    _add_item(conn, "SHT-050", "Shirting")
    _add_item(conn, "SUT-oops")
    conn.commit()
    assert next_item_code(conn, "Suiting") == "SUT-005"
    assert next_item_code(conn, "Shirting") == "SHT-051"
    assert next_item_code(conn, "Readymade") == "RDY-001"
    conn.close()


# ---------------------------------------------------------------------------
# 1. Deleting a bill that unlocked a loyalty gift
# ---------------------------------------------------------------------------
def _bill_body(**over):
    body = {"customer_name": "Ravi", "customer_mobile": "9876543210", "bill_date": "2026-11-01",
            "salesperson_name": "Self", "payment_mode_type": "Cash",
            "items": [{"cloth_type": "Shirting", "company_name": "Monti", "quantity": 2, "mrp": 500}]}
    body.update(over)
    return body


def test_deleting_a_bill_keeps_the_loyalty_gift_it_unlocked(client):
    bill = client.post("/api/bills", json=_bill_body()).get_json()
    conn = _billing_conn()
    conn.execute("INSERT INTO loyalty_cycles (cycle_number, start_date, end_date) "
                 "VALUES (1, '2026-01-01', '2027-01-01')")
    conn.execute("INSERT INTO loyalty_gifts (customer_id, tier, cycle_id, bill_id, given_at, given_by) "
                 "VALUES (?, 'silver', 1, ?, '2026-11-02', 'admin')", (bill["customer_id"], bill["id"]))
    conn.commit()
    conn.close()

    r = client.delete(f"/api/bills/{bill['id']}")
    assert r.status_code == 200, r.get_json()

    conn = _billing_conn()
    gift = conn.execute("SELECT * FROM loyalty_gifts").fetchone()
    left = conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
    conn.close()
    assert left == 0
    assert gift is not None and gift["bill_id"] is None        # gift kept, link cleared
    assert gift["given_at"] == "2026-11-02"                    # and still marked as handed over


def test_deleting_a_bill_without_gifts_still_works(client):
    bill = client.post("/api/bills", json=_bill_body()).get_json()
    assert client.delete(f"/api/bills/{bill['id']}").status_code == 200


# ---------------------------------------------------------------------------
# 4. NaN / infinity / huge numbers are refused (and nothing is saved)
# ---------------------------------------------------------------------------
def _count(table):
    conn = _billing_conn()
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


@pytest.mark.parametrize("mutate", [
    lambda b: b["items"][0].update(quantity="nan"),
    lambda b: b["items"][0].update(quantity="inf"),
    lambda b: b["items"][0].update(quantity="1e308"),
    lambda b: b["items"][0].update(mrp="Infinity"),
    lambda b: b["items"][0].update(mrp=float("nan")),
    lambda b: b["items"][0].update(discount_percent="nan"),
    lambda b: b["items"][0].update(discount_amount="inf"),
    lambda b: b.update(advance_paid="nan"),
    lambda b: b.update(advance_paid=float("inf")),
    lambda b: b.update(round_off="inf"),
    lambda b: b.update(advance_paid=500, payments=[{"payment_method": "Cash", "amount": "nan"}]),
])
def test_bill_create_refuses_non_finite_numbers(client, mutate):
    body = _bill_body()
    mutate(body)
    r = _raw(client, "post", "/api/bills", body)
    assert r.status_code == 400, r.get_json()
    assert "error" in r.get_json()
    assert _count("bills") == 0


def test_bill_create_still_treats_junk_text_advance_as_zero(client):
    """Unchanged legacy behaviour: unparseable (but finite-safe) text means 0."""
    r = client.post("/api/bills", json=_bill_body(advance_paid="abc"))
    assert r.status_code == 201 and r.get_json()["advance_paid"] == 0


def test_bill_record_payment_refuses_non_finite_amounts(client):
    bill = client.post("/api/bills", json=_bill_body()).get_json()
    for bad in ("nan", "inf", "-inf", "1e999", "abc"):
        r = _raw(client, "post", f"/api/bills/{bill['id']}/record-payment",
                 {"payment_method": "Cash", "amount": bad})
        assert r.status_code == 400, (bad, r.get_json())
    assert client.get(f"/api/bills/{bill['id']}").get_json()["remaining"] == 1000
    assert _count("bill_payments") == 0


def _inst_body(**over):
    body = {"company_name": "Acme", "bill_date": "2026-11-01", "payment_mode_type": "Cash",
            "items": [{"cloth_type": "Suiting", "company_name": "Raymond", "quantity_per_pc": 3,
                       "rate_per_m": 500, "no_of_pcs": 2, "stitching_per_unit": 100}]}
    body.update(over)
    return body


def test_institution_bill_valid_baseline(client):
    assert client.post("/api/institution-bills", json=_inst_body()).status_code == 201


@pytest.mark.parametrize("mutate", [
    lambda b: b["items"][0].update(rate_per_m="nan"),
    lambda b: b["items"][0].update(quantity_per_pc="inf"),
    lambda b: b["items"][0].update(stitching_per_unit="nan"),
    lambda b: b["items"][0].update(no_of_pcs=float("inf")),
    lambda b: b["items"][0].update(no_of_pcs="nan"),
    lambda b: b.update(advance_paid="nan"),
    lambda b: b.update(round_off="inf"),
    lambda b: b.update(payments=[{"payment_method": "Cash", "amount": "nan"}]),
    lambda b: b.update(payments=[{"payment_method": "Cash", "amount": -5}]),
    lambda b: b.update(payments=[{"amount": 100}]),
    lambda b: b.update(payments="lots"),
])
def test_institution_bill_refuses_bad_numbers_and_payments(client, mutate):
    body = _inst_body()
    mutate(body)
    r = _raw(client, "post", "/api/institution-bills", body)
    assert r.status_code == 400, r.get_json()
    assert _count("institution_bills") == 0


def test_institution_bill_update_refuses_non_finite(client):
    bill = client.post("/api/institution-bills", json=_inst_body()).get_json()
    r = _raw(client, "put", f"/api/institution-bills/{bill['id']}", _inst_body(advance_paid="inf"))
    assert r.status_code == 400
    r = _raw(client, "put", f"/api/institution-bills/{bill['id']}",
             _inst_body(payments=[{"payment_method": "Cash", "amount": "nan"}]))
    assert r.status_code == 400


def test_institution_record_payment_refuses_non_finite(client):
    bill = client.post("/api/institution-bills", json=_inst_body()).get_json()
    for bad in ("nan", "inf", "1e999"):
        r = _raw(client, "post", f"/api/institution-bills/{bill['id']}/record-payment",
                 {"payment_method": "Cash", "amount": bad})
        assert r.status_code == 400, (bad, r.get_json())


# ---- tailoring + suits ----------------------------------------------------
_orders = itertools.count(5001)


def _tailoring_count(table):
    import sqlite3
    import db.tailoring as tdb
    conn = sqlite3.connect(tdb.TAILORING_DB_PATH)
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _t_body(**over):
    body = {"order_number": next(_orders), "customer_name": "Bawaskar", "mobile": "9876543210",
            "items": [{"garment_type": "Shirt", "qty": 1, "rate": 500}]}
    body.update(over)
    return body


def _s_body(**over):
    body = _t_body(**over)
    body["book_no"] = "1"
    return body


@pytest.mark.parametrize("base", ["/api/tailoring/orders", "/api/tailoring/suits/orders"])
@pytest.mark.parametrize("field,bad", [
    ("advance", "nan"), ("advance", "inf"), ("advance", "-inf"),
    ("cloth_balance", "nan"), ("cloth_balance", "inf"), ("advance", "1e13"),
])
def test_tailoring_create_refuses_non_finite_money(client, base, field, bad):
    make = _s_body if "suits" in base else _t_body
    r = _raw(client, "post", base, make(**{field: bad}))
    assert r.status_code == 400, r.get_json()
    table = "tailoring_suit_orders" if "suits" in base else "tailoring_orders"
    assert _tailoring_count(table) == 0                         # nothing half-saved


@pytest.mark.parametrize("base", ["/api/tailoring/orders", "/api/tailoring/suits/orders"])
def test_tailoring_create_refuses_non_finite_rate(client, base):
    make = _s_body if "suits" in base else _t_body
    body = make()
    body["items"][0]["rate"] = "nan"
    assert _raw(client, "post", base, body).status_code == 400


@pytest.mark.parametrize("base", ["/api/tailoring/orders", "/api/tailoring/suits/orders"])
def test_tailoring_payment_endpoints_refuse_non_finite(client, base):
    make = _s_body if "suits" in base else _t_body
    order = client.post(base, json=make(advance=100)).get_json()
    oid = order["id"]
    for bad in ("nan", "inf", "1e999"):
        assert _raw(client, "post", f"{base}/{oid}/payments", {"amount": bad}).status_code == 400
        assert _raw(client, "patch", f"{base}/{oid}/payment", {"advance": bad}).status_code == 400
        assert _raw(client, "patch", f"{base}/{oid}/cloth-balance", {"cloth_balance": bad}).status_code == 400
    after = client.get(f"{base}/{oid}").get_json()
    assert after["advance"] == 100 and after["balance"] == 400      # untouched


def test_tailoring_update_refuses_non_finite(client):
    order = client.post("/api/tailoring/orders", json=_t_body()).get_json()
    body = _t_body(order_number=order["order_number"], advance="nan")
    r = _raw(client, "put", f"/api/tailoring/orders/{order['id']}", body)
    assert r.status_code == 400


def test_tailoring_valid_money_still_works(client):
    r = client.post("/api/tailoring/orders", json=_t_body(advance=200, cloth_balance=50))
    assert r.status_code == 201
    got = r.get_json()
    assert got["advance"] == 200 and got["cloth_balance"] == 50 and got["balance"] == 350


# ---- inventory --------------------------------------------------------------
def _inv_body(**over):
    body = {"cloth_type": "Suiting", "company_name": "Raymond", "mrp": 500,
            "cost_price": 300, "opening_stock": 10}
    body.update(over)
    return body


def test_inventory_valid_baseline(client):
    assert client.post("/api/inventory", json=_inv_body()).status_code == 201


@pytest.mark.parametrize("field", ["mrp", "cost_price", "opening_stock", "min_stock_alert"])
@pytest.mark.parametrize("bad", ["nan", "inf", "1e999"])
def test_inventory_create_refuses_non_finite(client, field, bad):
    r = _raw(client, "post", "/api/inventory", _inv_body(**{field: bad}))
    assert r.status_code == 400, r.get_json()
    assert _count("inventory_items") == 0


def test_inventory_update_and_adjust_refuse_non_finite(client):
    item = client.post("/api/inventory", json=_inv_body()).get_json()
    iid = item["id"]
    for bad in ("nan", "inf"):
        assert _raw(client, "put", f"/api/inventory/{iid}", _inv_body(mrp=bad)).status_code == 400
        assert _raw(client, "post", f"/api/inventory/{iid}/adjust", {"quantity": bad}).status_code == 400
    conn = _billing_conn()
    row = conn.execute("SELECT mrp, current_stock FROM inventory_items WHERE id = ?", (iid,)).fetchone()
    conn.close()
    assert (row["mrp"], row["current_stock"]) == (500, 10)
