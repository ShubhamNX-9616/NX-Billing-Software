"""Tailoring Delivery System — routes.

Fully separate from the billing system: uses tailoring.db via db.tailoring,
its own upload folder, and its own page + share templates.
"""
import hashlib
import hmac
import os
import sqlite3
import uuid
from datetime import date, timedelta
from flask import (Blueprint, current_app, jsonify, request, render_template,
                   send_from_directory)
from db.tailoring import get_tailoring_db, STAGES, GARMENT_TYPES, IST_NOW
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


def _is_overdue(order, today_s):
    """Overdue = delivery date passed and stitching still pending.
    Once every garment is Full Stitched, collecting the order is the
    customer's responsibility, so it no longer counts as overdue."""
    return (bool(order["delivery_date"]) and order["delivery_date"] < today_s
            and order["stage"] not in ("Full Stitched", "Delivered"))


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
    payments = [dict(r) for r in db.execute(
        "SELECT * FROM tailoring_payments WHERE order_id = ? ORDER BY id", (order["id"],)
    ).fetchall()]
    order["payments"] = payments
    # Orders from before payment history existed (or edited via the old
    # set-total endpoint) may have paid more than the recorded entries.
    order["unrecorded_paid"] = round(
        order["advance"] - sum(p["amount"] for p in payments), 2)
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


