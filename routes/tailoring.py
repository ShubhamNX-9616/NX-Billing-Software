"""Tailoring Delivery System — routes.

Fully separate from the billing system: uses tailoring.db via db.tailoring,
its own upload folder, and its own page + share templates.
"""
import os
import uuid
from datetime import date
from flask import Blueprint, jsonify, request, render_template, send_from_directory
from db.tailoring import get_tailoring_db, next_order_number, STAGES, GARMENT_TYPES, IST_NOW
from services.auth import api_login_required, login_required

tailoring_api_bp = Blueprint("tailoring_api", __name__)
tailoring_pages_bp = Blueprint("tailoring_pages", __name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "tailoring")

MAX_PHOTO_DIM = 1400          # px, longest side after resize
PHOTO_JPEG_QUALITY = 82


def _today_ist():
    # SQLite IST_NOW handles timestamps; for date comparisons use local date,
    # which on this deployment (shop PC, IST timezone) matches IST.
    return date.today().isoformat()


def _derived_stage(item_stages):
    """Order-level stage = the earliest stage among its items."""
    if not item_stages:
        return STAGES[0]
    return min(item_stages, key=lambda s: STAGES.index(s) if s in STAGES else 0)


def _order_payload(db, order_row):
    order = dict(order_row)
    items = [dict(r) for r in db.execute(
        "SELECT * FROM tailoring_items WHERE order_id = ? ORDER BY id", (order["id"],)
    ).fetchall()]
    photos = [dict(r) for r in db.execute(
        "SELECT * FROM tailoring_photos WHERE order_id = ? ORDER BY id", (order["id"],)
    ).fetchall()]
    for it in items:
        it["photos"] = [p for p in photos if p["item_id"] == it["id"]]
    order["items"] = items
    order["photos"] = photos          # all photos (incl. per-item ones)
    order["general_photos"] = [p for p in photos if not p["item_id"]]
    order["stage"] = _derived_stage([i["stage"] for i in items])
    return order


def _parse_items(body):
    """Validate and normalise the items array from a create/update body."""
    items = body.get("items") or []
    if not isinstance(items, list) or not items:
        raise ValueError("At least one item is required")
    parsed = []
    for it in items:
        garment = (it.get("garment_type") or "").strip()
        if not garment:
            raise ValueError("Every item needs a garment type")
        qty = int(it.get("qty") or 0)
        if qty <= 0:
            raise ValueError(f"Quantity for {garment} must be at least 1")
        rate = float(it.get("rate") or 0)
        if rate < 0:
            raise ValueError(f"Rate for {garment} cannot be negative")
        stage = (it.get("stage") or STAGES[0]).strip()
        if stage not in STAGES:
            stage = STAGES[0]
        parsed.append({
            "id": it.get("id"),
            "garment_type": garment,
            "qty": qty,
            "rate": rate,
            "amount": round(qty * rate, 2),
            "stage": stage,
            "notes": (it.get("notes") or "").strip() or None,
        })
    return parsed


# ---------------------------------------------------------------------------
# GET /api/tailoring/meta — stage + garment lists for the UI
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/meta", methods=["GET"])
@api_login_required
def tailoring_meta():
    return jsonify({"stages": STAGES, "garment_types": GARMENT_TYPES})


