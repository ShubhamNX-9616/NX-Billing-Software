"""Mirror Try-On picture saving + the Try-On Gallery.

Runs against a temp DB and a temp upload folder, with R2 switched off —
billing.db and uploads/ are never touched.
"""
import base64
import io
import os
import sys

import pytest
from flask import Flask
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

SECRET = "x" * 32
HDR = {"X-Tryon-Secret": SECRET}


def _jpeg_b64(color=(180, 30, 40), size=(60, 80)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    import db.connection as conn_mod
    import routes.tryon as tryon_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", str(tmp_path / "billing_test.db"))
    monkeypatch.setattr(tryon_mod, "UPLOAD_DIR", str(tmp_path / "uploads" / "tryon"))
    monkeypatch.setattr(tryon_mod.r2_storage, "is_configured", lambda: False)
    monkeypatch.setenv("TRYON_SHARED_SECRET", SECRET)

    from db import get_db, close_db, init_db
    from routes.tryon import tryon_api_bp, tryon_pages_bp

    init_db()
    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"))
    app.secret_key = "test"
    app.register_blueprint(tryon_api_bp, url_prefix="/api")
    app.register_blueprint(tryon_pages_bp)
    app.teardown_appcontext(close_db)

    # Stand-ins for what the real app.py / auth blueprint provide to base.html
    from flask import Blueprint, session

    stub = Blueprint("auth_routes", __name__)
    stub.add_url_rule("/login", "login", lambda: "login")
    stub.add_url_rule("/unauthorized", "unauthorized", lambda: "no")
    stub.add_url_rule("/logout", "logout", lambda: "bye")
    app.register_blueprint(stub)

    @app.context_processor
    def inject():
        role = session.get("role")
        return {
            "share_base_url": "", "tryon_url": "https://example.test", "server_today": "2026-01-01",
            "sv": "1",
            "current_user": {"id": session.get("user_id"), "username": session.get("username"),
                             "role": role, "is_admin": role == "admin",
                             "is_staff": role == "staff", "is_tailor": role == "tailor"},
        }

    with app.app_context():
        d = get_db()
        d.execute("INSERT OR IGNORE INTO cloth_types (type_name, normalized_name) VALUES ('Suiting','suiting')")
        d.execute(
            """INSERT INTO inventory_items (cloth_type, company_name, quality_number, item_name,
                   current_stock, mrp, item_code)
               VALUES ('Suiting', 'Raymonds', 'Q1', 'Navy Twill', 5, 1000, 'SUT-001')"""
        )
        d.commit()
    return app, tmp_path


def _client(app, role=None):
    c = app.test_client()
    if role:
        with c.session_transaction() as s:
            s.update(user_id=1, role=role, username="t")
    return c


def _save(c, **over):
    body = {"item_code": "SUT-001", "garment": "suit", "image": _jpeg_b64()}
    body.update(over)
    return c.post("/api/tryon/photos", json=body, headers=HDR)


# ---- secret ---------------------------------------------------------------
def test_wrong_or_missing_secret_rejected(env):
    app, _ = env
    c = _client(app)
    assert c.get("/api/tryon/inventory/SUT-001").status_code == 401
    assert c.get("/api/tryon/inventory/SUT-001", headers={"X-Tryon-Secret": "nope"}).status_code == 401
    assert c.post("/api/tryon/photos", json={}).status_code == 401


def test_saving_off_when_secret_unset_or_weak(env, monkeypatch):
    app, _ = env
    monkeypatch.setenv("TRYON_SHARED_SECRET", "short")
    assert _client(app).get("/api/tryon/inventory/SUT-001", headers={"X-Tryon-Secret": "short"}).status_code == 503
    monkeypatch.delenv("TRYON_SHARED_SECRET")
    assert _client(app).get("/api/tryon/inventory/SUT-001", headers={"X-Tryon-Secret": ""}).status_code == 503


# ---- lookup ---------------------------------------------------------------
def test_lookup_is_forgiving_and_returns_name(env):
    app, _ = env
    c = _client(app)
    for typed in ("SUT-001", "sut001", "sut1"):
        r = c.get(f"/api/tryon/inventory/{typed}", headers=HDR)
        assert r.status_code == 200
        assert r.get_json()["item_code"] == "SUT-001"
        assert r.get_json()["item_name"] == "Navy Twill"
    assert c.get("/api/tryon/inventory/ZZZ-999", headers=HDR).status_code == 404


# ---- saving ---------------------------------------------------------------
def test_save_writes_file_named_by_code_in_garment_folder(env):
    app, tmp = env
    r = _save(_client(app), item_code="sut001")        # typed loosely
    assert r.status_code == 201
    assert r.get_json()["path"] == "tryon/suit/SUT-001.jpg"
    assert (tmp / "uploads" / "tryon" / "suit" / "SUT-001.jpg").is_file()


def test_sherwani_is_an_accepted_garment(env):
    app, tmp = env
    assert _save(_client(app), garment="sherwani").status_code == 201
    assert (tmp / "uploads" / "tryon" / "sherwani" / "SUT-001.jpg").is_file()


def test_same_code_other_garment_goes_to_its_own_folder(env):
    app, tmp = env
    c = _client(app)
    assert _save(c, garment="suit").status_code == 201
    assert _save(c, garment="kurta").status_code == 201
    assert (tmp / "uploads" / "tryon" / "suit" / "SUT-001.jpg").is_file()
    assert (tmp / "uploads" / "tryon" / "kurta" / "SUT-001.jpg").is_file()


def test_saving_again_replaces_and_keeps_one_row(env):
    app, tmp = env
    c = _client(app)
    _save(c, image=_jpeg_b64(color=(255, 0, 0)))
    _save(c, image=_jpeg_b64(color=(0, 0, 255)))
    from db import get_db
    with app.app_context():
        n = get_db().execute("SELECT COUNT(*) FROM tryon_photos").fetchone()[0]
    assert n == 1
    px = Image.open(tmp / "uploads" / "tryon" / "suit" / "SUT-001.jpg").convert("RGB").getpixel((5, 5))
    assert px[2] > 200 and px[0] < 60           # now the blue one


@pytest.mark.parametrize("over, status", [
    ({"garment": "tuxedo"}, 400),
    ({"garment": "../../etc"}, 400),
    ({"item_code": "NOPE-1"}, 404),
    ({"image": ""}, 400),
    ({"image": "not base64!!"}, 400),
    ({"image": base64.b64encode(b"plain text").decode()}, 400),
])
def test_bad_input_rejected(env, over, status):
    app, tmp = env
    assert _save(_client(app), **over).status_code == status
    assert not (tmp / "uploads").exists()        # nothing written


# ---- gallery --------------------------------------------------------------
def test_gallery_needs_login(env):
    app, _ = env
    _save(_client(app))
    c = _client(app)
    assert c.get("/api/tryon-gallery").status_code == 401
    assert c.get("/tryon-gallery/image/suit/SUT-001").status_code == 401
    assert c.get("/tryon-gallery").status_code == 302       # redirected to login


def test_gallery_lists_filters_and_serves_image(env):
    app, _ = env
    _save(_client(app))
    _save(_client(app), garment="kurta")
    c = _client(app, "staff")

    rows = c.get("/api/tryon-gallery").get_json()
    assert {r["garment"] for r in rows} == {"suit", "kurta"}
    assert rows[0]["item_name"] == "Navy Twill"

    assert [r["garment"] for r in c.get("/api/tryon-gallery?garment=kurta").get_json()] == ["kurta"]
    assert len(c.get("/api/tryon-gallery?q=navy").get_json()) == 2
    assert c.get("/api/tryon-gallery?q=zzz").get_json() == []

    img = c.get(rows[0]["url"])
    assert img.status_code == 200 and img.mimetype == "image/jpeg"
    assert Image.open(io.BytesIO(img.data)).format == "JPEG"
    assert c.get("/tryon-gallery/image/suit/NOPE").status_code == 404
    assert c.get("/tryon-gallery").status_code == 200


def test_only_admin_can_delete(env):
    app, tmp = env
    _save(_client(app))
    pid = _client(app, "staff").get("/api/tryon-gallery").get_json()[0]["id"]
    assert _client(app, "staff").delete(f"/api/tryon-gallery/{pid}").status_code == 403
    assert _client(app, "admin").delete(f"/api/tryon-gallery/{pid}").status_code == 200
    assert not (tmp / "uploads" / "tryon" / "suit" / "SUT-001.jpg").exists()
    assert _client(app, "admin").get("/api/tryon-gallery").get_json() == []
