"""Phase 1 tests for the Measurements trial skeleton.

Uses a minimal Flask app and a temp measurements DB, so billing.db,
tailoring.db and the real measurements.db are never touched.
"""
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import db.measurements as mdb
    import routes.measurements as mr

    monkeypatch.setattr(mdb, "MEASUREMENTS_DB_PATH", str(tmp_path / "measurements_test.db"))
    monkeypatch.setattr(mr, "UPLOAD_DIR", str(tmp_path / "uploads"))
    mdb.init_measurements_db()

    app = Flask(
        __name__,
        template_folder=os.path.join(PROJECT_ROOT, "templates"),
        static_folder=os.path.join(PROJECT_ROOT, "static"),
    )
    app.secret_key = "test"
    app.register_blueprint(mr.measurements_api_bp, url_prefix="/api")
    app.register_blueprint(mr.measurements_pages_bp)
    app.teardown_appcontext(mdb.close_measurements_db)

    @app.context_processor
    def inject_globals():
        from flask import session
        return {
            "measurements_enabled": True,
            "tryon_url": "",
            "sv": "t",
            "server_today": "2026-01-01",
            "share_base_url": "",
            "current_user": {
                "id": session.get("user_id"),
                "username": session.get("username"),
                "role": session.get("role"),
                "is_admin": session.get("role") == "admin",
                "is_staff": session.get("role") == "staff",
                "is_tailor": session.get("role") == "tailor",
            },
        }

    @app.template_filter("format_date")
    def format_date_filter(date_str):
        return date_str or ""

    # base.html links to these endpoints; stubs keep url_for() happy
    @app.route("/login", endpoint="auth_routes.login")
    def _login():
        return "login"

    @app.route("/unauthorized", endpoint="auth_routes.unauthorized")
    def _unauthorized():
        return "unauthorized", 403

    with app.test_client() as c:
        yield c


def _login_as(client, role):
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "tester"
        sess["role"] = role


def test_schema_created_in_separate_db(client):
    import sqlite3
    import db.measurements as mdb

    conn = sqlite3.connect(mdb.MEASUREMENTS_DB_PATH)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"m_customers", "m_measurements"} <= tables
    # none of the existing systems' tables leak into this database
    assert not any(t.startswith("tailoring_") or t in ("bills", "customers") for t in tables)


def test_page_requires_login(client):
    resp = client.get("/measurements")
    assert resp.status_code == 302


def test_page_renders_for_admin_and_staff(client):
    for role in ("admin", "staff"):
        _login_as(client, role)
        resp = client.get("/measurements")
        assert resp.status_code == 200
        assert b"Measurements" in resp.data


def test_page_blocked_for_tailor_role(client):
    _login_as(client, "tailor")
    resp = client.get("/measurements")
    assert resp.status_code == 302


def test_status_endpoint_empty(client):
    _login_as(client, "admin")
    resp = client.get("/api/measurements/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"customers": 0, "measurements": 0}


def test_status_endpoint_requires_login(client):
    resp = client.get("/api/measurements/status")
    assert resp.status_code in (401, 403)
