"""Money handling: amounts are whole paise, rates keep their decimals, and totals never
carry floating-point noise.

Money is stored as REAL rounded to 2 decimals (decision recorded in CLAUDE.md). That is
safe only if (a) every amount is rounded on its way in, (b) every aggregate is rounded on
its way out, and (c) rates / unit prices - which are multiplied, not paid - are NOT
rounded. These tests pin all three.
"""
import itertools
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

from utils import money_float  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db.connection as conn_mod
    import db.measurements as mdb
    import db.tailoring as tdb
    import routes.measurements as mr
    import routes.tailoring as tr
    import routes.tailoring_suits as ts
    from db import close_db, init_db
    from routes.analytics import analytics_bp
    from routes.bills import bills_bp
    from routes.customers import customers_bp
    from routes.institution_bills import inst_bills_bp
    from routes.inventory import inventory_bp

    monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "billing_test.db"))
    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", str(tmp_path / "tailoring_test.db"))
    monkeypatch.setattr(mdb, "MEASUREMENTS_DB_PATH", str(tmp_path / "measurements_test.db"))
    monkeypatch.setattr(tr, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(ts, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(mr, "UPLOAD_DIR", str(tmp_path / "uploads_m"))
    init_db()
    tdb.init_tailoring_db()
    mdb.init_measurements_db()

    app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"))
    app.secret_key = "test"
    for bp in (bills_bp, customers_bp, inst_bills_bp, inventory_bp, analytics_bp, tr.tailoring_api_bp,
               ts.tailoring_suit_api_bp, mr.measurements_api_bp):
        app.register_blueprint(bp, url_prefix="/api")
    app.teardown_appcontext(close_db)
    app.teardown_appcontext(tdb.close_tailoring_db)
    app.teardown_appcontext(mdb.close_measurements_db)
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"], sess["username"], sess["role"] = 1, "tester", "admin"
        yield c


# ---------------------------------------------------------------------------
# money_float
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("100.005", 100.01), (100.004, 100.0), ("33.333333", 33.33), ("0.005", 0.01), (7, 7.0),
    ("2899.998", 2900.0), ("-0.004", -0.0), ("1e3", 1000.0),
])
def test_money_float_rounds_to_whole_paise_half_up(raw, expected):
    assert money_float(raw) == expected


@pytest.mark.parametrize("raw", ["nan", "inf", "abc", None, "", "1e13"])
def test_money_float_still_refuses_junk(raw):
    with pytest.raises(ValueError):
        money_float(raw, "Advance")


# ---------------------------------------------------------------------------
# The loyalty bug: exact 10,000.00 summed to 9999.999999999998
# ---------------------------------------------------------------------------
NOISY = [3483.69, 1928.79, 1487.73, 814.57, 2285.22]          # adds up to exactly 10,000.00


def _bill(client, name, amount, mobile="9876543210", date="2026-11-01"):
    r = client.post("/api/bills", json={
        "customer_name": name, "customer_mobile": mobile, "bill_date": date,
        "salesperson_name": "Self", "payment_mode_type": "Cash",
        "items": [{"cloth_type": "Accessories", "company_name": "X", "quantity": 1, "mrp": amount}]})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _open():
    import db.connection as conn_mod
    return conn_mod._open_connection()


def test_the_noisy_combination_is_noisy_and_rounding_fixes_it():
    """Premise of the next tests, independent of the SQLite version.

    Plain float addition of these amounts gives 9999.999999999998 (IEEE arithmetic, the same
    everywhere). Older SQLite builds (e.g. 3.40, as on some servers) sum REAL columns exactly
    like that; newer ones (3.43+) use compensated summation and happen to return exactly
    10000.0. The app must be right on both, so it rounds: ROUND(SUM(x), 2) is 10000.0 either way."""
    import sqlite3
    acc = 0.0
    for x in NOISY:
        acc += x
    assert acc < 10000 and round(acc, 2) == 10000.0
    c = sqlite3.connect(":memory:")
    c.execute("create table t (x real)")
    c.executemany("insert into t values (?)", [(x,) for x in NOISY])
    assert c.execute("select round(sum(x), 2) from t").fetchone()[0] == 10000.0


