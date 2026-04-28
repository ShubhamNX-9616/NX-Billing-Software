from flask import Blueprint, jsonify, request
from db import get_db
from auth import login_required, admin_required, staff_or_admin_required, api_login_required, api_admin_required

companies_bp = Blueprint("companies", __name__)


@companies_bp.route("/companies", methods=["GET"])
@api_login_required
def get_companies():
    try:
        cloth_type = request.args.get("clothType", "").strip()
        if not cloth_type:
            return jsonify({"error": "clothType param is required"}), 400
        db = get_db()
        ct = db.execute(
            "SELECT id FROM cloth_types WHERE type_name = ?", (cloth_type,)
        ).fetchone()
        if not ct:
            return jsonify({"error": f"Invalid cloth type: {cloth_type}"}), 400
        rows = db.execute(
            "SELECT * FROM companies WHERE cloth_type = ? ORDER BY company_name",
            (cloth_type,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@companies_bp.route("/companies", methods=["POST"])
@api_login_required
def add_company():
    try:
        body = request.get_json(force=True, silent=True) or {}
        cloth_type = (body.get("cloth_type") or "").strip()
        company_name = (body.get("company_name") or "").strip()

        if not company_name:
            return jsonify({"error": "company_name cannot be empty"}), 400

        db = get_db()
        ct = db.execute(
            "SELECT id FROM cloth_types WHERE type_name = ?", (cloth_type,)
        ).fetchone()
        if not ct:
            return jsonify({"error": f"Invalid cloth type: {cloth_type}"}), 400

        normalized = company_name.lower()
        existing = db.execute(
            """
            SELECT id FROM companies
            WHERE cloth_type = ? AND normalized_company_name = ?
            """,
            (cloth_type, normalized),
        ).fetchone()
        if existing:
            return jsonify({"error": "Company already exists under this cloth type"}), 409

        cursor = db.execute(
            """
            INSERT INTO companies (cloth_type, company_name, normalized_company_name, is_default)
            VALUES (?, ?, ?, 0)
            """,
            (cloth_type, company_name, normalized),
        )
        db.commit()
        new_row = db.execute(
            "SELECT * FROM companies WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return jsonify(dict(new_row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
