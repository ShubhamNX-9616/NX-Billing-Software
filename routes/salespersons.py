from flask import Blueprint, jsonify, request

from db import get_db
from auth import login_required, admin_required, staff_or_admin_required, api_login_required, api_admin_required

salespersons_bp = Blueprint("salespersons", __name__)


@salespersons_bp.route("/salespersons", methods=["GET"])
@api_login_required
def get_salespersons():
    try:
        db = get_db()
        rows = db.execute(
            """
            SELECT id, name
            FROM salespersons
            ORDER BY is_default DESC, name ASC
            """
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@salespersons_bp.route("/salespersons", methods=["POST"])
@api_admin_required
def add_salesperson():
    try:
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400

        normalized = name.lower()
        db = get_db()
        existing = db.execute(
            "SELECT id FROM salespersons WHERE normalized_name = ?",
            (normalized,),
        ).fetchone()
        if existing:
            return jsonify({"error": "Sales person already exists"}), 409

        cursor = db.execute(
            """
            INSERT INTO salespersons (name, normalized_name, is_default)
            VALUES (?, ?, 0)
            """,
            (name, normalized),
        )
        db.commit()
        row = db.execute(
            "SELECT id, name FROM salespersons WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
