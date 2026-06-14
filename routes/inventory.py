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
               i.current_stock, i.min_stock_alert, i.mrp, i.cost_price, i.notes, i.item_code,
               i.supplier_id, s.name AS supplier_name, i.created_at, i.updated_at,
               i.item_name, i.shade_number, i.invoice_id,
               inv.invoice_number, inv.invoice_date
        FROM inventory_items i
        LEFT JOIN invoices inv ON i.invoice_id = inv.id
        LEFT JOIN suppliers s ON s.id = COALESCE(i.supplier_id, inv.supplier_id)
        ORDER BY COALESCE(inv.invoice_date, date(i.created_at)) DESC,
                 i.invoice_id DESC,
                 i.id ASC
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
        cost_price      = float(body.get("cost_price") or 0)
        opening_stock   = float(body.get("opening_stock") or 0)
        min_stock_alert = float(body.get("min_stock_alert") or 5)
        notes           = (body.get("notes") or "").strip() or None
        supplier_id_raw = body.get("supplier_id")
        supplier_id     = int(supplier_id_raw) if supplier_id_raw else None
        item_name       = (body.get("item_name")    or "").strip() or None
        shade_number    = (body.get("shade_number") or "").strip() or None
        invoice_id_raw  = body.get("invoice_id")
        invoice_id      = int(invoice_id_raw) if invoice_id_raw else None

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
                    current_stock, min_stock_alert, mrp, cost_price, notes, item_code,
                    supplier_id, item_name, shade_number, invoice_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cloth_type, company_name, quality_number, unit_label,
                 opening_stock, min_stock_alert, mrp, cost_price, notes, item_code,
                 supplier_id, item_name, shade_number, invoice_id),
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
        cost_price      = float(body.get("cost_price", item["cost_price"] or 0))
        min_stock_alert = float(body.get("min_stock_alert", item["min_stock_alert"]))
        notes           = (body.get("notes") or "").strip() or None
        item_name       = (body.get("item_name")    or "").strip() or None
        shade_number    = (body.get("shade_number") or "").strip() or None

        db.execute(
            """UPDATE inventory_items
               SET mrp = ?, cost_price = ?, min_stock_alert = ?, notes = ?,
                   item_name = ?, shade_number = ?,
                   updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (mrp, cost_price, min_stock_alert, notes, item_name, shade_number, item_id),
        )
        db.commit()
        updated = db.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        return jsonify(dict(updated))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /api/inventory/batch
# ---------------------------------------------------------------------------
@inventory_bp.route("/inventory/batch", methods=["POST"])
@api_admin_required
def batch_create_inventory_items():
    try:
        body       = request.get_json(force=True, silent=True) or {}
        invoice_id_raw = body.get("invoice_id")
        invoice_id = int(invoice_id_raw) if invoice_id_raw else None
        groups     = body.get("groups", [])

        if not groups:
            return jsonify({"error": "groups cannot be empty"}), 400

        db      = get_db()
        created = []

        for group in groups:
            cloth_type   = (group.get("cloth_type")   or "").strip()
            company_name = (group.get("company_name") or "").strip()
            if not cloth_type or not company_name:
                return jsonify({"error": "cloth_type and company_name are required for every group"}), 400

            for item in group.get("items", []):
                item_name      = (item.get("item_name")    or "").strip() or None
                shade_number   = (item.get("shade_number") or "").strip() or None
                quality_number = (item.get("quality_number") or "").strip()
                cost_price     = float(item.get("cost_price")     or 0)
                mrp            = float(item.get("mrp")            or 0)
                opening_stock  = float(item.get("opening_stock")  or 0)
                min_stock_alert = float(item.get("min_stock_alert") or 5)
                notes          = (item.get("notes") or "").strip() or None
                unit_label     = (item.get("unit_label") or "m").strip()

                item_code = _next_item_code(db, cloth_type)
                cur = db.execute(
                    """INSERT INTO inventory_items
                       (cloth_type, company_name, quality_number, unit_label,
                        current_stock, min_stock_alert, mrp, cost_price, notes, item_code,
                        item_name, shade_number, invoice_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (cloth_type, company_name, quality_number, unit_label,
                     opening_stock, min_stock_alert, mrp, cost_price, notes, item_code,
                     item_name, shade_number, invoice_id),
                )
                item_id = cur.lastrowid

                if opening_stock > 0:
                    db.execute(
                        """INSERT INTO inventory_transactions
                           (item_id, txn_type, quantity, reference_type, notes, created_by)
                           VALUES (?, 'opening', ?, 'manual', 'Opening stock', ?)""",
                        (item_id, opening_stock, session.get("username")),
                    )
                created.append(item_id)

        db.commit()
        return jsonify({"created": len(created), "ids": created}), 201

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
        "SELECT * FROM inventory_items WHERE UPPER(item_code) = UPPER(?)", (item_code,)
    ).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404
    return jsonify(dict(item))


