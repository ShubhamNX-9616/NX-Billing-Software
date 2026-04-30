from flask import Blueprint, jsonify, request
from db import get_db
from auth import api_login_required, api_admin_required

suppliers_bp = Blueprint("suppliers", __name__)


@suppliers_bp.route("/suppliers", methods=["GET"])
@api_login_required
def get_suppliers():
    db = get_db()
    rows = db.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])


@suppliers_bp.route("/suppliers", methods=["POST"])
@api_admin_required
def add_supplier():
    try:
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        normalized = name.lower()
        db = get_db()
        existing = db.execute(
            "SELECT id FROM suppliers WHERE normalized_name = ?", (normalized,)
        ).fetchone()
        if existing:
            return jsonify({"error": "Supplier already exists"}), 409
        cur = db.execute(
            "INSERT INTO suppliers (name, normalized_name) VALUES (?, ?)",
            (name, normalized),
        )
        db.commit()
        row = db.execute("SELECT * FROM suppliers WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
