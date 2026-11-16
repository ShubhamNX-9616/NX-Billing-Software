"""Tests for the schema / validation / hardening batch:

1. performance indexes exist and are actually used
2. migrations: re-runnable, atomic, and an existing database is backed up before an upgrade
3. dates are validated wherever they are accepted
4. security headers, and logout only ends the session on POST
5. first-run passwords are no longer the published defaults
plus the read-only data check script.

Temp databases only; the real ones are never touched.
"""
import glob
import os
import sqlite3
import subprocess
import sys
import time

import pytest
from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# reuse the app fixtures / helpers from the earlier hardening tests
from test_hardening import _login, app  # noqa: E402,F401
from test_numeric_and_data_fixes import (_bill_body, _inst_body, _raw, _s_body,  # noqa: E402,F401
                                         _t_body, client)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def billing_path(tmp_path, monkeypatch):
    import db.connection as conn_mod
    path = str(tmp_path / "billing_test.db")
    monkeypatch.setattr(conn_mod, "DB_PATH", path)
    return path


def _conn(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _versions(path):
    c = _conn(path)
    out = {r[0] for r in c.execute("SELECT version FROM schema_version")}
    c.close()
    return out


def _index_names(path):
    c = _conn(path)
    out = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    c.close()
    return out


def _plan(path, sql, params=()):
    c = _conn(path)
    rows = c.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    c.close()
    return " | ".join(r["detail"] for r in rows)


# ---------------------------------------------------------------------------
# 1. Indexes
# ---------------------------------------------------------------------------
def test_performance_indexes_exist_on_a_fresh_database(billing_path):
    from db import init_db
    init_db()
    assert {"idx_bills_bill_date", "idx_bills_customer_date", "idx_inst_bills_bill_date",
            "idx_inventory_transactions_item_id"} <= _index_names(billing_path)


def test_the_queries_the_app_runs_use_those_indexes(billing_path):
    from db import init_db
    init_db()
    assert "idx_bills_bill_date" in _plan(
        billing_path, "SELECT id FROM bills WHERE bill_date >= ? AND bill_date <= ?", ("2026-01-01", "2026-12-31"))
    assert "idx_inventory_transactions_item_id" in _plan(
        billing_path, "SELECT * FROM inventory_transactions WHERE item_id = ?", (1,))
    assert "idx_bills_customer_date" in _plan(
        billing_path, "SELECT SUM(final_total) FROM bills WHERE customer_id = ? AND bill_date >= ? AND bill_date < ?",
        (1, "2026-01-01", "2027-01-01"))
    assert "idx_inst_bills_bill_date" in _plan(
        billing_path, "SELECT id FROM institution_bills WHERE bill_date >= ?", ("2026-01-01",))


def test_old_databases_without_a_version_table_still_get_the_indexes(billing_path):
    """The one-off 'stamp everything as applied' path used to skip new migrations."""
    from db import init_db
    init_db()
    c = _conn(billing_path)
    for name in ("idx_bills_bill_date", "idx_bills_customer_date", "idx_inst_bills_bill_date",
                 "idx_inventory_transactions_item_id"):
        c.execute(f"DROP INDEX {name}")
    c.execute("DROP TABLE schema_version")
    c.commit()
    c.close()
    init_db()
    assert "idx_bills_bill_date" in _index_names(billing_path)
    assert 33 in _versions(billing_path)


# ---------------------------------------------------------------------------
# 2. Migrations
# ---------------------------------------------------------------------------
def test_fresh_database_applies_every_migration(billing_path):
    from db import init_db
    from db.schema import MIGRATIONS
    init_db()
    assert _versions(billing_path) == {v for v, _ in MIGRATIONS}


def test_migrations_17_and_18_survive_a_second_run(billing_path):
    """The old versions died with 'duplicate column name' if the app stopped after
    adding the column but before recording the migration."""
    from db import init_db
    init_db()
    c = _conn(billing_path)
    c.execute("DELETE FROM schema_version WHERE version IN (17, 18)")
    c.commit()
    c.close()
    init_db()                                   # must not raise
    assert {17, 18} <= _versions(billing_path)
    c = _conn(billing_path)
    cols = [r[1] for r in c.execute("PRAGMA table_info(institution_bills)")]
    items = [r[1] for r in c.execute("PRAGMA table_info(institution_bill_items)")]
    c.close()
    assert cols.count("company_address") == 1 and items.count("stitching_per_unit") == 1


def test_every_migration_can_be_run_twice_without_losing_data(billing_path):
    from db import init_db
    from db.schema import MIGRATIONS
    init_db()
    c = _conn(billing_path)
    c.execute("INSERT INTO suppliers (name, normalized_name) VALUES ('S', 's')")
    c.execute("INSERT INTO inventory_items (cloth_type, company_name, quality_number, item_code, current_stock) "
              "VALUES ('Suiting', 'Raymond', 'Q1', 'SUT-001', 7)")
    c.commit()
    for version, fn in MIGRATIONS:
        try:
            fn(c)
            fn(c)
            c.commit()
        except Exception as exc:                # pragma: no cover - the message names the culprit
            pytest.fail(f"migration {version} ({fn.__name__}) is not re-runnable: {exc}")
    stock = c.execute("SELECT current_stock FROM inventory_items WHERE item_code = 'SUT-001'").fetchone()[0]
    c.close()
    assert stock == 7


def test_a_failing_migration_rolls_back_completely(billing_path, monkeypatch):
    import db.schema as schema
    schema.init_db()

    def half_done(conn):
        conn.execute("ALTER TABLE customers ADD COLUMN half_done TEXT")
        raise RuntimeError("disk full")

    monkeypatch.setattr(schema, "MIGRATIONS", schema.MIGRATIONS + [(99, half_done)])
    with pytest.raises(RuntimeError):
        schema.init_db()
    c = _conn(billing_path)
    cols = [r[1] for r in c.execute("PRAGMA table_info(customers)")]
    c.close()
    assert "half_done" not in cols                     # the ALTER was undone with it
    assert 99 not in _versions(billing_path)           # and it is not recorded as applied

    # once the migration is fixed, the next start applies it normally
    monkeypatch.setattr(schema, "MIGRATIONS", schema.MIGRATIONS[:-1] + [
        (99, lambda conn: conn.execute("ALTER TABLE customers ADD COLUMN fixed TEXT"))])
    schema.init_db()
    c = _conn(billing_path)
    cols = [r[1] for r in c.execute("PRAGMA table_info(customers)")]
    c.close()
    assert "fixed" in cols and 99 in _versions(billing_path)


def _backups(billing_path):
    return sorted(glob.glob(os.path.join(os.path.dirname(billing_path), "backups",
                                         "billing_before_migration_*.db")))


def test_fresh_and_up_to_date_databases_are_not_backed_up(billing_path):
    from db import init_db
    init_db()
    init_db()
    assert _backups(billing_path) == []


def test_upgrading_an_existing_database_makes_a_backup_first(billing_path):
    from db import init_db
    init_db()
    c = _conn(billing_path)
    c.execute("INSERT INTO customers (name, mobile, normalized_mobile) VALUES ('Ravi', '9876543210', '9876543210')")
    c.execute("DELETE FROM schema_version WHERE version = 33")        # pretend the last upgrade is pending
    c.commit()
    c.close()
    init_db()
    backups = _backups(billing_path)
    assert len(backups) == 1 and "_v33_" in os.path.basename(backups[0])
    copy = _conn(backups[0])                                         # a real, readable copy with the data
    assert copy.execute("SELECT name FROM customers").fetchone()[0] == "Ravi"
    assert copy.execute("SELECT 1 FROM schema_version WHERE version = 33").fetchone() is None  # taken BEFORE
    copy.close()
    assert 33 in _versions(billing_path)


def test_only_the_newest_few_backups_are_kept(billing_path):
    from db import init_db
    from db.schema import PRE_MIGRATION_BACKUPS_KEPT
    init_db()
    for _ in range(PRE_MIGRATION_BACKUPS_KEPT + 3):
        c = _conn(billing_path)
        c.execute("DELETE FROM schema_version WHERE version = 33")
        c.commit()
        c.close()
        init_db()
        time.sleep(1.05)                                             # backup names carry the second
    assert len(_backups(billing_path)) == PRE_MIGRATION_BACKUPS_KEPT


def test_a_backup_problem_does_not_stop_the_upgrade(billing_path, monkeypatch):
    import db.schema as schema
    schema.init_db()
    c = _conn(billing_path)
    c.execute("DELETE FROM schema_version WHERE version = 33")
    c.commit()
    c.close()
    monkeypatch.setattr(schema.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only disk")))
    schema.init_db()                                                 # logs, carries on
    assert 33 in _versions(billing_path)


# ---------------------------------------------------------------------------
# 3. Dates
# ---------------------------------------------------------------------------
BAD_DATES = ["31/11/2026", "2026-02-30", "yesterday", "2026-1-5", "0226-01-01", "2026-11-15T10:00", "20261115"]


@pytest.mark.parametrize("bad", BAD_DATES)
def test_bill_with_a_bad_date_is_refused_and_not_saved(client, bad):
    r = client.post("/api/bills", json=_bill_body(bill_date=bad))
    assert r.status_code == 400 and "bill_date" in r.get_json()["error"]
    assert client.get("/api/bills").get_json() == []


def test_bill_update_with_a_bad_date_is_refused(client):
    bill = client.post("/api/bills", json=_bill_body()).get_json()
    r = client.put(f"/api/bills/{bill['id']}", json=_bill_body(bill_date="31/11/2026"))
    assert r.status_code == 400
    assert client.get(f"/api/bills/{bill['id']}").get_json()["bill_date"] == "2026-11-01"


def test_valid_dates_are_still_accepted(client):
    assert client.post("/api/bills", json=_bill_body(bill_date="2026-12-31")).status_code == 201
    assert client.post("/api/bills", json=_bill_body(bill_date="2024-02-29")).status_code == 201   # leap day


@pytest.mark.parametrize("bad", BAD_DATES)
def test_bill_payment_date_is_validated(client, bad):
    bill = client.post("/api/bills", json=_bill_body()).get_json()
    r = client.post(f"/api/bills/{bill['id']}/record-payment",
                    json={"payment_method": "Cash", "amount": 100, "paid_date": bad})
    assert r.status_code == 400 and "paid_date" in r.get_json()["error"]
    ok = client.post(f"/api/bills/{bill['id']}/record-payment",
                     json={"payment_method": "Cash", "amount": 100, "paid_date": "2026-11-02"})
    assert ok.status_code == 200


def test_institution_bill_dates_are_validated(client):
    for bad in BAD_DATES[:4]:
        r = client.post("/api/institution-bills", json=_inst_body(bill_date=bad))
        assert r.status_code == 400 and "bill_date" in r.get_json()["error"]
    bill = client.post("/api/institution-bills", json=_inst_body()).get_json()
    assert client.put(f"/api/institution-bills/{bill['id']}", json=_inst_body(bill_date="nope")).status_code == 400
    r = client.post(f"/api/institution-bills/{bill['id']}/record-payment",
                    json={"payment_method": "Cash", "amount": 10, "paid_date": "31/11/2026"})
    assert r.status_code == 400


@pytest.mark.parametrize("base,make", [("/api/tailoring/orders", _t_body), ("/api/tailoring/suits/orders", _s_body)])
@pytest.mark.parametrize("field", ["order_date", "trial_date", "delivery_date"])
def test_tailoring_and_suit_dates_are_validated(client, base, make, field):
    r = client.post(base, json=make(**{field: "31/11/2026"}))
    assert r.status_code == 400 and "real date" in r.get_json()["error"]
    table = "tailoring_suit_orders" if "suits" in base else "tailoring_orders"
    import db.tailoring as tdb
    c = sqlite3.connect(tdb.TAILORING_DB_PATH)
    assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    c.close()


@pytest.mark.parametrize("base,make", [("/api/tailoring/orders", _t_body), ("/api/tailoring/suits/orders", _s_body)])
def test_tailoring_blank_dates_still_mean_none_and_order_date_defaults_to_today(client, base, make):
    r = client.post(base, json=make(order_date="", trial_date="", delivery_date=""))
    assert r.status_code == 201
    got = r.get_json()
    assert got["trial_date"] is None and got["delivery_date"] is None and got["order_date"]


@pytest.mark.parametrize("base,make", [("/api/tailoring/orders", _t_body), ("/api/tailoring/suits/orders", _s_body)])
def test_tailoring_update_and_payment_dates_are_validated(client, base, make):
    order = client.post(base, json=make()).get_json()
    body = make(order_number=order["order_number"], delivery_date="soon")
    assert client.put(f"{base}/{order['id']}", json=body).status_code == 400
    r = client.post(f"{base}/{order['id']}/payments", json={"amount": 10, "paid_at": "31/11/2026"})
    assert r.status_code == 400
    assert client.post(f"{base}/{order['id']}/payments", json={"amount": 10, "paid_at": "2026-11-02"}).status_code == 201


def test_date_helpers():
    from utils import clean_iso_date, valid_iso_date
    assert valid_iso_date("2026-11-15") and valid_iso_date(" 2026-11-15 ") and valid_iso_date("2000-01-01")
    for bad in ("", None, "2026-13-01", "2026-00-10", "1999-12-31", "2101-01-01", "26-11-15", "2026/11/15"):
        assert not valid_iso_date(bad)
    assert clean_iso_date("") is None and clean_iso_date(None) is None and clean_iso_date("2026-11-15") == "2026-11-15"
    with pytest.raises(ValueError, match="Trial date must be a real date"):
        clean_iso_date("tomorrow", "Trial date")


# ---------------------------------------------------------------------------
# Read-only data check
# ---------------------------------------------------------------------------
@pytest.fixture
def three_dbs(tmp_path, monkeypatch):
    import db.connection as conn_mod
    import db.measurements as mdb
    import db.tailoring as tdb
    from db import init_db
    paths = {"billing": str(tmp_path / "b.db"), "tailoring": str(tmp_path / "t.db"),
             "measurements": str(tmp_path / "m.db")}
    monkeypatch.setattr(conn_mod, "DB_PATH", paths["billing"])
    monkeypatch.setattr(tdb, "TAILORING_DB_PATH", paths["tailoring"])
    monkeypatch.setattr(mdb, "MEASUREMENTS_DB_PATH", paths["measurements"])
    init_db()
    tdb.init_tailoring_db()
    mdb.init_measurements_db()
    return paths


def _add_bill(c, number, date="2026-11-01", total=1000, paid=0, remaining=None, items=1000, round_off=0, status="active"):
    cur = c.execute(
        "INSERT INTO bills (bill_number, customer_name_snapshot, customer_mobile_snapshot, bill_date, "
        "final_total, advance_paid, remaining, round_off, payment_mode_type, status) "
        "VALUES (?, 'A', '9876543210', ?, ?, ?, ?, ?, 'Cash', ?)",
        (number, date, total, paid, total - paid if remaining is None else remaining, round_off, status))
    c.execute("INSERT INTO bill_items (bill_id, cloth_type, company_name, quantity, unit_label, mrp, final_amount) "
              "VALUES (?, 'Shirting', 'X', 1, 'm', ?, ?)", (cur.lastrowid, items, items))
    return cur.lastrowid


def test_data_check_is_clean_on_good_data(three_dbs):
    from services.data_check import format_report, run_checks
    c = sqlite3.connect(three_dbs["billing"])
    _add_bill(c, "SHN-0001/26-27")
    _add_bill(c, "SHN-0002/26-27", total=500, paid=200, items=520, round_off=20)    # round-off is accounted for
    _add_bill(c, "SHN-0003/26-27", date="2026-11-02", total=300, paid=300, items=300)
    c.commit()
    c.close()
    problems, skipped = run_checks(three_dbs["billing"], three_dbs["tailoring"], three_dbs["measurements"])
    assert problems == [] and skipped == []
    assert "No problems found" in format_report(problems, skipped)


def test_data_check_accepts_early_bills_whose_round_off_was_never_stored(three_dbs):
    """Before the round_off column existed, a total was rounded down and the rounding
    was not recorded; the app derives it for display, so it is not a data error. A total
    HIGHER than the items is, whatever the era."""
    from services.data_check import run_checks
    c = sqlite3.connect(three_dbs["billing"])
    _add_bill(c, "SHN-0008", total=5600, items=5609.8)          # rounded down, round_off = 0
    _add_bill(c, "SHN-0012", total=3800, items=3959.9)
    _add_bill(c, "SHN-0020", total=1100, items=1000)            # billed MORE than the items add up to
    _add_bill(c, "SHN-0021/26-27", total=500, paid=0, items=530, round_off=20)    # recorded round-off is 10 short
    c.commit()
    c.close()
    problems, _ = run_checks(three_dbs["billing"], three_dbs["tailoring"], three_dbs["measurements"])
    flagged = sorted(p["detail"].split(":")[0] for p in problems if p["check"] == "Total does not match items")
    assert flagged == ["SHN-0020", "SHN-0021/26-27"]


def test_data_check_finds_bad_dates_and_money(three_dbs):
    from services.data_check import format_report, run_checks
    c = sqlite3.connect(three_dbs["billing"])
    _add_bill(c, "SHN-0001/26-27", date="31/11/2026")                       # bad date
    _add_bill(c, "SHN-0002/26-27", date="")                                 # empty date
    _add_bill(c, "SHN-0003/26-27", total=1000, paid=200, remaining=500)     # balance wrong
    _add_bill(c, "SHN-0004/26-27", total=1000, items=900)                   # total != items
    _add_bill(c, "SHN-0005/26-27", total=1000, paid=200, remaining=500, status="cancelled")   # cancelled: ignored
    bid = _add_bill(c, "SHN-0006/26-27")
    c.execute("INSERT INTO bill_payments (bill_id, payment_method, amount, paid_at) VALUES (?, 'Cash', 5, 'last week')", (bid,))
    c.commit()
    c.close()

    c = sqlite3.connect(three_dbs["tailoring"])
    c.execute("INSERT INTO tailoring_orders (order_number, order_date, customer_name, delivery_date, total, advance, balance) "
              "VALUES (1, '2026-13-45', 'A', '2026-1-1', 1000, 300, 900)")
    c.execute("INSERT INTO tailoring_orders (order_number, order_date, customer_name, total, advance, balance) "
              "VALUES (2, '2026-11-01', 'B', 500, 700, 0)")
    c.commit()
    c.close()

    problems, _ = run_checks(three_dbs["billing"], three_dbs["tailoring"], three_dbs["measurements"])
    by_check = {}
    for p in problems:
        by_check.setdefault((p["database"], p["table"], p["check"]), []).append(p)
    assert len(by_check[("billing.db", "bills", "Bad bill date")]) == 2
    assert [p["detail"].startswith("SHN-0003") for p in by_check[("billing.db", "bills", "Balance does not match")]] == [True]
    assert len(by_check[("billing.db", "bills", "Total does not match items")]) == 1
    assert len(by_check[("billing.db", "bill_payments", "Bad payment date")]) == 1
    assert len(by_check[("tailoring.db", "tailoring_orders", "Bad order date")]) == 1
    assert len(by_check[("tailoring.db", "tailoring_orders", "Bad delivery date")]) == 1
    assert len(by_check[("tailoring.db", "tailoring_orders", "Paid more than owed")]) == 1
    assert ("billing.db", "bills", "Negative amount") not in by_check
    report = format_report(problems, [])
    assert "problem(s) found" in report and "31/11/2026" in report and "SHN-0003/26-27" in report


def test_data_check_never_modifies_a_database(three_dbs):
    from services.data_check import open_readonly, run_checks
    c = sqlite3.connect(three_dbs["billing"])
    _add_bill(c, "SHN-0001/26-27", date="bad")
    c.commit()
    c.close()
    before = {k: (os.path.getsize(p), os.path.getmtime(p)) for k, p in three_dbs.items()}
    run_checks(three_dbs["billing"], three_dbs["tailoring"], three_dbs["measurements"])
    assert {k: (os.path.getsize(p), os.path.getmtime(p)) for k, p in three_dbs.items()} == before
    ro = open_readonly(three_dbs["billing"])
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("DELETE FROM bills")
    ro.close()


def test_data_check_reports_missing_files_and_script_exit_codes(three_dbs, tmp_path):
    from services.data_check import format_report, run_checks
    problems, skipped = run_checks(three_dbs["billing"], str(tmp_path / "nope.db"), None)
    assert skipped == ["tailoring.db", "measurements.db"]
    assert "Not checked" in format_report(problems, skipped)

    script = os.path.join(PROJECT_ROOT, "scripts", "check_data.py")
    args = [sys.executable, script, "--billing", three_dbs["billing"],
            "--tailoring", three_dbs["tailoring"], "--measurements", three_dbs["measurements"]]
    clean = subprocess.run(args, capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert clean.returncode == 0 and "No problems found" in clean.stdout
    c = sqlite3.connect(three_dbs["billing"])
    _add_bill(c, "SHN-0009/26-27", date="31/11/2026")
    c.commit()
    c.close()
    dirty = subprocess.run(args, capture_output=True, text=True, cwd=PROJECT_ROOT)
    assert dirty.returncode == 1 and "Bad bill date" in dirty.stdout and "31/11/2026" in dirty.stdout


# ---------------------------------------------------------------------------
# 4. Security headers + logout
# ---------------------------------------------------------------------------
def _header_app(secure=False):
    from services.security import install_security_headers
    flask_app = Flask(__name__, static_folder=os.path.join(PROJECT_ROOT, "static"))
    flask_app.secret_key = "t"
    flask_app.config["SESSION_COOKIE_SECURE"] = secure
    install_security_headers(flask_app)

    @flask_app.route("/page")
    def page():
        return "hello"

    @flask_app.route("/cached")
    def cached():
        resp = flask_app.response_class("img")
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    @flask_app.route("/signin")
    def signin():
        from flask import session
        session["user_id"] = 1
        return "ok"

    return flask_app


def test_every_response_carries_the_protective_headers():
    c = _header_app().test_client()
    for url in ("/page", "/does-not-exist"):                       # errors too
        h = c.get(url).headers
        assert h["X-Content-Type-Options"] == "nosniff"
        assert h["X-Frame-Options"] == "DENY"
        assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
        assert "object-src 'none'" in h["Content-Security-Policy"]
        assert h["Permissions-Policy"].startswith("camera=(self)") and "microphone=()" in h["Permissions-Policy"]
        assert "Strict-Transport-Security" not in h              # plain-HTTP setup: no HSTS


def test_csp_does_not_forbid_inline_scripts():
    """The pages rely on inline <script>; a script-src rule would blank them."""
    csp = _header_app().test_client().get("/page").headers["Content-Security-Policy"]
    assert "script-src" not in csp and "default-src" not in csp


def test_hsts_only_when_the_site_is_set_up_for_https():
    h = _header_app(secure=True).test_client().get("/page").headers
    assert h["Strict-Transport-Security"] == "max-age=31536000"


def test_private_pages_are_not_cached_but_public_ones_and_files_are_untouched():
    c = _header_app().test_client()
    assert "no-store" not in c.get("/page").headers.get("Cache-Control", "")     # anonymous (public share pages)
    c.get("/signin")
    assert c.get("/page").headers["Cache-Control"] == "no-store"                  # signed in
    assert c.get("/cached").headers["Cache-Control"] == "public, max-age=3600"    # a route's own choice wins
    static = c.get("/static/css/base.css")
    assert static.status_code == 200 and "no-store" not in static.headers.get("Cache-Control", "")


def test_security_headers_are_installed_in_the_real_app_source():
    src = open(os.path.join(PROJECT_ROOT, "app.py"), encoding="utf-8").read()
    assert "install_security_headers(app)" in src


def test_get_logout_no_longer_signs_anyone_out(app):
    c = _login(app)
    r = c.get("/logout")
    assert r.status_code == 302
    assert c.get("/api/bills").status_code == 200                  # still signed in


def test_post_logout_ends_the_session(app):
    c = _login(app)
    r = c.post("/logout")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert c.get("/api/bills").status_code == 401
    assert c.post("/logout").status_code == 302                    # logging out twice is harmless


def test_no_template_still_links_to_logout_with_a_plain_link():
    offenders = []
    for path in glob.glob(os.path.join(PROJECT_ROOT, "templates", "*.html")):
        text = open(path, encoding="utf-8").read()
        if 'href="/logout"' in text or "href='/logout'" in text:
            offenders.append(os.path.basename(path))
    assert offenders == []
    base = open(os.path.join(PROJECT_ROOT, "templates", "base.html"), encoding="utf-8").read()
    assert base.count('method="post" action="/logout"') == 2       # sidebar + top bar


# ---------------------------------------------------------------------------
# 5. First-run passwords
# ---------------------------------------------------------------------------
def _seed(billing_path, monkeypatch, admin=None, staff=None):
    from flask_bcrypt import Bcrypt
    from db import init_db, seed_default_users
    for name, value in (("INITIAL_ADMIN_PASSWORD", admin), ("INITIAL_STAFF_PASSWORD", staff)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    init_db()
    bcrypt = Bcrypt()
    seed_default_users(bcrypt)
    c = _conn(billing_path)
    users = {r["username"]: r["password_hash"] for r in c.execute("SELECT username, password_hash FROM users")}
    c.close()
    return bcrypt, users


def test_first_run_passwords_come_from_the_environment_when_set(billing_path, monkeypatch, capsys):
    bcrypt, users = _seed(billing_path, monkeypatch, admin="Shop#Admin77", staff="Shop#Staff88")
    assert set(users) == {"admin", "staff"}
    assert bcrypt.check_password_hash(users["admin"], "Shop#Admin77")
    assert bcrypt.check_password_hash(users["staff"], "Shop#Staff88")
    out = capsys.readouterr().out
    assert "Shop#Admin77" not in out and "Shop#Staff88" not in out        # never echoed to the log


def test_first_run_passwords_are_random_and_printed_once_when_not_set(billing_path, monkeypatch, capsys, tmp_path):
    bcrypt, users = _seed(billing_path, monkeypatch)
    out = capsys.readouterr().out
    assert not bcrypt.check_password_hash(users["admin"], "Admin@1234")   # the published defaults are gone
    assert not bcrypt.check_password_hash(users["staff"], "Staff@1234")
    printed = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "password:":
            printed[parts[0]] = parts[2]
    assert set(printed) == {"admin", "staff"} and printed["admin"] != printed["staff"]
    assert bcrypt.check_password_hash(users["admin"], printed["admin"])   # what was printed really works
    assert bcrypt.check_password_hash(users["staff"], printed["staff"])
    assert len(printed["admin"]) >= 10


def test_seeding_twice_changes_nothing(billing_path, monkeypatch, capsys):
    bcrypt, first = _seed(billing_path, monkeypatch, admin="One#Admin11", staff="One#Staff11")
    capsys.readouterr()
    from db import seed_default_users
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "Different#99")
    seed_default_users(bcrypt)
    c = _conn(billing_path)
    again = {r["username"]: r["password_hash"] for r in c.execute("SELECT username, password_hash FROM users")}
    c.close()
    assert again == first and capsys.readouterr().out == ""


def test_no_fixed_default_password_is_left_in_the_code_or_readme():
    seeds = open(os.path.join(PROJECT_ROOT, "db", "seeds.py"), encoding="utf-8").read()
    assert "Admin@1234" not in seeds and "Staff@1234" not in seeds
    readme = open(os.path.join(PROJECT_ROOT, "README.md"), encoding="utf-8").read()
    assert "| Admin | `admin`  | `Admin@1234` |" not in readme       # the credentials table is gone
    assert "INITIAL_ADMIN_PASSWORD" in readme


def test_labels_docx_is_no_longer_tracked_by_git():
    tracked = subprocess.run(["git", "ls-files", "Labels.docx"], capture_output=True, text=True,
                             cwd=PROJECT_ROOT).stdout.strip()
    assert tracked == ""
    ignore = open(os.path.join(PROJECT_ROOT, ".gitignore"), encoding="utf-8").read()
    assert "Labels.docx" in ignore
