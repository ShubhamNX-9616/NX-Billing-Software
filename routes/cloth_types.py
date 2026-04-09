from flask import Blueprint, jsonify, request
from database import get_db

cloth_types_bp = Blueprint("cloth_types", __name__)


@cloth_types_bp.route("/cloth-types", methods=["GET"])
def get_cloth_types():
    try:
        db = get_db()
        rows = db.execute(
            """
            SELECT id, type_name, has_company
            FROM cloth_types
            ORDER BY is_default DESC, type_name ASC
            """
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@cloth_types_bp.route("/cloth-types", methods=["POST"])
def add_cloth_type():
    try:
        body = request.get_json(force=True, silent=True) or {}
        type_name = (body.get("type_name") or "").strip()

        if not type_name:
            return jsonify({"error": "type_name cannot be empty"}), 400

        normalized = type_name.lower()
        db = get_db()

        existing = db.execute(
            "SELECT id FROM cloth_types WHERE normalized_name = ?", (normalized,)
        ).fetchone()
        if existing:
            return jsonify({"error": "Cloth type already exists"}), 409

        cursor = db.execute(
            """
            INSERT INTO cloth_types (type_name, normalized_name, is_default, has_company)
            VALUES (?, ?, 0, 1)
            """,
            (type_name, normalized),
        )
        db.commit()
        new_row = db.execute(
            "SELECT * FROM cloth_types WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return jsonify(dict(new_row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