def _parse_order_number(body):
    """The order number is typed from the paper receipt book — required."""
    raw = str(body.get("order_number") or "").strip()
    if not raw:
        raise ValueError("Order number is required (copy it from the receipt book)")
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError("Order number must be a positive number")
    return int(raw)


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
            order_number = _parse_order_number(body)
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
        if db.execute("SELECT 1 FROM tailoring_orders WHERE order_number = ?",
                      (order_number,)).fetchone():
            return jsonify({"error": f"Order number {order_number} already exists"}), 400
        try:
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
        except sqlite3.IntegrityError:
            # Two devices saved the same number in the same instant — the
            # SELECT above missed it, but the UNIQUE constraint catches it.
            return jsonify({"error": f"Order number {order_number} already exists"}), 400
        order_id = cur.lastrowid
        for it in items:
            db.execute(
                """INSERT INTO tailoring_items
                   (order_id, garment_type, qty, rate, amount, stage, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order_id, it["garment_type"], it["qty"], it["rate"],
                 it["amount"], it["stage"], it["notes"]),
            )
        if advance > 0:
            db.execute(
                "INSERT INTO tailoring_payments (order_id, amount, mode, note) "
                "VALUES (?, ?, ?, 'Advance')",
                (order_id, advance, payment_mode),
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
        orders = [o for o in orders if _is_overdue(o, today)]

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
            if _is_overdue(o, today):
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
# GET /api/tailoring/dashboard — preparation view for the staff
# ---------------------------------------------------------------------------
def _order_brief(order):
    """Compact order summary for dashboard lists (no photos)."""
    return {
        "id": order["id"],
        "order_number": order["order_number"],
        "customer_name": order["customer_name"],
        "mobile": order["mobile"],
        "trial_date": order["trial_date"],
        "delivery_date": order["delivery_date"],
        "stage": order["stage"],
        "balance": order["balance"],
        "items": [{"garment_type": i["garment_type"], "qty": i["qty"], "stage": i["stage"]}
                  for i in order["items"]],
        "ready_items": sum(1 for i in order["items"]
                           if i["stage"] in ("Full Stitched", "Delivered")),
        "total_items": len(order["items"]),
    }


@tailoring_api_bp.route("/tailoring/dashboard", methods=["GET"])
@api_login_required
def tailoring_dashboard():
    db = get_tailoring_db()
    today = date.today()
    today_s = today.isoformat()
    tomorrow_s = (today + timedelta(days=1)).isoformat()

    orders = [_order_payload(db, r) for r in
              db.execute("SELECT * FROM tailoring_orders").fetchall()]
    open_orders = [o for o in orders if o["stage"] != "Delivered"]

    # Delivery load per day for the next 15 days (today included):
    # order count plus pending-garment breakdown, e.g. {"Shirt": 5, "Trouser": 6}
    days = []
    for n in range(15):
        ds = (today + timedelta(days=n)).isoformat()
        due = [o for o in open_orders if o["delivery_date"] == ds]
        garments = {}
        for o in due:
            for i in o["items"]:
                if i["stage"] != "Delivered":
                    garments[i["garment_type"]] = garments.get(i["garment_type"], 0) + i["qty"]
        days.append({
            "date": ds,
            "orders": len(due),
            "garments": garments,
            "trials": sum(1 for o in open_orders if o["trial_date"] == ds),
            "order_list": [_order_brief(o) for o in due],
        })

    overdue = sorted(
        (_order_brief(o) for o in open_orders if _is_overdue(o, today_s)),
        key=lambda b: b["delivery_date"],
    )
    for b in overdue:
        b["days_late"] = (today - date.fromisoformat(b["delivery_date"])).days

    # Fully stitched, delivery date arrived/passed (or never set) — the
    # customer needs a reminder call to come and collect.
    ready_waiting = sorted(
        (_order_brief(o) for o in open_orders
         if o["stage"] == "Full Stitched"
         and (not o["delivery_date"] or o["delivery_date"] <= today_s)),
        key=lambda b: b["delivery_date"] or "",
    )
    for b in ready_waiting:
        if b["delivery_date"] and b["delivery_date"] < today_s:
            b["days_waiting"] = (today - date.fromisoformat(b["delivery_date"])).days

    def due_on(field, ds):
        return [_order_brief(o) for o in open_orders if o[field] == ds]

    return jsonify({
        "today": today_s,
        "days": days,
        "overdue": overdue,
        "ready_waiting": ready_waiting,
        "deliveries_today": due_on("delivery_date", today_s),
        "deliveries_tomorrow": due_on("delivery_date", tomorrow_s),
        "trials_today": due_on("trial_date", today_s),
        "trials_tomorrow": due_on("trial_date", tomorrow_s),
    })


# ---------------------------------------------------------------------------
# GET /api/tailoring/customers — customer list derived from orders
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/customers", methods=["GET"])
@api_login_required
def tailoring_customers():
    """Tailoring has no customers table; group orders by mobile number
    (falling back to the name when no mobile was recorded)."""
    db = get_tailoring_db()
    q = (request.args.get("q") or "").strip().lower()

    orders = [_order_payload(db, r) for r in db.execute(
        "SELECT * FROM tailoring_orders ORDER BY order_number").fetchall()]

    groups = {}
    for o in orders:
        key = (o["mobile"] or "").strip() or "name:" + o["customer_name"].strip().lower()
        g = groups.setdefault(key, {
            "customer_name": o["customer_name"],
            "mobile": o["mobile"],
            "address": o["address"],
            "orders": 0,
            "open_orders": 0,
            "total_business": 0.0,
            "pending_balance": 0.0,
            "first_order_date": o["order_date"],
            "last_order_date": o["order_date"],
        })
        # Orders come in ascending order_number, so the latest spelling wins
        g["customer_name"] = o["customer_name"]
        if o["address"]:
            g["address"] = o["address"]
        g["orders"] += 1
        if o["stage"] != "Delivered":
            g["open_orders"] += 1
        g["total_business"] += o["total"]
        g["pending_balance"] += o["balance"]
        if o["order_date"] < g["first_order_date"]:
            g["first_order_date"] = o["order_date"]
        if o["order_date"] > g["last_order_date"]:
            g["last_order_date"] = o["order_date"]

    customers = list(groups.values())
    for c in customers:
        c["total_business"] = round(c["total_business"], 2)
        c["pending_balance"] = round(c["pending_balance"], 2)

    if q:
        customers = [c for c in customers
                     if q in c["customer_name"].lower() or q in (c["mobile"] or "")]
    customers.sort(key=lambda c: c["customer_name"].lower())
    return jsonify({"customers": customers, "total": len(customers)})


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
            # Absent in older clients → keep the current number
            order_number = (_parse_order_number(body)
                            if "order_number" in body else existing["order_number"])
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

        if order_number != existing["order_number"] and db.execute(
                "SELECT 1 FROM tailoring_orders WHERE order_number = ?",
                (order_number,)).fetchone():
            return jsonify({"error": f"Order number {order_number} already exists"}), 400

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

        try:
            db.execute(
                f"""UPDATE tailoring_orders
                   SET order_number = ?, customer_name = ?, mobile = ?, address = ?,
                       order_date = ?, trial_date = ?, delivery_date = ?, total = ?,
                       advance = ?, balance = ?, payment_mode = ?, notes = ?,
                       updated_at = {IST_NOW}
                   WHERE id = ?""",
                (order_number, customer_name, mobile, address, order_date, trial_date,
                 delivery_date, total, advance, balance, payment_mode, notes, order_id),
            )
        except sqlite3.IntegrityError:
            # Another save took this number in the instant between our check and write.
            return jsonify({"error": f"Order number {order_number} already exists"}), 400
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
# POST /api/tailoring/orders/<id>/payments — record one payment (with history)
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders/<int:order_id>/payments", methods=["POST"])
@api_login_required
def record_payment(order_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_tailoring_db()
        row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return jsonify({"error": "Order not found"}), 404

        try:
            amount = round(float(body.get("amount") or 0), 2)
        except (TypeError, ValueError):
            return jsonify({"error": "Amount must be a number"}), 400
        if amount <= 0:
            return jsonify({"error": "Amount must be greater than zero"}), 400
        mode = (body.get("mode") or "").strip() or None

        new_advance = round(row["advance"] + amount, 2)
        if new_advance > row["total"]:
            return jsonify({"error":
                f"This would make total paid ₹{new_advance:.2f}, "
                f"more than the order total ₹{row['total']:.2f}"}), 400

        db.execute(
            "INSERT INTO tailoring_payments (order_id, amount, mode) VALUES (?, ?, ?)",
            (order_id, amount, mode),
        )
        db.execute(
            f"""UPDATE tailoring_orders
               SET advance = ?, balance = ?, payment_mode = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (new_advance, round(row["total"] - new_advance, 2),
             mode or row["payment_mode"], order_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/tailoring/payments/<id> — undo a wrongly entered payment
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/payments/<int:payment_id>", methods=["DELETE"])
@api_login_required
def delete_payment(payment_id):
    try:
        db = get_tailoring_db()
        p = db.execute("SELECT * FROM tailoring_payments WHERE id = ?", (payment_id,)).fetchone()
        if not p:
            return jsonify({"error": "Payment not found"}), 404
        order = db.execute("SELECT * FROM tailoring_orders WHERE id = ?",
                           (p["order_id"],)).fetchone()

        db.execute("DELETE FROM tailoring_payments WHERE id = ?", (payment_id,))
        new_advance = max(0.0, round(order["advance"] - p["amount"], 2))
        db.execute(
            f"""UPDATE tailoring_orders
               SET advance = ?, balance = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (new_advance, round(order["total"] - new_advance, 2), order["id"]),
        )
        db.commit()
        row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order["id"],)).fetchone()
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


def _report_token(day_s):
    """Unguessable token for the public tailor-report link, tied to a date so
    old links stop working (valid the day it was made and the next)."""
    secret = str(current_app.secret_key or "tailoring-report")
    return hmac.new(secret.encode(), f"tailor-report:{day_s}".encode(),
                    hashlib.sha256).hexdigest()[:20]


def _build_report_data():
    """Tailor work report data: overdue orders + tomorrow's deliveries/trials."""
    db = get_tailoring_db()
    today = date.today()
    today_s = today.isoformat()
    tomorrow_s = (today + timedelta(days=1)).isoformat()

    orders = [_order_payload(db, r) for r in
              db.execute("SELECT * FROM tailoring_orders").fetchall()]
    open_orders = [o for o in orders if o["stage"] != "Delivered"]

    def entry(o, mode):
        """mode 'trial': work needed until Trial Ready; else until Full Stitched."""
        items = []
        for i in o["items"]:
            if i["stage"] == "Delivered":
                continue
            done_stages = ("Trial Ready", "Full Stitched") if mode == "trial" \
                else ("Full Stitched",)
            items.append({
                "garment_type": i["garment_type"],
                "qty": i["qty"],
                "stage": i["stage"],
                "notes": i["notes"],
                "needs_work": i["stage"] not in done_stages,
                "photos": [p["filename"] for p in i["photos"]],
            })
        e = {
            "order_number": o["order_number"],
            "customer_name": o["customer_name"],
            "trial_date": o["trial_date"],
            "delivery_date": o["delivery_date"],
            "notes": o["notes"],
            "items": items,
            "measurement_photos": [p["filename"] for p in o["general_photos"]],
        }
        if mode == "overdue":
            e["days_late"] = (today - date.fromisoformat(o["delivery_date"])).days
        return e

    overdue = sorted((entry(o, "overdue") for o in open_orders
                      if _is_overdue(o, today_s)),
                     key=lambda e: e["delivery_date"])
    deliveries = [entry(o, "delivery") for o in open_orders
                  if o["delivery_date"] == tomorrow_s
                  and o["stage"] not in ("Full Stitched",)]
    trials = [entry(o, "trial") for o in open_orders
              if o["trial_date"] == tomorrow_s]

    return {"overdue": overdue, "deliveries": deliveries, "trials": trials,
            "today": today_s, "tomorrow": tomorrow_s}


@tailoring_pages_bp.route("/tailoring/report")
@login_required
def tailoring_report():
    """Staff view — printable, with a WhatsApp button carrying the share link."""
    data = _build_report_data()
    token = _report_token(data["today"])
    return render_template("tailoring_report.html", shared=False,
                           share_path=f"/tailoring/report/share/{token}", **data)


@tailoring_pages_bp.route("/tailoring/report/share/<token>")
def tailoring_report_shared(token):
    """Public tailor view, opened from the WhatsApp link — no login needed.
    Accepts today's and yesterday's token so a 10pm link survives midnight."""
    today = date.today()
    valid = {_report_token(today.isoformat()),
             _report_token((today - timedelta(days=1)).isoformat())}
    if token not in valid:
        return ("<h3 style='font-family:sans-serif;text-align:center;margin-top:40px;'>"
                "This report link has expired. Please ask the shop for today's link."
                "</h3>"), 404
    data = _build_report_data()
    return render_template("tailoring_report.html", shared=True,
                           share_path=None, **data)


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
