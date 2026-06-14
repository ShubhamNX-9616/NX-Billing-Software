from flask import Blueprint, jsonify, request
from db import get_db
from auth import api_login_required, api_admin_required
from utils import normalize_mobile

customers_bp = Blueprint("customers", __name__)


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


@customers_bp.route("/customers/suggest", methods=["GET"])
@api_login_required
def suggest_customers():
    try:
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify([])
        db = get_db()
        like = f"%{q}%"
        rows = db.execute(
            """
            SELECT name, mobile FROM customers
            WHERE name LIKE ?
            ORDER BY name
            LIMIT 8
            """,
            (like,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@customers_bp.route("/customers/summary", methods=["GET"])
@api_login_required
def customer_summary():
    try:
        raw = request.args.get("mobile", "").strip()
        if not raw:
            return jsonify({"error": "mobile required"}), 400
        norm = normalize_mobile(raw)
        db   = get_db()

        stats = db.execute("""
            SELECT COUNT(b.id)                        AS total_bills,
                   COALESCE(SUM(b.final_total), 0)    AS total_spent
            FROM   customers c
            JOIN   bills b ON b.customer_id = c.id
            WHERE  c.normalized_mobile = ?
              AND  b.status != 'cancelled'
        """, (norm,)).fetchone()

        last = db.execute("""
            SELECT b.bill_number, b.bill_date, b.final_total
            FROM   bills b
            JOIN   customers c ON c.id = b.customer_id
            WHERE  c.normalized_mobile = ?
              AND  b.status != 'cancelled'
            ORDER  BY b.bill_date DESC, b.id DESC
            LIMIT  1
        """, (norm,)).fetchone()

        return jsonify({
            "total_bills":       int(stats["total_bills"]  or 0),
            "total_spent":       round(float(stats["total_spent"] or 0), 2),
            "last_bill_amount":  round(float(last["final_total"]), 2) if last else None,
            "last_bill_date":    last["bill_date"]   if last else None,
            "last_bill_number":  last["bill_number"] if last else None,
        })
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