# ---------------------------------------------------------------------------
# POST /api/tailoring/orders
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders", methods=["POST"])
@api_login_required
def create_order():
    try:
        body = request.get_json(force=True, silent=True) or {}

        customer_name = (body.get("customer_name") or "").strip()
        if not customer_name:
            return jsonify({"error": "Customer name is required"}), 400

        try:
            items = _parse_items(body)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

        mobile        = (body.get("mobile") or "").strip() or None
        address       = (body.get("address") or "").strip() or None
        order_date    = (body.get("order_date") or "").strip() or _today_ist()
        trial_date    = (body.get("trial_date") or "").strip() or None
        delivery_date = (body.get("delivery_date") or "").strip() or None
        payment_mode  = (body.get("payment_mode") or "").strip() or None
        notes         = (body.get("notes") or "").strip() or None
        advance       = float(body.get("advance") or 0)
        if advance < 0:
            return jsonify({"error": "Advance cannot be negative"}), 400

        total = round(sum(i["amount"] for i in items), 2)
        if advance > total:
            return jsonify({"error": "Advance cannot exceed the total"}), 400
        balance = round(total - advance, 2)

        db = get_tailoring_db()
        order_number = next_order_number(db)
        cur = db.execute(
            """INSERT INTO tailoring_orders
               (order_number, order_date, customer_name, mobile, address,
                trial_date, delivery_date, total, advance, balance,
                payment_mode, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order_number, order_date, customer_name, mobile, address,
             trial_date, delivery_date, total, advance, balance,
             payment_mode, notes),
        )
        order_id = cur.lastrowid
        for it in items:
            db.execute(
                """INSERT INTO tailoring_items
                   (order_id, garment_type, qty, rate, amount, stage, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order_id, it["garment_type"], it["qty"], it["rate"],
                 it["amount"], it["stage"], it["notes"]),
            )
        db.commit()

        order = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, order)), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/tailoring/orders?q=&stage=&due=
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders", methods=["GET"])
@api_login_required
def list_orders():
    db = get_tailoring_db()
    q     = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "").strip()
    due   = (request.args.get("due") or "").strip()

    sql = "SELECT * FROM tailoring_orders"
    where, params = [], []
    if q:
        where.append("(customer_name LIKE ? OR mobile LIKE ? OR CAST(order_number AS TEXT) LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY order_number DESC"

    orders = [_order_payload(db, r) for r in db.execute(sql, params).fetchall()]

    if stage:
        orders = [o for o in orders if o["stage"] == stage]

    today = _today_ist()
    if due == "trial-today":
        orders = [o for o in orders if o["trial_date"] == today and o["stage"] != "Delivered"]
    elif due == "delivery-today":
        orders = [o for o in orders if o["delivery_date"] == today and o["stage"] != "Delivered"]
    elif due == "overdue":
        orders = [o for o in orders
                  if o["delivery_date"] and o["delivery_date"] < today and o["stage"] != "Delivered"]

    # Dashboard counts (computed over all orders, ignoring the filters)
    all_orders = [_order_payload(db, r) for r in
                  db.execute("SELECT * FROM tailoring_orders").fetchall()]
    counts = {s: 0 for s in STAGES}
    trial_today = delivery_today = overdue = 0
    for o in all_orders:
        counts[o["stage"]] = counts.get(o["stage"], 0) + 1
        if o["stage"] != "Delivered":
            if o["trial_date"] == today:
                trial_today += 1
            if o["delivery_date"] == today:
                delivery_today += 1
            if o["delivery_date"] and o["delivery_date"] < today:
                overdue += 1

    return jsonify({
        "orders": orders,
        "counts": {
            "stages": counts,
            "trial_today": trial_today,
            "delivery_today": delivery_today,
            "overdue": overdue,
            "total": len(all_orders),
        },
    })


# ---------------------------------------------------------------------------
# GET /api/tailoring/orders/<id>
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders/<int:order_id>", methods=["GET"])
@api_login_required
def get_order(order_id):
    db = get_tailoring_db()
    row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Order not found"}), 404
    return jsonify(_order_payload(db, row))


# ---------------------------------------------------------------------------
# PUT /api/tailoring/orders/<id>
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders/<int:order_id>", methods=["PUT"])
@api_login_required
def update_order(order_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_tailoring_db()
        existing = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Order not found"}), 404

        customer_name = (body.get("customer_name") or "").strip()
        if not customer_name:
            return jsonify({"error": "Customer name is required"}), 400

        try:
            items = _parse_items(body)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

        mobile        = (body.get("mobile") or "").strip() or None
        address       = (body.get("address") or "").strip() or None
        order_date    = (body.get("order_date") or "").strip() or existing["order_date"]
        trial_date    = (body.get("trial_date") or "").strip() or None
        delivery_date = (body.get("delivery_date") or "").strip() or None
        payment_mode  = (body.get("payment_mode") or "").strip() or None
        notes         = (body.get("notes") or "").strip() or None
        advance       = float(body.get("advance") or 0)
        if advance < 0:
            return jsonify({"error": "Advance cannot be negative"}), 400

        total = round(sum(i["amount"] for i in items), 2)
        if advance > total:
            return jsonify({"error": "Advance cannot exceed the total"}), 400
        balance = round(total - advance, 2)

        # Reconcile items: update rows whose id is sent, insert new ones,
        # delete the ones no longer present. Stages of kept items survive.
        old_ids = {r["id"] for r in db.execute(
            "SELECT id FROM tailoring_items WHERE order_id = ?", (order_id,)).fetchall()}
        sent_ids = set()
        for it in items:
            iid = it.get("id")
            if iid and int(iid) in old_ids:
                iid = int(iid)
                sent_ids.add(iid)
                db.execute(
                    """UPDATE tailoring_items
                       SET garment_type = ?, qty = ?, rate = ?, amount = ?, notes = ?
                       WHERE id = ? AND order_id = ?""",
                    (it["garment_type"], it["qty"], it["rate"], it["amount"],
                     it["notes"], iid, order_id),
                )
            else:
                db.execute(
                    """INSERT INTO tailoring_items
                       (order_id, garment_type, qty, rate, amount, stage, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, it["garment_type"], it["qty"], it["rate"],
                     it["amount"], it["stage"], it["notes"]),
                )
        for gone in old_ids - sent_ids:
            db.execute("DELETE FROM tailoring_items WHERE id = ?", (gone,))

        db.execute(
            f"""UPDATE tailoring_orders
               SET customer_name = ?, mobile = ?, address = ?, order_date = ?,
                   trial_date = ?, delivery_date = ?, total = ?, advance = ?,
                   balance = ?, payment_mode = ?, notes = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (customer_name, mobile, address, order_date, trial_date, delivery_date,
             total, advance, balance, payment_mode, notes, order_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, row))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/items/<id>/stage
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/items/<int:item_id>/stage", methods=["PATCH"])
@api_login_required
def update_item_stage(item_id):
    body = request.get_json(force=True, silent=True) or {}
    stage = (body.get("stage") or "").strip()
    if stage not in STAGES:
        return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
    db = get_tailoring_db()
    item = db.execute("SELECT * FROM tailoring_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404
    db.execute("UPDATE tailoring_items SET stage = ? WHERE id = ?", (stage, item_id))
    db.execute(f"UPDATE tailoring_orders SET updated_at = {IST_NOW} WHERE id = ?",
               (item["order_id"],))
    db.commit()
    row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (item["order_id"],)).fetchone()
    return jsonify(_order_payload(db, row))


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/orders/<id>/stage  — set every item at once
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders/<int:order_id>/stage", methods=["PATCH"])
@api_login_required
def update_order_stage(order_id):
    body = request.get_json(force=True, silent=True) or {}
    stage = (body.get("stage") or "").strip()
    if stage not in STAGES:
        return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
    db = get_tailoring_db()
    row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Order not found"}), 404
    db.execute("UPDATE tailoring_items SET stage = ? WHERE order_id = ?", (stage, order_id))
    db.execute(f"UPDATE tailoring_orders SET updated_at = {IST_NOW} WHERE id = ?", (order_id,))
    db.commit()
    return jsonify(_order_payload(db, row))


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/orders/<id>/payment
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders/<int:order_id>/payment", methods=["PATCH"])
@api_login_required
def update_payment(order_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_tailoring_db()
        row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return jsonify({"error": "Order not found"}), 404

        advance = float(body.get("advance", row["advance"]))
        payment_mode = (body.get("payment_mode") or row["payment_mode"] or "").strip() or None
        if advance < 0:
            return jsonify({"error": "Advance cannot be negative"}), 400
        if advance > row["total"]:
            return jsonify({"error": "Paid amount cannot exceed the total"}), 400
        balance = round(row["total"] - advance, 2)

        db.execute(
            f"""UPDATE tailoring_orders
               SET advance = ?, balance = ?, payment_mode = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (advance, balance, payment_mode, order_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/tailoring/orders/<id>
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders/<int:order_id>", methods=["DELETE"])
@api_login_required
def delete_order(order_id):
    db = get_tailoring_db()
    row = db.execute("SELECT id FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Order not found"}), 404
    photos = db.execute(
        "SELECT filename FROM tailoring_photos WHERE order_id = ?", (order_id,)).fetchall()
    db.execute("DELETE FROM tailoring_orders WHERE id = ?", (order_id,))
    db.commit()
    for p in photos:
        try:
            os.remove(os.path.join(UPLOAD_DIR, p["filename"]))
        except OSError:
            pass
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders/<int:order_id>/photos", methods=["POST"])
@api_login_required
def upload_photo(order_id):
    db = get_tailoring_db()
    row = db.execute("SELECT id FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Order not found"}), 404

    file = request.files.get("photo")
    if not file:
        return jsonify({"error": "No photo provided"}), 400

    # Optional: attach the photo to one garment line of this order
    item_id_raw = (request.form.get("item_id") or "").strip()
    item_id = None
    if item_id_raw:
        item = db.execute(
            "SELECT id FROM tailoring_items WHERE id = ? AND order_id = ?",
            (item_id_raw, order_id),
        ).fetchone()
        if not item:
            return jsonify({"error": "Item does not belong to this order"}), 400
        item_id = item["id"]

    try:
        from PIL import Image, ImageOps
        img = Image.open(file.stream)
        img = ImageOps.exif_transpose(img)   # respect phone camera orientation
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((MAX_PHOTO_DIM, MAX_PHOTO_DIM))
    except Exception:
        return jsonify({"error": "File is not a valid image"}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"order{order_id}-{uuid.uuid4().hex[:10]}.jpg"
    img.save(os.path.join(UPLOAD_DIR, filename), "JPEG",
             quality=PHOTO_JPEG_QUALITY, optimize=True)

    db.execute(
        "INSERT INTO tailoring_photos (order_id, item_id, filename) VALUES (?, ?, ?)",
        (order_id, item_id, filename),
    )
    db.commit()
    order = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
    return jsonify(_order_payload(db, order)), 201


@tailoring_api_bp.route("/tailoring/photos/<int:photo_id>", methods=["DELETE"])
@api_login_required
def delete_photo(photo_id):
    db = get_tailoring_db()
    photo = db.execute("SELECT * FROM tailoring_photos WHERE id = ?", (photo_id,)).fetchone()
    if not photo:
        return jsonify({"error": "Photo not found"}), 404
    db.execute("DELETE FROM tailoring_photos WHERE id = ?", (photo_id,))
    db.commit()
    try:
        os.remove(os.path.join(UPLOAD_DIR, photo["filename"]))
    except OSError:
        pass
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@tailoring_pages_bp.route("/tailoring")
@login_required
def tailoring_page():
    return render_template("tailoring.html")


@tailoring_pages_bp.route("/tailoring/photos/<path:filename>")
def tailoring_photo_file(filename):
    """Serve uploaded cloth-sample photos (also used by the public receipt)."""
    return send_from_directory(os.path.abspath(UPLOAD_DIR), filename)


@tailoring_pages_bp.route("/tailoring/share/<int:order_number>")
def tailoring_receipt(order_number):
    """Public receipt page — linked in the WhatsApp message, printable."""
    db = get_tailoring_db()
    row = db.execute(
        "SELECT * FROM tailoring_orders WHERE order_number = ?", (order_number,)
    ).fetchone()
    if not row:
        return render_template("tailoring_receipt_not_found.html",
                               order_number=order_number), 404
    order = _order_payload(db, row)
    return render_template("tailoring_receipt.html", order=order)
