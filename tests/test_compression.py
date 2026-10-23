"""gzip applies to big JSON/HTML responses only, and only when asked for."""
import gzip
import json
import os
import sys

import pytest
from flask import Flask, jsonify, send_file

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.compression import init_compression

BIG = {"rows": [{"name": "Bawaskar", "mobile": "9876543210"}] * 200}


@pytest.fixture
def client(tmp_path):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"\xff\xd8" + b"x" * 5000)

    app = Flask(__name__)
    init_compression(app)

    @app.route("/big")
    def big():
        return jsonify(BIG)

    @app.route("/small")
    def small():
        return jsonify({"ok": True})

    @app.route("/page")
    def page():
        return "<html>" + "<p>row</p>" * 500 + "</html>"

    @app.route("/photo")
    def photo_file():
        return send_file(str(photo), mimetype="image/jpeg")

    @app.route("/missing")
    def missing():
        return jsonify(BIG), 404

    return app.test_client()


def test_big_json_is_compressed_and_round_trips(client):
    res = client.get("/big", headers={"Accept-Encoding": "gzip, deflate"})
    assert res.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in res.headers["Vary"]
    assert int(res.headers["Content-Length"]) == len(res.data)
    assert json.loads(gzip.decompress(res.data)) == BIG
    assert len(res.data) < len(json.dumps(BIG)) / 3


def test_html_is_compressed(client):
    res = client.get("/page", headers={"Accept-Encoding": "gzip"})
    assert res.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(res.data).startswith(b"<html>")


def test_not_compressed_when_client_does_not_accept_gzip(client):
    res = client.get("/big")
    assert "Content-Encoding" not in res.headers
    assert res.get_json() == BIG


def test_small_responses_left_alone(client):
    res = client.get("/small", headers={"Accept-Encoding": "gzip"})
    assert "Content-Encoding" not in res.headers


def test_files_and_errors_left_alone(client):
    hdr = {"Accept-Encoding": "gzip"}
    assert "Content-Encoding" not in client.get("/photo", headers=hdr).headers
    assert "Content-Encoding" not in client.get("/missing", headers=hdr).headers
