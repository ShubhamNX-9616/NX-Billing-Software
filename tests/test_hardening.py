"""Tests for the production-hardening batch:

- editing a cancelled bill must not move stock
- sessions end when a user is deactivated / has their password changed / role changed
- the login lockout cannot be dodged with a forged X-Forwarded-For
- request size limit + safe, logged error responses (no leaked internals)
- concurrent payments / stock sales are serialised (no overpay, no lost update)
- dates follow IST, not the server's clock
- ?limit= / ?offset= paging on the bill lists

Temp databases only; the real billing.db / tailoring.db / measurements.db are never touched.
"""
import logging
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone

import pytest
from flask import Flask, request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# App fixture: real auth + billing blueprints on temp databases
# ---------------------------------------------------------------------------
@pytest.fixture
def app(tmp_path, monkeypatch):
    import db.connection as conn_mod
    import db.measurements as mdb
    import db.tailoring as tdb
    import routes.measurements as mr
    import routes.tailoring as tr
    import routes.tailoring_suits as ts
    from db import close_db, init_db, seed_default_users
    from extensions import bcrypt
    from routes.auth import auth_routes
    from routes.bills import bills_bp
    from routes.institution_bills import inst_bills_bp
    from routes.inventory import inventory_bp
    from routes.loyalty import loyalty_bp
    from services.auth import check_session_valid, login_required
    from services.errors import install_error_handlers
    from services.security import install_request_limits

    monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "billing_test.db"))
    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", str(tmp_path / "tailoring_test.db"))
    monkeypatch.setattr(mdb, "MEASUREMENTS_DB_PATH", str(tmp_path / "measurements_test.db"))
    monkeypatch.setattr(tr, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(ts, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(mr, "UPLOAD_DIR", str(tmp_path / "uploads_m"))

    flask_app = Flask(__name__, template_folder=os.path.join(PROJECT_ROOT, "templates"),
                      static_folder=os.path.join(PROJECT_ROOT, "static"))
    flask_app.secret_key = "test"
    flask_app.config["TESTING"] = False        # exercise the real error handlers
    bcrypt.init_app(flask_app)
    init_db()
    seed_default_users(bcrypt)
    tdb.init_tailoring_db()
    mdb.init_measurements_db()

    for bp in (auth_routes, bills_bp, inst_bills_bp, inventory_bp, loyalty_bp):
        flask_app.register_blueprint(bp, url_prefix="" if bp is auth_routes else "/api")
    flask_app.register_blueprint(tr.tailoring_api_bp, url_prefix="/api")
    flask_app.register_blueprint(ts.tailoring_suit_api_bp, url_prefix="/api")
    flask_app.register_blueprint(mr.measurements_api_bp, url_prefix="/api")
    flask_app.teardown_appcontext(close_db)
    flask_app.teardown_appcontext(tdb.close_tailoring_db)
    flask_app.teardown_appcontext(mdb.close_measurements_db)
    flask_app.before_request(check_session_valid)
    install_request_limits(flask_app, 1)
    install_error_handlers(flask_app)

    @flask_app.context_processor
    def _ctx():
        return {"sv": "t"}

    @flask_app.route("/_page")
    @login_required
    def _page():
        return "page ok"

    # the login view redirects to these page endpoints (their real blueprints render
    # heavy templates, so stubs stand in)
    flask_app.add_url_rule("/", "pages.dashboard", lambda: "dashboard")
    flask_app.add_url_rule("/new-bill", "pages.new_bill", lambda: "new bill")
    flask_app.add_url_rule("/tailoring", "tailoring_pages.tailoring_page", lambda: "tailoring")

    @flask_app.route("/_ip")
    def _ip():
        return request.remote_addr or ""

    import routes.auth as auth_mod
    auth_mod._attempt_store.clear()
    yield flask_app
    auth_mod._attempt_store.clear()


def _login(app, username="admin", password="Admin@1234"):
    c = app.test_client()
    r = c.post("/login", data={"username": username, "password": password})
    assert r.status_code == 302, r.get_data(as_text=True)[:200]
    return c


def _db():
    import db.connection as conn_mod
    return conn_mod._open_connection()


def _user_id(username):
    conn = _db()
    uid = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()[0]
    conn.close()
    return uid


def _sql(query, params=()):
    conn = _db()
    conn.execute(query, params)
    conn.commit()
    conn.close()


def _bill_body(**over):
    body = {"customer_name": "Ravi", "customer_mobile": "9876543210", "bill_date": "2026-11-01",
            "salesperson_name": "Self", "payment_mode_type": "Cash",
            "items": [{"cloth_type": "Shirting", "company_name": "Monti", "quantity": 2, "mrp": 500}]}
    body.update(over)
    return body


# ---------------------------------------------------------------------------
# Cancelled bills do not move stock when edited
# ---------------------------------------------------------------------------
def _stock(item_id):
    conn = _db()
    n = conn.execute("SELECT current_stock FROM inventory_items WHERE id = ?", (item_id,)).fetchone()[0]
    conn.close()
    return n


def _make_item(client, stock=10):
    r = client.post("/api/inventory", json={"cloth_type": "Shirting", "company_name": "Monti",
                                            "mrp": 500, "cost_price": 300, "opening_stock": stock})
    assert r.status_code == 201, r.get_json()
    return r.get_json()["id"]


def test_editing_a_cancelled_bill_leaves_stock_alone(app):
    c = _login(app)
    item = _make_item(c, 10)
    body = _bill_body()
    body["items"][0].update(quantity=4, inventory_item_id=item)
    bill = c.post("/api/bills", json=body).get_json()
    assert _stock(item) == 6                                   # sold 4

    assert c.put(f"/api/bills/{bill['id']}/cancel").status_code == 200
    assert _stock(item) == 10                                  # handed back

    body["items"][0]["quantity"] = 3                           # edit while cancelled
    assert c.put(f"/api/bills/{bill['id']}", json=body).status_code == 200
    assert _stock(item) == 10                                  # the old bug: this became 11

    body["items"][0]["quantity"] = 5
    assert c.put(f"/api/bills/{bill['id']}", json=body).status_code == 200
    assert _stock(item) == 10

    assert c.put(f"/api/bills/{bill['id']}/restore").status_code == 200
    assert _stock(item) == 5                                   # restore deducts the CURRENT quantity


def test_editing_an_active_bill_still_adjusts_stock(app):
    c = _login(app)
    item = _make_item(c, 10)
    body = _bill_body()
    body["items"][0].update(quantity=4, inventory_item_id=item)
    bill = c.post("/api/bills", json=body).get_json()
    body["items"][0]["quantity"] = 7
    assert c.put(f"/api/bills/{bill['id']}", json=body).status_code == 200
    assert _stock(item) == 3


# ---------------------------------------------------------------------------
# Sessions follow the account
# ---------------------------------------------------------------------------
def test_deactivated_user_is_signed_out_on_the_next_request(app):
    staff = _login(app, "staff", "Staff@1234")
    assert staff.get("/api/server-date").status_code == 200
    assert staff.get("/_page").status_code == 200
    _sql("UPDATE users SET is_active = 0 WHERE username = 'staff'")
    r = staff.get("/api/server-date")
    assert r.status_code == 401 and "session has ended" in r.get_json()["error"]
    # a page request is sent to the login screen, and stays signed out
    assert staff.get("/_page").status_code == 302
    assert staff.get("/api/server-date").status_code == 401


def test_deleted_user_is_signed_out(app):
    staff = _login(app, "staff", "Staff@1234")
    _sql("DELETE FROM users WHERE username = 'staff'")
    assert staff.get("/api/server-date").status_code == 401


def test_admin_password_reset_signs_the_user_out_everywhere(app):
    admin = _login(app)
    phone, desk = _login(app, "staff", "Staff@1234"), _login(app, "staff", "Staff@1234")
    assert phone.get("/api/server-date").status_code == 200
    r = admin.put(f"/api/users/{_user_id('staff')}/password",
                  json={"new_password": "NewPass#1", "confirm_password": "NewPass#1"})
    assert r.status_code == 200
    assert phone.get("/api/server-date").status_code == 401
    assert desk.get("/api/server-date").status_code == 401
    assert admin.get("/api/bills").status_code == 200           # the admin is unaffected
    assert _login(app, "staff", "NewPass#1").get("/api/server-date").status_code == 200


def test_own_password_change_keeps_this_device_but_ends_the_others(app):
    here, other = _login(app, "staff", "Staff@1234"), _login(app, "staff", "Staff@1234")
    r = here.put("/api/users/me/password", json={"current_password": "Staff@1234",
                                                 "new_password": "Fresh#123", "confirm_password": "Fresh#123"})
    assert r.status_code == 200
    assert here.get("/api/server-date").status_code == 200       # still signed in here
    assert other.get("/api/server-date").status_code == 401      # signed out elsewhere


def test_role_changes_apply_immediately(app):
    admin, staff = _login(app), _login(app, "staff", "Staff@1234")
    assert staff.get("/api/bills").status_code == 403            # staff cannot list bills
    _sql("UPDATE users SET role = 'admin' WHERE username = 'staff'")
    assert staff.get("/api/bills").status_code == 200            # promoted: no re-login needed
    _sql("UPDATE users SET role = 'staff' WHERE username = 'admin'")
    assert admin.get("/api/bills").status_code == 403            # demoted just as fast


def test_session_from_before_the_upgrade_is_accepted_and_stamped(app):
    c = app.test_client()
    with c.session_transaction() as sess:                        # no "pwf" stamp, as an old cookie
        sess["user_id"] = _user_id("admin")
        sess["username"] = "admin"
        sess["role"] = "admin"
    assert c.get("/api/bills").status_code == 200
    with c.session_transaction() as sess:
        assert sess.get("pwf")                                   # stamped on first sight
    _sql("UPDATE users SET password_hash = 'changed' WHERE username = 'admin'")
    assert c.get("/api/bills").status_code == 401                # and now it is bound to the password


def test_anonymous_requests_are_unchanged(app):
    c = app.test_client()
    assert c.get("/api/bills").status_code == 401
    assert c.get("/_page").status_code == 302


# ---------------------------------------------------------------------------
# Login lockout cannot be dodged with a forged X-Forwarded-For
# ---------------------------------------------------------------------------
def test_lockout_ignores_a_forged_forwarded_for_header(app):
    c = app.test_client()
    for n in range(5):
        r = c.post("/login", data={"username": "admin", "password": "wrong"},
                   headers={"X-Forwarded-For": f"10.0.0.{n}"})       # a "new address" every time
        assert "Invalid username or password" in r.get_data(as_text=True) or "Too many" in r.get_data(as_text=True)
    r = c.post("/login", data={"username": "admin", "password": "Admin@1234"},
               headers={"X-Forwarded-For": "203.0.113.77"})
    assert r.status_code == 200
    assert "Too many failed attempts" in r.get_data(as_text=True)     # locked, even with the right password


def test_proxy_fix_uses_the_address_our_proxy_appended():
    from services.security import install_proxy_fix
    flask_app = Flask(__name__)

    @flask_app.route("/ip")
    def ip():
        return request.remote_addr

    install_proxy_fix(flask_app, 1)
    c = flask_app.test_client()
    # the client claims to be 1.1.1.1; the proxy appended the real address last
    r = c.get("/ip", headers={"X-Forwarded-For": "1.1.1.1, 198.51.100.9"})
    assert r.get_data(as_text=True) == "198.51.100.9"
    assert c.get("/ip").get_data(as_text=True) == "127.0.0.1"        # no header: unchanged

    plain = Flask(__name__)
    plain.add_url_rule("/ip", "ip", ip)
    install_proxy_fix(plain, 0)                                      # nothing in front: header ignored
    assert plain.test_client().get("/ip", headers={"X-Forwarded-For": "1.1.1.1"}).get_data(as_text=True) == "127.0.0.1"


def test_env_int_falls_back_on_garbage(monkeypatch):
    from services.security import env_int
    monkeypatch.setenv("X_TEST", "3")
    assert env_int("X_TEST", 9) == 3
    monkeypatch.setenv("X_TEST", "three")
    assert env_int("X_TEST", 9) == 9
    monkeypatch.delenv("X_TEST")
    assert env_int("X_TEST", 9) == 9


# ---------------------------------------------------------------------------
# Upload limit + error handling
# ---------------------------------------------------------------------------
def test_oversized_request_is_refused_with_a_clear_message(app):
    import io
    c = _login(app)
    order = c.post("/api/tailoring/orders", json={
        "order_number": 1, "customer_name": "A", "mobile": "9876543210",
        "items": [{"garment_type": "Shirt", "qty": 1, "rate": 100}]}).get_json()
    big = b"x" * (2 * 1024 * 1024)                                   # limit in this fixture is 1 MB
    r = c.post(f"/api/tailoring/orders/{order['id']}/photos", data={"photo": (io.BytesIO(big), "a.jpg")},
               content_type="multipart/form-data")
    assert r.status_code == 413
    assert "too large" in r.get_json()["error"] and "1 MB" in r.get_json()["error"]


@pytest.mark.parametrize("url", ["/api/tailoring/orders", "/api/tailoring/suits/orders", "/api/bills",
                                 "/api/institution-bills", "/api/inventory"])
def test_oversized_json_body_is_a_413_not_a_500(app, url):
    """These routes read the body inside `try ... except Exception`; that block used
    to turn Flask's 'request too large' into a 500 "something went wrong"."""
    c = _login(app)
    r = c.post(url, data=b'{"x": "' + b"a" * (2 * 1024 * 1024) + b'"}', content_type="application/json")
    assert r.status_code == 413, r.get_data(as_text=True)[:200]
    assert "too large" in r.get_json()["error"]


def test_server_error_lets_http_errors_through(app):
    from werkzeug.exceptions import RequestEntityTooLarge
    from services.errors import server_error
    with app.test_request_context("/api/x", method="POST"):
        with pytest.raises(RequestEntityTooLarge):
            server_error(RequestEntityTooLarge())


def test_request_limit_and_pixel_cap_are_installed():
    from PIL import Image
    from services.security import MAX_IMAGE_PIXELS, install_request_limits
    flask_app = Flask(__name__)
    install_request_limits(flask_app, 7)
    assert flask_app.config["MAX_CONTENT_LENGTH"] == 7 * 1024 * 1024
    assert Image.MAX_IMAGE_PIXELS == MAX_IMAGE_PIXELS


def test_unexpected_errors_are_logged_but_never_leaked(app, caplog, monkeypatch):
    import routes.bills as bills_mod

    def boom(*a, **k):
        raise RuntimeError("secret table bills_x at /srv/app/billing.db")

    monkeypatch.setattr(bills_mod, "validate_and_calculate_items", boom)
    c = _login(app)
    with caplog.at_level(logging.ERROR):
        r = c.post("/api/bills", json=_bill_body())
    assert r.status_code == 500
    assert "secret" not in r.get_data(as_text=True) and "billing.db" not in r.get_data(as_text=True)
    assert "went wrong" in r.get_json()["error"]
    logged = "\n".join(rec.getMessage() + (str(rec.exc_info[1]) if rec.exc_info else "") for rec in caplog.records)
    assert "secret table" in logged and "/api/bills" in logged        # the admin can find it in the log


def test_unhandled_exceptions_and_http_errors_get_safe_responses(app, caplog):
    @app.route("/api/_boom")
    def api_boom():
        raise RuntimeError("internal detail")

    @app.route("/_boom")
    def page_boom():
        raise RuntimeError("internal detail")

    c = _login(app)
    with caplog.at_level(logging.ERROR):
        api = c.get("/api/_boom")
        page = c.get("/_boom")
    assert api.status_code == 500 and api.is_json and "internal detail" not in api.get_data(as_text=True)
    assert page.status_code == 500 and "internal detail" not in page.get_data(as_text=True)
    assert "internal detail" in caplog.text
    missing = c.get("/api/_nope")
    assert missing.status_code == 404 and missing.is_json         # API callers always get JSON
    assert c.get("/_nope").status_code == 404 and not c.get("/_nope").is_json


def test_server_error_helper_is_generic_and_logs(app, caplog):
    from services.errors import GENERIC_500, server_error
    with app.test_request_context("/api/x", method="POST"):
        try:
            raise ValueError("db password is hunter2")
        except ValueError as e:
            with caplog.at_level(logging.ERROR):
                resp, status = server_error(e)
    assert status == 500 and resp.get_json() == {"error": GENERIC_500}
    assert "hunter2" in caplog.text and "POST /api/x" in caplog.text


# ---------------------------------------------------------------------------
# Concurrency: two requests at the same instant
# ---------------------------------------------------------------------------
def _race(app, requests_):
    """Run each (method, url, body) from its own signed-in client at the same moment."""
    clients = [_login(app) for _ in requests_]
    barrier = threading.Barrier(len(requests_))
    out = [None] * len(requests_)

    def go(i):
        method, url, body = requests_[i]
        barrier.wait()
        out[i] = getattr(clients[i], method)(url, json=body)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(len(requests_))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return out


def _slow(original, delay=0.4):
    def wrapper(*a, **k):
        result = original(*a, **k)
        time.sleep(delay)          # widen the gap between "read the balance" and "write it"
        return result
    return wrapper


def test_two_simultaneous_payments_cannot_overpay_a_bill(app, monkeypatch):
    import routes.bills as bills_mod
    c = _login(app)
    bill = c.post("/api/bills", json=_bill_body()).get_json()           # 1000 due
    monkeypatch.setattr(bills_mod, "apply_payment", _slow(bills_mod.apply_payment))
    url = f"/api/bills/{bill['id']}/record-payment"
    out = _race(app, [("post", url, {"payment_method": "Cash", "amount": 1000})] * 2)
    assert sorted(r.status_code for r in out) == [200, 400]
    got = c.get(f"/api/bills/{bill['id']}").get_json()
    assert got["advance_paid"] == 1000 and got["remaining"] == 0
    assert len(got["payments"]) == 1


def test_two_simultaneous_sales_of_the_same_stock_both_count(app, monkeypatch):
    import services.inventory as inv_mod
    c = _login(app)
    item = _make_item(c, 10)
    monkeypatch.setattr(inv_mod, "r2", _slow(inv_mod.r2, 0.3))
    body = _bill_body()
    body["items"][0].update(quantity=6, inventory_item_id=item)
    out = _race(app, [("post", "/api/bills", body)] * 2)
    assert [r.status_code for r in out] == [201, 201]
    assert _stock(item) == -2        # 10 - 6 - 6. A lost update would leave 4 (one sale forgotten).


def test_two_simultaneous_tailoring_payments_cannot_overpay(app, monkeypatch):
    import routes.tailoring_common as tc          # the shared code both books run
    c = _login(app)
    order = c.post("/api/tailoring/orders", json={
        "order_number": 1, "customer_name": "A", "mobile": "9876543210",
        "items": [{"garment_type": "Shirt", "qty": 1, "rate": 500}]}).get_json()
    monkeypatch.setattr(tc, "_final_total", _slow(tc._final_total))
    out = _race(app, [("post", f"/api/tailoring/orders/{order['id']}/payments", {"amount": 500})] * 2)
    assert sorted(r.status_code for r in out) == [201, 400]
    got = c.get(f"/api/tailoring/orders/{order['id']}").get_json()
    assert got["advance"] == 500 and got["balance"] == 0 and len(got["payments"]) == 1


def test_two_simultaneous_suit_payments_cannot_overpay(app, monkeypatch):
    import routes.tailoring_common as tc
    c = _login(app)
    order = c.post("/api/tailoring/suits/orders", json={
        "book_no": "1", "order_number": 1, "customer_name": "A", "mobile": "9876543210",
        "items": [{"garment_type": "Suit", "qty": 1, "rate": 3500}]}).get_json()
    monkeypatch.setattr(tc, "_final_total", _slow(tc._final_total))
    out = _race(app, [("post", f"/api/tailoring/suits/orders/{order['id']}/payments", {"amount": 3500})] * 2)
    assert sorted(r.status_code for r in out) == [201, 400]
    assert c.get(f"/api/tailoring/suits/orders/{order['id']}").get_json()["balance"] == 0


def test_two_simultaneous_measurement_payments_cannot_overpay(app, monkeypatch):
    import routes.measurement_orders as mo
    c = _login(app)
    cust = c.post("/api/measurements/customers", json={"name": "A", "mobile": "9876543210"}).get_json()
    order = c.post("/api/measurements/orders", json={
        "customer_id": cust["id"], "items": [{"garment_type": "shirt", "rate": 500, "values": {}}]}).get_json()
    monkeypatch.setattr(mo, "final_total", _slow(mo.final_total))
    out = _race(app, [("post", f"/api/measurements/orders/{order['id']}/payments", {"amount": 500})] * 2)
    assert sorted(r.status_code for r in out) == [201, 400]
    got = c.get(f"/api/measurements/orders/{order['id']}").get_json()
    assert got["advance"] == 500 and got["balance"] == 0 and len(got["payments"]) == 1


def test_two_simultaneous_institution_payments_cannot_overpay(app, monkeypatch):
    import routes.institution_bills as ib
    c = _login(app)
    bill = c.post("/api/institution-bills", json={
        "company_name": "Acme", "bill_date": "2026-11-01", "payment_mode_type": "Cash",
        "items": [{"cloth_type": "Suiting", "company_name": "Raymond", "quantity_per_pc": 1,
                   "rate_per_m": 1000, "no_of_pcs": 1}]}).get_json()
    monkeypatch.setattr(ib, "apply_payment", _slow(ib.apply_payment))
    out = _race(app, [("post", f"/api/institution-bills/{bill['id']}/record-payment",
                       {"payment_method": "Cash", "amount": 1000})] * 2)
    assert sorted(r.status_code for r in out) == [200, 400]
    assert c.get(f"/api/institution-bills/{bill['id']}").get_json()["bill"]["remaining"] == 0


def test_two_simultaneous_cancels_restore_stock_only_once(app, monkeypatch):
    import services.inventory as inv_mod
    c = _login(app)
    item = _make_item(c, 10)
    body = _bill_body()
    body["items"][0].update(quantity=4, inventory_item_id=item)
    bill = c.post("/api/bills", json=body).get_json()
    monkeypatch.setattr(inv_mod, "r2", _slow(inv_mod.r2, 0.3))
    out = _race(app, [("put", f"/api/bills/{bill['id']}/cancel", None)] * 2)
    assert sorted(r.status_code for r in out) == [200, 400]
    assert _stock(item) == 10                    # 6 + 4, not 14


# ---------------------------------------------------------------------------
# IST, not the server's clock
# ---------------------------------------------------------------------------
class _UtcServerClock(datetime):
    """A server whose own clock is UTC: it is 19:00 UTC on 31 Mar 2027, which is
    00:30 on 1 Apr 2027 in India - already the new financial year."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2027, 3, 31, 19, 0, tzinfo=timezone.utc).astimezone(tz) if tz else \
            datetime(2027, 3, 31, 19, 0)


def test_today_and_financial_year_follow_ist(monkeypatch):
    import utils
    from db.connection import current_fy
    monkeypatch.setattr(utils, "datetime", _UtcServerClock)
    assert utils.ist_today() == date(2027, 4, 1)           # the server's own date would say 31 Mar
    assert current_fy() == "27-28"                          # date.today() on that server gave "26-27"


def test_financial_year_just_before_ist_midnight(monkeypatch):
    import utils
    from db.connection import current_fy

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2027, 3, 31, 18, 29, tzinfo=timezone.utc).astimezone(tz)   # 23:59 IST

    monkeypatch.setattr(utils, "datetime", Clock)
    assert utils.ist_today() == date(2027, 3, 31) and current_fy() == "26-27"


def test_loyalty_cycle_uses_the_shops_day(monkeypatch):
    import services.loyalty as loyalty
    seen = {}

    class FakeDb:
        def execute(self, *a, **k):
            seen["called"] = True

            class R:
                def fetchone(self_inner):
                    return None
            return R()

    monkeypatch.setattr(loyalty, "ist_today", lambda: date(2030, 1, 1))
    # no cycles and no activation date -> None, but only after resolving "today" via ist_today
    assert loyalty.get_current_cycle(FakeDb()) is None and seen["called"]


def test_marking_a_gift_given_stamps_ist(app):
    c = _login(app)
    bill = c.post("/api/bills", json=_bill_body()).get_json()
    conn = _db()
    conn.execute("INSERT INTO loyalty_cycles (cycle_number, start_date, end_date) VALUES (1, '2026-01-01', '2027-01-01')")
    conn.execute("INSERT INTO loyalty_gifts (customer_id, tier, cycle_id, bill_id) VALUES (?, 'silver', 1, ?)",
                 (bill["customer_id"], bill["id"]))
    conn.commit()
    conn.close()
    gift_id = c.get("/api/loyalty/pending-gifts").get_json()[0]["id"]
    assert c.post(f"/api/loyalty/gifts/{gift_id}/mark-given").status_code == 200
    conn = _db()
    stamp = conn.execute("SELECT given_at FROM loyalty_gifts WHERE id = ?", (gift_id,)).fetchone()[0]
    conn.close()
    given = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
    assert abs((datetime.now(IST) - given).total_seconds()) < 120     # IST wall-clock, whatever the server says


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------
def _make_bills(c, n):
    ids = []
    for i in range(n):
        r = c.post("/api/bills", json=_bill_body(customer_name=f"Cust {i}", customer_mobile=f"98765432{i:02d}"))
        assert r.status_code == 201, r.get_json()
        ids.append(r.get_json()["id"])
    return ids


def test_bill_list_pages_through_everything_exactly_once(app):
    c = _login(app)
    ids = _make_bills(c, 7)
    seen = []
    for offset in (0, 3, 6):
        r = c.get(f"/api/bills?limit=3&offset={offset}")
        assert r.status_code == 200 and r.headers["X-Total-Count"] == "7"
        seen += [b["id"] for b in r.get_json()]
    assert seen == sorted(ids, reverse=True)                  # newest first, no repeats, no gaps
    assert c.get("/api/bills?limit=3&offset=9").get_json() == []


def test_bill_list_without_a_limit_is_unchanged(app):
    c = _login(app)
    _make_bills(c, 4)
    r = c.get("/api/bills")
    assert len(r.get_json()) == 4 and r.headers["X-Total-Count"] == "4"
    assert len(c.get("/api/bills?limit=2").get_json()) == 2     # the dashboard's "latest 10" style call
    assert len(c.get("/api/bills?limit=-5&offset=-3").get_json()) == 4   # nonsense values are ignored


def test_bill_search_pages_and_reports_the_match_count(app):
    c = _login(app)
    _make_bills(c, 6)
    r = c.get("/api/bills/search?name=Cust&limit=4")
    assert len(r.get_json()) == 4 and r.headers["X-Total-Count"] == "6"
    r = c.get("/api/bills/search?name=Cust&limit=4&offset=4")
    assert len(r.get_json()) == 2
    r = c.get("/api/bills/search?name=Cust 3")
    assert len(r.get_json()) == 1 and r.headers["X-Total-Count"] == "1"
    r = c.get("/api/bills?search=Cust&limit=2")
    assert len(r.get_json()) == 2 and r.headers["X-Total-Count"] == "6"


def test_institution_lists_page_too(app):
    c = _login(app)
    for i in range(5):
        r = c.post("/api/institution-bills", json={
            "company_name": f"Acme {i}", "bill_date": "2026-11-01", "payment_mode_type": "Cash",
            "items": [{"cloth_type": "Suiting", "company_name": "Raymond", "quantity_per_pc": 1,
                       "rate_per_m": 100, "no_of_pcs": 1}]})
        assert r.status_code == 201
    r = c.get("/api/institution-bills?limit=2&offset=2")
    assert len(r.get_json()) == 2 and r.headers["X-Total-Count"] == "5"
    assert len(c.get("/api/institution-bills").get_json()) == 5
    r = c.get("/api/institution-bills/search?name=Acme&limit=3")
    assert len(r.get_json()) == 3 and r.headers["X-Total-Count"] == "5"


def test_page_args_caps_the_page_size(app):
    from services.paging import MAX_PAGE_SIZE, page_args, page_sql
    with app.test_request_context("/x?limit=999999&offset=5"):
        assert page_args() == (MAX_PAGE_SIZE, 5)
    with app.test_request_context("/x?offset=7"):
        assert page_args() == (None, 7) and page_sql(None, 7) == " LIMIT -1 OFFSET 7"
    with app.test_request_context("/x"):
        assert page_args() == (None, 0) and page_sql(None, 0) == ""
