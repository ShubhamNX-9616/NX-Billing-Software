from flask import Blueprint, jsonify, request
from db import get_db
from auth import api_admin_required

invoices_bp = Blueprint("invoices", __name__)


@invoices_bp.route("/invoices", methods=["GET"])
@api_admin_required
def list_invoices():
    try:
        db = get_db()
        rows = db.execute("""
            SELECT i.id, i.invoice_number, i.invoice_date, i.notes, i.created_at,
                   i.supplier_id, s.name AS supplier_name,
                   COUNT(ii.id) AS item_count
            FROM invoices i
            LEFT JOIN suppliers s ON i.supplier_id = s.id
            LEFT JOIN inventory_items ii ON ii.invoice_id = i.id
            GROUP BY i.id
            ORDER BY i.invoice_date DESC, i.created_at DESC
        """).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@invoices_bp.route("/invoices", methods=["POST"])
@api_admin_required
def create_invoice():
    try:
        body           = request.get_json(force=True, silent=True) or {}
        invoice_number = (body.get("invoice_number") or "").strip()
        invoice_date   = (body.get("invoice_date")   or "").strip()
        supplier_id_raw = body.get("supplier_id")
        supplier_id    = int(supplier_id_raw) if supplier_id_raw else None
        notes          = (body.get("notes") or "").strip() or None

        if not invoice_number:
            return jsonify({"error": "invoice_number is required"}), 400
        if not invoice_date:
            return jsonify({"error": "invoice_date is required"}), 400

        db = get_db()
        cur = db.execute(
            "INSERT INTO invoices (invoice_number, invoice_date, supplier_id, notes) VALUES (?, ?, ?, ?)",
            (invoice_number, invoice_date, supplier_id, notes),
        )
        db.commit()
        row = db.execute("""
            SELECT i.*, s.name AS supplier_name
            FROM invoices i LEFT JOIN suppliers s ON i.supplier_id = s.id
            WHERE i.id = ?
        """, (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