def test_customer_who_spent_exactly_ten_thousand_earns_silver(client):
    from services.loyalty import check_and_unlock_gifts, get_cycle_spent
    conn = _open()
    conn.execute("INSERT INTO loyalty_cycles (cycle_number, start_date, end_date) VALUES (1, '2026-01-01', '2027-01-01')")
    conn.execute("UPDATE loyalty_settings SET activation_date = '2026-01-01'")
    conn.commit()
    conn.close()
    last = None
    for i, amount in enumerate(NOISY):
        last = _bill(client, "Ravi", amount)
    conn = _open()
    cycle = dict(conn.execute("SELECT * FROM loyalty_cycles WHERE id = 1").fetchone())
    assert get_cycle_spent(conn, last["customer_id"], cycle) == 10000.0           # exact, not ...998
    tiers = [r["tier"] for r in conn.execute("SELECT tier FROM loyalty_gifts")]
    conn.close()
    assert tiers == ["silver"]                                                    # earned, and awarded


def test_one_paisa_short_still_does_not_earn_silver(client):
    from services.loyalty import get_cycle_spent
    conn = _open()
    conn.execute("INSERT INTO loyalty_cycles (cycle_number, start_date, end_date) VALUES (1, '2026-01-01', '2027-01-01')")
    conn.execute("UPDATE loyalty_settings SET activation_date = '2026-01-01'")
    conn.commit()
    conn.close()
    amounts = NOISY[:-1] + [round(NOISY[-1] - 0.01, 2)]                           # 9,999.99
    for amount in amounts:
        bill = _bill(client, "Sunil", amount, mobile="9123456789")
    conn = _open()
    cycle = dict(conn.execute("SELECT * FROM loyalty_cycles WHERE id = 1").fetchone())
    assert get_cycle_spent(conn, bill["customer_id"], cycle) == 9999.99
    assert conn.execute("SELECT COUNT(*) FROM loyalty_gifts").fetchone()[0] == 0
    conn.close()


def test_reports_show_exact_totals_not_float_noise(client):
    for amount in NOISY:
        _bill(client, "Ravi", amount)
    got = client.get("/api/analytics/summary").get_json()
    assert got["total_sales"] == 10000.0 and got["today_sales"] in (0, 10000.0)
    # and the customer figure on the customers screen
    stats = client.get("/api/customers/summary?mobile=9876543210").get_json()
    assert stats["total_spent"] == 10000.0


# ---------------------------------------------------------------------------
# Amounts are stored as whole paise
# ---------------------------------------------------------------------------
_numbers = itertools.count(8001)


def _order(base, **over):
    body = {"order_number": next(_numbers), "customer_name": "A", "mobile": "9876543210",
            "items": [{"garment_type": "Shirt", "qty": 1, "rate": 1000}]}
    if "suits" in base:
        body["book_no"] = "1"
    body.update(over)
    return body


@pytest.mark.parametrize("base", ["/api/tailoring/orders", "/api/tailoring/suits/orders"])
def test_advance_and_cloth_balance_are_stored_in_whole_paise(client, base):
    r = client.post(base, json=_order(base, advance="100.005", cloth_balance="50.004"))
    assert r.status_code == 201, r.get_json()
    got = r.get_json()
    assert got["advance"] == 100.01 and got["cloth_balance"] == 50.0
    assert got["balance"] == 949.99                       # 1000 + 50.00 - 100.01, exactly
    assert got["payments"][0]["amount"] == 100.01


@pytest.mark.parametrize("base", ["/api/tailoring/orders", "/api/tailoring/suits/orders"])
def test_later_payments_are_stored_in_whole_paise(client, base):
    order = client.post(base, json=_order(base, advance=100)).get_json()
    got = client.post(f"{base}/{order['id']}/payments", json={"amount": "10.004"}).get_json()
    assert got["advance"] == 110.0 and got["balance"] == 890.0
    assert [p["amount"] for p in got["payments"]] == [100.0, 10.0]
    got = client.post(f"{base}/{order['id']}/payments", json={"amount": "0.005"}).get_json()
    assert got["advance"] == 110.01 and got["balance"] == 889.99