@inventory_bp.route("/inventory/<int:item_id>/qr", methods=["GET"])
@api_admin_required
def get_inventory_qr(item_id):
    try:
        from PIL import Image, ImageDraw, ImageFont

        db   = get_db()
        item = db.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return jsonify({"error": "Item not found"}), 404

        # Label: 64 mm × 34 mm at 300 DPI
        DPI    = 300
        W      = round(64 * DPI / 25.4)   # 756 px
        H      = round(34 * DPI / 25.4)   # 402 px
        M      = 16   # outer margin
        PAD    = 12   # inner padding after divider

        # Fonts — Segoe UI has the ₹ glyph; fall back to bitmap
        FONT_DIR = "C:/Windows/Fonts/"
        try:
            font_lbl = ImageFont.truetype(FONT_DIR + "segoeui.ttf",  20)
            font_val = ImageFont.truetype(FONT_DIR + "segoeuib.ttf", 28)
        except Exception:
            font_lbl = font_val = ImageFont.load_default()

        # QR code (square, fills the full height minus margins)
        code_text = item["item_code"] or f"#{item['id']}"
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=1)
        qr.add_data(f"inv:{code_text}")
        qr.make(fit=True)
        qr_pil  = qr.make_image(fill_color="black", back_color="white")
        qr_size = H - 2 * M
        qr_img  = qr_pil.get_image().resize((qr_size, qr_size), Image.NEAREST)

        # Canvas
        label = Image.new("RGB", (W, H), "white")
        draw  = ImageDraw.Draw(label)

        # Outer border
        draw.rectangle([0, 0, W - 1, H - 1], outline="black", width=3)

        # QR on left
        label.paste(qr_img, (M, M))

        # Vertical divider
        div_x = M + qr_size + M
        draw.line([(div_x, M), (div_x, H - M)], fill="#bbbbbb", width=2)

        # Text fields
        mrp   = item["mrp"]   if item["mrp"]   is not None else 0.0
        stock = item["current_stock"] if item["current_stock"] is not None else 0.0
        unit  = item["unit_label"] or "m"

        fields = [
            ("ID",        code_text),
            ("Item Name", item["item_name"] or "—"),
            ("Company",   item["company_name"] or "—"),
            ("Quality",   item["quality_number"] or "—"),
            ("MRP",       f"₹{float(mrp):.2f} / {unit}"),
            ("Length",    f"{float(stock):.2f} {unit}"),
        ]

        tx     = div_x + PAD
        line_h = (H - 2 * M) // len(fields)

        for idx, (lbl, val) in enumerate(fields):
            y = M + idx * line_h
            draw.text((tx, y + 2),      lbl + ":", font=font_lbl, fill="#999999")
            draw.text((tx, y + 2 + 22), val,       font=font_val, fill="#111111")

        buf = io.BytesIO()
        label.save(buf, format="PNG", dpi=(DPI, DPI))
        buf.seek(0)
        return send_file(buf, mimetype="image/png",
                         download_name=f"label-{code_text}.png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
