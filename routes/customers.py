import re
from flask import Blueprint, jsonify, request
from database import get_db
from auth import login_required, admin_required, staff_or_admin_required, api_login_required, api_admin_required

customers_bp = Blueprint("customers", __name__)


def normalize_mobile(raw):
    """Strip spaces, remove leading +91 or 0, return last 10 digits."""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return digits


@customers_bp.route("/customers", methods=["GET"])
@api_admin_required
def get_customers():
    try:
        search = request.args.get("search", "").strip()
        db = get_db()
        if search:
            like = f"%{search}%"
            rows = db.execute(
                """
                SELECT * FROM customers
                WHERE name LIKE ? OR mobile LIKE ?
                ORDER BY name
                """,
                (like, like),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM customers ORDER BY name"
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/search", methods=["GET"])
@api_login_required
def search_customer_by_mobile():
    try:
        raw = request.args.get("mobile", "").strip()
        if not raw:
            return jsonify({"error": "mobile param required"}), 400
        norm = normalize_mobile(raw)
        db = get_db()
        row = db.execute(
            "SELECT * FROM customers WHERE normalized_mobile = ?", (norm,)
        ).fetchone()
        if row:
            return jsonify({"found": True, "customer": dict(row)})
        return jsonify({"found": False})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<int:customer_id>", methods=["GET"])
@api_admin_required
def get_customer(customer_id):
    try:
        db = get_db()
        row = db.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Customer not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/<int:customer_id>/bills", methods=["GET"])
@api_admin_required
def get_customer_bills(customer_id):
    try:
        db = get_db()
        customer = db.execute(
            "SELECT id FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if not customer:
            return jsonify({"error": "Customer not found"}), 404
        rows = db.execute(
            """
            SELECT id, bill_number, bill_date, final_total,
                   payment_mode_type, created_at
            FROM bills
            WHERE customer_id = ?
            ORDER BY created_at DESC
            """,
            (customer_id,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
