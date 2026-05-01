import io
import json
import qrcode
from flask import Blueprint, jsonify, request, send_file, session
from db import get_db
from auth import api_login_required, api_admin_required
from utils import r2, cloth_type_prefix as _item_prefix

inventory_bp = Blueprint("inventory", __name__)

def _next_item_code(db, cloth_type):
    prefix = _item_prefix(cloth_type)
    row = db.execute(
        "SELECT item_code FROM inventory_items WHERE item_code LIKE ? ORDER BY item_code DESC LIMIT 1",
        (f"{prefix}-%",)
    ).fetchone()
    if row:
        try:
            last_num = int(row['item_code'].split('-')[1])
        except (IndexError, ValueError):
            last_num = 0
        next_num = last_num + 1
    else:
        next_num = 1
    return f"{prefix}-{next_num:03d}"


# ---------------------------------------------------------------------------
# GET /api/inventory
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory", methods=["GET"])
@api_admin_required
def list_inventory():
    db = get_db()
    rows = db.execute(
        """
        SELECT i.id, i.cloth_type, i.company_name, i.quality_number, i.unit_label,
               i.current_stock, i.min_stock_alert, i.mrp, i.notes, i.item_code,
               i.supplier_id, s.name AS supplier_name, i.created_at, i.updated_at
        FROM inventory_items i
        LEFT JOIN suppliers s ON i.supplier_id = s.id
        ORDER BY i.cloth_type, i.company_name, i.quality_number
        """
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /api/inventory/<id>
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/<int:item_id>", methods=["GET"])
@api_login_required
def get_inventory_item(item_id):
    db = get_db()
    item = db.execute(
        "SELECT * FROM inventory_items WHERE id = ?", (item_id,)
    ).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404
    return jsonify(dict(item))


# ---------------------------------------------------------------------------
# POST /api/inventory
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory", methods=["POST"])
@api_admin_required
def create_inventory_item():
    try:
        body = request.get_json(force=True, silent=True) or {}

        cloth_type      = (body.get("cloth_type")     or "").strip()
        company_name    = (body.get("company_name")    or "").strip()
        quality_number  = (body.get("quality_number")  or "").strip()
        unit_label      = (body.get("unit_label")      or "m").strip()
        mrp             = float(body.get("mrp")        or 0)
        opening_stock   = float(body.get("opening_stock") or 0)
        min_stock_alert = float(body.get("min_stock_alert") or 5)
        notes           = (body.get("notes") or "").strip() or None
        supplier_id_raw = body.get("supplier_id")
        supplier_id     = int(supplier_id_raw) if supplier_id_raw else None

        if not cloth_type:
            return jsonify({"error": "cloth_type is required"}), 400
        if not company_name:
            return jsonify({"error": "company_name is required"}), 400
        if mrp < 0:
            return jsonify({"error": "mrp cannot be negative"}), 400
        if opening_stock < 0:
            return jsonify({"error": "opening_stock cannot be negative"}), 400

        db = get_db()
        try:
            item_code = _next_item_code(db, cloth_type)
            cur = db.execute(
                """INSERT INTO inventory_items
                   (cloth_type, company_name, quality_number, unit_label,
                    current_stock, min_stock_alert, mrp, notes, item_code, supplier_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cloth_type, company_name, quality_number, unit_label,
                 opening_stock, min_stock_alert, mrp, notes, item_code, supplier_id),
            )
            item_id = cur.lastrowid
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                return jsonify({"error": "An inventory item with these details already exists"}), 409
            raise

        if opening_stock > 0:
            db.execute(
                """INSERT INTO inventory_transactions
                   (item_id, txn_type, quantity, reference_type, notes, created_by)
                   VALUES (?, 'opening', ?, 'manual', 'Opening stock', ?)""",
                (item_id, opening_stock, session.get("username")),
            )

        db.commit()
        item = db.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        return jsonify(dict(item)), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/inventory/<id>
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/<int:item_id>", methods=["PUT"])
@api_admin_required
def update_inventory_item(item_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_db()

        item = db.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return jsonify({"error": "Item not found"}), 404

        mrp             = float(body.get("mrp",             item["mrp"]))
        min_stock_alert = float(body.get("min_stock_alert", item["min_stock_alert"]))
        notes           = (body.get("notes") or "").strip() or None

        db.execute(
            """UPDATE inventory_items
               SET mrp = ?, min_stock_alert = ?, notes = ?,
                   updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (mrp, min_stock_alert, notes, item_id),
        )
        db.commit()
        updated = db.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        return jsonify(dict(updated))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/inventory/<id>
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/<int:item_id>", methods=["DELETE"])
@api_admin_required
def delete_inventory_item(item_id):
    try:
        db = get_db()
        item = db.execute("SELECT id FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return jsonify({"error": "Item not found"}), 404

        in_bills = db.execute(
            "SELECT COUNT(*) as cnt FROM bill_items WHERE inventory_item_id = ?", (item_id,)
        ).fetchone()["cnt"]
        if in_bills > 0:
            return jsonify({"error": "Cannot delete: this item is referenced in bills"}), 409

        db.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        db.commit()
        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /api/inventory/<id>/restock
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/<int:item_id>/restock", methods=["POST"])
@api_admin_required
def restock_item(item_id):
    try:
        body     = request.get_json(force=True, silent=True) or {}
        quantity = float(body.get("quantity") or 0)
        txn_type = body.get("txn_type", "purchase")
        notes    = (body.get("notes") or "").strip() or None

        if quantity <= 0:
            return jsonify({"error": "quantity must be > 0"}), 400
        if txn_type not in ("purchase", "opening"):
            return jsonify({"error": "txn_type must be 'purchase' or 'opening'"}), 400

        db = get_db()
        item = db.execute("SELECT current_stock FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return jsonify({"error": "Item not found"}), 404

        new_stock = r2(item["current_stock"] + quantity)
        db.execute(
            "UPDATE inventory_items SET current_stock = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (new_stock, item_id),
        )
        db.execute(
            """INSERT INTO inventory_transactions
               (item_id, txn_type, quantity, reference_type, notes, created_by)
               VALUES (?, ?, ?, 'manual', ?, ?)""",
            (item_id, txn_type, quantity, notes, session.get("username")),
        )
        db.commit()
        return jsonify({"success": True, "new_stock": new_stock})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /api/inventory/<id>/adjust
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/<int:item_id>/adjust", methods=["POST"])
@api_admin_required
def adjust_item(item_id):
    try:
        body     = request.get_json(force=True, silent=True) or {}
        quantity = float(body.get("quantity") or 0)
        notes    = (body.get("notes") or "").strip() or None

        if quantity == 0:
            return jsonify({"error": "quantity cannot be zero"}), 400

        db = get_db()
        item = db.execute("SELECT current_stock FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return jsonify({"error": "Item not found"}), 404

        new_stock = r2(item["current_stock"] + quantity)
        db.execute(
            "UPDATE inventory_items SET current_stock = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (new_stock, item_id),
        )
        db.execute(
            """INSERT INTO inventory_transactions
               (item_id, txn_type, quantity, reference_type, notes, created_by)
               VALUES (?, 'adjustment', ?, 'manual', ?, ?)""",
            (item_id, quantity, notes, session.get("username")),
        )
        db.commit()
        return jsonify({"success": True, "new_stock": new_stock})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/inventory/<id>/transactions
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/<int:item_id>/transactions", methods=["GET"])
@api_admin_required
def get_item_transactions(item_id):
    db = get_db()
    rows = db.execute(
        """SELECT * FROM inventory_transactions WHERE item_id = ?
           ORDER BY created_at DESC""",
        (item_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /api/inventory/low-stock
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/low-stock", methods=["GET"])
@api_admin_required
def low_stock():
    db = get_db()
    rows = db.execute(
        """SELECT * FROM inventory_items
           WHERE current_stock <= min_stock_alert
           ORDER BY current_stock ASC"""
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# GET /api/inventory/<id>/qr  — returns PNG of inventory QR
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/by-code/<item_code>", methods=["GET"])
@api_login_required
def get_inventory_item_by_code(item_code):
    db = get_db()
    item = db.execute(
        "SELECT * FROM inventory_items WHERE item_code = ?", (item_code,)
    ).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404
    return jsonify(dict(item))


@inventory_bp.route("/inventory/<int:item_id>/qr", methods=["GET"])
@api_admin_required
def get_inventory_qr(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404

    qr_content = f"inv:{item['item_code']}"
    img = qrcode.make(qr_content)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name=f"inv-qr-{item['item_code']}.png")


# ---------------------------------------------------------------------------
# POST /api/inventory/current-stock-qr  — returns PNG for a non-tracked item
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/current-stock-qr", methods=["POST"])
@api_admin_required
def current_stock_qr():
    try:
        body = request.get_json(force=True, silent=True) or {}
        cloth_type    = (body.get("cloth_type")    or "").strip()
        company_name  = (body.get("company_name")  or "").strip()
        quality_number = (body.get("quality_number") or "").strip()
        mrp           = float(body.get("mrp") or 0)
        unit_label    = (body.get("unit_label") or "m").strip()

        if not cloth_type:
            return jsonify({"error": "cloth_type is required"}), 400

        data = {
            "cloth_type":    cloth_type,
            "company_name":  company_name,
            "quality_number": quality_number,
            "mrp":           mrp,
            "unit_label":    unit_label,
        }
        qr_content = "cs:" + json.dumps(data, separators=(",", ":"))
        img = qrcode.make(qr_content)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png",
                         download_name="current-stock-qr.png")

    except Exception as e:
        return jsonify({"error": str(e)}), 500