@pytest.mark.parametrize("base", ["/api/tailoring/orders", "/api/tailoring/suits/orders"])
def test_a_rate_keeps_its_decimals_so_three_pieces_can_make_exactly_2900(client, base):
    """Real data has rates like 966.666. Rounding the rate to 966.67 would bill 2,900.01."""
    body = _order(base)
    body["items"] = [{"garment_type": "Shirt", "qty": 3, "rate": "966.666"}]
    got = client.post(base, json=body).get_json()
    assert got["items"][0]["rate"] == 966.666
    assert got["items"][0]["amount"] == 2900.0 and got["total"] == 2900.0


def test_bill_payment_rows_are_stored_in_whole_paise(client):
    r = client.post("/api/bills", json={
        "customer_name": "A", "customer_mobile": "9876543210", "bill_date": "2026-11-01",
        "salesperson_name": "Self", "payment_mode_type": "Cash", "advance_paid": 500,
        "payments": [{"payment_method": "Cash", "amount": "500.004"}],
        "items": [{"cloth_type": "Accessories", "company_name": "X", "quantity": 1, "mrp": 1000}]})
    assert r.status_code == 201, r.get_json()
    bill = client.get(f"/api/bills/{r.get_json()['id']}").get_json()
    assert [p["amount"] for p in bill["payments"]] == [500.0]


def test_inventory_prices_are_not_rounded(client):
    """mrp / cost price are per-unit rates: they keep whatever precision was entered."""
    r = client.post("/api/inventory", json={"cloth_type": "Suiting", "company_name": "Raymond",
                                           "mrp": "333.333", "cost_price": "199.999", "opening_stock": 4})
    assert r.status_code == 201
    got = client.get(f"/api/inventory/{r.get_json()['id']}").get_json()
    assert got["mrp"] == 333.333 and got["cost_price"] == 199.999


def test_measurement_rate_keeps_its_decimals_and_the_amount_is_in_paise(client):
    cust = client.post("/api/measurements/customers", json={"name": "A", "mobile": "9876543210"}).get_json()
    order = client.post("/api/measurements/orders", json={
        "customer_id": cust["id"], "advance": "100.005",
        "items": [{"garment_type": "shirt", "rate": "966.666", "values": {"no_of_shirts": "3"}}]}).get_json()
    item = order["items"][0]
    assert item["rate"] == 966.666 and item["amount"] == 2900.0
    assert order["advance"] == 100.01 and order["balance"] == 2799.99
    # editing the garment keeps the same rule
    upd = client.put(f"/api/measurements/{item['id']}",
                     json={"values": {"no_of_shirts": "3"}, "rate": "966.666"}).get_json()
    assert upd["rate"] == 966.666 and upd["amount"] == 2900.0
    for bad in ("nan", "-1", "abc"):
        assert client.put(f"/api/measurements/{item['id']}",
                          json={"values": {}, "rate": bad}).status_code == 400


# ---------------------------------------------------------------------------
# The read-only check recognises the same rules
# ---------------------------------------------------------------------------
def test_data_check_flags_amounts_with_fractions_of_a_paisa_but_not_rates(client):
    import sqlite3
    import db.tailoring as tdb
    from db.connection import DB_PATH
    from services.data_check import run_checks
    t = sqlite3.connect(tdb.TAILORING_DB_PATH)
    t.execute("INSERT INTO tailoring_orders (order_number, order_date, customer_name, total, advance, balance) "
              "VALUES (1, '2026-11-01', 'A', 2900, 100.005, 2799.995)")
    oid = t.execute("SELECT id FROM tailoring_orders").fetchone()[0]
    t.execute("INSERT INTO tailoring_items (order_id, garment_type, qty, rate, amount) VALUES (?, 'Shirt', 3, 966.666, 2900)", (oid,))
    t.commit()
    t.close()
    problems, _ = run_checks(DB_PATH, tdb.TAILORING_DB_PATH, None)
    flagged = {(p["table"], p["detail"].split(" =")[0]) for p in problems
               if p["check"] == "Amount with fractions of a paisa"}
    assert flagged == {("tailoring_orders", "advance"), ("tailoring_orders", "balance")}   # the rate is fine
