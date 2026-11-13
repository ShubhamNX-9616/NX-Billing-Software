"""Measurements trial - billing: orders, garment lines, payments.

Registered on the same blueprint as the rest of the measurements API (see the
import at the bottom of routes/measurements.py), so it only exists when
MEASUREMENTS_ENABLED is set and only ever uses measurements.db.

An order groups the garments taken for one customer and carries the money. Each
garment is a normal m_measurements row linked by order_id, so measurements,
photos, statuses and the dashboard keep working exactly as before.
"""
import json
import re

from flask import jsonify, render_template, request

from db.measurements import IST_NOW, get_measurements_db
from routes.measurements import (_clean_date, _customer_dict, _measurement_dict,
                                 _remove_photo_file, _today_ist,
                                 measurements_api_bp, measurements_pages_bp)
from services.auth import api_staff_or_admin_required, staff_or_admin_required
from services.measurement_billing import (ORDER_TYPES, default_rate, final_total,
                                          item_amount, next_order_number,
                                          order_label, order_status,
                                          parse_money, payment_problem,
                                          recompute_order, remember_rate,
                                          sync_item_dates)
from services.measurement_fields import DEFAULT_STATUS, GARMENTS, clean_values, piece_count


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------
def _payment_dict(p):
    return {"id": p["id"], "amount": p["amount"], "mode": p["mode"] or "",
            "note": p["note"] or "", "paid_at": p["paid_at"]}


def order_payload(db, o):
    customer = db.execute("SELECT * FROM m_customers WHERE id = ?",
                          (o["customer_id"],)).fetchone()
    items = db.execute("SELECT * FROM m_measurements WHERE order_id = ? ORDER BY id",
                       (o["id"],)).fetchall()
    payments = db.execute("SELECT * FROM m_payments WHERE order_id = ? ORDER BY id",
                          (o["id"],)).fetchall()
    return {
        "id": o["id"],
        "order_type": o["order_type"],
        "order_number": o["order_number"],
        "label": order_label(o["order_type"], o["order_number"]),
        "customer": _customer_dict(customer),
        "order_date": o["order_date"],
        "trial_date": o["trial_date"],
        "delivery_date": o["delivery_date"],
        "total": o["total"],
        "cloth_balance": o["cloth_balance"],
        "final_total": final_total(o["total"], o["cloth_balance"]),
        "advance": o["advance"],
        "balance": o["balance"],
        "payment_mode": o["payment_mode"] or "",
        "notes": o["notes"] or "",
        "delivered_at": o["delivered_at"],
        "status": order_status([i["status"] for i in items]),
        "items": [_measurement_dict(i) for i in items],
        "payments": [_payment_dict(p) for p in payments],
        "created_at": o["created_at"],
    }


def _get_order(db, order_id):
    return db.execute("SELECT * FROM m_orders WHERE id = ?", (order_id,)).fetchone()


# ---------------------------------------------------------------------------
# Garment lines
# ---------------------------------------------------------------------------
def _parse_item(db, order_type, data):
    """Validate one garment line. Returns (item, error)."""
    garment_type = (data.get("garment_type") or "").strip().lower()
    if garment_type not in GARMENTS:
        return None, "Choose a garment"
    values, err = clean_values(garment_type, data.get("values") or {})
    if err:
        return None, err
    raw_rate = data.get("rate")
    if raw_rate is None or (isinstance(raw_rate, str) and not raw_rate.strip()):
        rate = default_rate(db, order_type, garment_type)     # blank -> saved default
    else:
        rate, err = parse_money(raw_rate, "Rate")
        if err:
            return None, err
    qty = piece_count(garment_type, values)
    return {
        "garment_type": garment_type,
        "values_json": json.dumps(values),
        "notes": (data.get("notes") or "").strip() or None,
        "qty": qty,
        "rate": rate,
        "amount": item_amount(rate, qty),
    }, None


def _insert_item(db, order, item):
    cur = db.execute(
        "INSERT INTO m_measurements (customer_id, garment_type, values_json, notes, "
        "order_date, trial_date, delivery_date, status, order_id, qty, rate, amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (order["customer_id"], item["garment_type"], item["values_json"], item["notes"],
         order["order_date"], order["trial_date"], order["delivery_date"], DEFAULT_STATUS,
         order["id"], item["qty"], item["rate"], item["amount"]))
    remember_rate(db, order["order_type"], item["garment_type"], item["rate"])
    return cur.lastrowid


def _parse_dates(data, required_order_date=False):
    """Returns ({field: value}, error) for whichever date fields are present."""
    out = {}
    for key in ("order_date", "trial_date", "delivery_date"):
        if key not in data:
            continue
        d = _clean_date(data.get(key))
        if d is False:
            return None, f"Invalid {key.replace('_', ' ')}"
        if key == "order_date" and d is None:
            d = _today_ist()
        out[key] = d
    return out, None


def _clean_mode(raw):
    return (str(raw or "").strip()[:30]) or None


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@measurements_api_bp.route("/measurements/orders", methods=["GET"])
@api_staff_or_admin_required
def list_orders():
    """?q= name / mobile / order number, ?type=general|suit, ?customer_id=, ?open=1"""
    db = get_measurements_db()
    sql = ("SELECT o.*, c.name AS cname, c.mobile AS cmobile FROM m_orders o "
           "JOIN m_customers c ON c.id = o.customer_id")
    clauses, params = [], []
    q = (request.args.get("q") or "").strip()
    if q:
        digits = re.sub(r"\D", "", q)
        parts = ["c.name LIKE ?"]
        params.append(f"%{q}%")
        if digits:
            parts += ["c.mobile LIKE ?", "CAST(o.order_number AS TEXT) = ?"]
            params += [f"%{digits}%", digits.lstrip("0") or "0"]
        clauses.append("(" + " OR ".join(parts) + ")")
    otype = (request.args.get("type") or "").strip()
    if otype in ORDER_TYPES:
        clauses.append("o.order_type = ?")
        params.append(otype)
    cid = request.args.get("customer_id", type=int)
    if cid:
        clauses.append("o.customer_id = ?")
        params.append(cid)
    if request.args.get("open") == "1":
        clauses.append("o.delivered_at IS NULL")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY o.id DESC LIMIT 200"
    rows = db.execute(sql, params).fetchall()

    ids = [r["id"] for r in rows]
    garments = {}
    if ids:
        marks = ",".join("?" * len(ids))
        for i in db.execute(
                f"SELECT order_id, garment_type, qty, status FROM m_measurements "
                f"WHERE order_id IN ({marks}) ORDER BY id", ids):
            garments.setdefault(i["order_id"], []).append(i)

    out = []
    for r in rows:
        items = garments.get(r["id"], [])
        out.append({
            "id": r["id"],
            "order_type": r["order_type"],
            "order_number": r["order_number"],
            "label": order_label(r["order_type"], r["order_number"]),
            "customer_id": r["customer_id"],
            "customer_name": r["cname"],
            "mobile": r["cmobile"],
            "order_date": r["order_date"],
            "trial_date": r["trial_date"],
            "delivery_date": r["delivery_date"],
            "total": r["total"],
            "cloth_balance": r["cloth_balance"],
            "advance": r["advance"],
            "balance": r["balance"],
            "delivered_at": r["delivered_at"],
            "status": order_status([i["status"] for i in items]),
            "item_count": len(items),
            "garments": [{"garment_type": i["garment_type"],
                          "label": GARMENTS.get(i["garment_type"], {}).get(
                              "label", i["garment_type"].title()),
                          "qty": i["qty"]} for i in items],
        })
    return jsonify(out)


@measurements_api_bp.route("/measurements/orders", methods=["POST"])
@api_staff_or_admin_required
def create_order():
    data = request.get_json(silent=True) or {}
    db = get_measurements_db()

    customer = db.execute("SELECT * FROM m_customers WHERE id = ?",
                          (data.get("customer_id"),)).fetchone()
    if not customer:
        return jsonify({"error": "Choose a customer"}), 400
    order_type = (data.get("order_type") or "general").strip().lower()
    if order_type not in ORDER_TYPES:
        return jsonify({"error": "Order type must be general or suit"}), 400

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"error": "Add at least one garment"}), 400
    items = []
    for raw in raw_items:
        item, err = _parse_item(db, order_type, raw if isinstance(raw, dict) else {})
        if err:
            return jsonify({"error": err}), 400
        items.append(item)

    dates, err = _parse_dates({"order_date": data.get("order_date"),
                               "trial_date": data.get("trial_date"),
                               "delivery_date": data.get("delivery_date")})
    if err:
        return jsonify({"error": err}), 400

    cloth, err = parse_money(data.get("cloth_balance"), "Cloth balance")
    if err:
        return jsonify({"error": err}), 400
    advance, err = parse_money(data.get("advance"), "Advance")
    if err:
        return jsonify({"error": err}), 400
    total = round(sum(i["amount"] for i in items), 2)
    if advance > final_total(total, cloth):
        return jsonify({"error": "Advance cannot exceed the total"}), 400
    mode = _clean_mode(data.get("payment_mode"))

    try:
        number = next_order_number(db, order_type)
        cur = db.execute(
            "INSERT INTO m_orders (order_type, order_number, customer_id, order_date, "
            "trial_date, delivery_date, cloth_balance, payment_mode, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order_type, number, customer["id"], dates["order_date"], dates["trial_date"],
             dates["delivery_date"], cloth, mode, (data.get("notes") or "").strip() or None))
        order = _get_order(db, cur.lastrowid)
        for item in items:
            _insert_item(db, order, item)
        if advance > 0:
            db.execute("INSERT INTO m_payments (order_id, amount, mode, note) "
                       "VALUES (?, ?, ?, 'Advance')", (order["id"], advance, mode))
        recompute_order(db, order["id"])
        db.commit()
    except Exception:
        db.rollback()          # also releases the reserved order number
        raise
    return jsonify(order_payload(db, _get_order(db, order["id"]))), 201


@measurements_api_bp.route("/measurements/orders/<int:order_id>", methods=["GET"])
@api_staff_or_admin_required
def get_order(order_id):
    db = get_measurements_db()
    order = _get_order(db, order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    return jsonify(order_payload(db, order))


@measurements_api_bp.route("/measurements/orders/<int:order_id>", methods=["PUT"])
@api_staff_or_admin_required
def update_order(order_id):
    """Partial update of the order header: dates, notes, payment mode, cloth balance."""
    db = get_measurements_db()
    order = _get_order(db, order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    data = request.get_json(silent=True) or {}

    dates, err = _parse_dates(data)
    if err:
        return jsonify({"error": err}), 400
    fields = dict(dates)
    if "notes" in data:
        fields["notes"] = (data.get("notes") or "").strip() or None
    if "payment_mode" in data:
        fields["payment_mode"] = _clean_mode(data.get("payment_mode"))
    if "cloth_balance" in data:
        cloth, err = parse_money(data.get("cloth_balance"), "Cloth balance")
        if err:
            return jsonify({"error": err}), 400
        problem = payment_problem(db, order_id, new_cloth=cloth)
        if problem:
            return jsonify({"error": problem}), 400
        fields["cloth_balance"] = cloth

    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE m_orders SET {sets}, updated_at = ({IST_NOW}) WHERE id = ?",
                   (*fields.values(), order_id))
        sync_item_dates(db, order_id)
        recompute_order(db, order_id)
        db.commit()
    return jsonify(order_payload(db, _get_order(db, order_id)))


@measurements_api_bp.route("/measurements/orders/<int:order_id>", methods=["DELETE"])
@api_staff_or_admin_required
def delete_order(order_id):
    db = get_measurements_db()
    if not _get_order(db, order_id):
        return jsonify({"error": "Order not found"}), 404
    images = [r["image"] for r in db.execute(
        "SELECT image FROM m_measurements WHERE order_id = ?", (order_id,))]
    db.execute("DELETE FROM m_measurements WHERE order_id = ?", (order_id,))
    db.execute("DELETE FROM m_orders WHERE id = ?", (order_id,))   # payments cascade
    db.commit()
    for img in images:
        _remove_photo_file(img)
    return jsonify({"ok": True})


@measurements_api_bp.route("/measurements/orders/<int:order_id>/items", methods=["POST"])
@api_staff_or_admin_required
def add_order_item(order_id):
    """Add another garment (with its measurement and rate) to an existing order."""
    db = get_measurements_db()
    order = _get_order(db, order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    item, err = _parse_item(db, order["order_type"], request.get_json(silent=True) or {})
    if err:
        return jsonify({"error": err}), 400
    _insert_item(db, order, item)
    recompute_order(db, order_id)
    db.commit()
    return jsonify(order_payload(db, _get_order(db, order_id))), 201


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@measurements_api_bp.route("/measurements/orders/<int:order_id>/payments", methods=["POST"])
@api_staff_or_admin_required
def record_payment(order_id):
    db = get_measurements_db()
    order = _get_order(db, order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    data = request.get_json(silent=True) or {}
    amount, err = parse_money(data.get("amount"), "Amount")
    if err:
        return jsonify({"error": err}), 400
    if amount <= 0:
        return jsonify({"error": "Amount must be greater than zero"}), 400
    paid_at = _clean_date(data.get("paid_at"))
    if paid_at is False:
        return jsonify({"error": "Invalid payment date"}), 400
    owed = final_total(order["total"], order["cloth_balance"])
    new_paid = round(order["advance"] + amount, 2)
    if new_paid > owed:
        return jsonify({"error": f"This would make total paid Rs {new_paid:.2f}, "
                                 f"more than the order total Rs {owed:.2f}"}), 400
    mode = _clean_mode(data.get("mode"))
    db.execute("INSERT INTO m_payments (order_id, amount, mode, note, paid_at) "
               "VALUES (?, ?, ?, ?, ?)",
               (order_id, amount, mode, (data.get("note") or "").strip() or None,
                paid_at or _today_ist()))
    if mode:
        db.execute("UPDATE m_orders SET payment_mode = ? WHERE id = ?", (mode, order_id))
    recompute_order(db, order_id)
    db.commit()
    return jsonify(order_payload(db, _get_order(db, order_id))), 201


@measurements_api_bp.route("/measurements/payments/<int:payment_id>", methods=["DELETE"])
@api_staff_or_admin_required
def delete_payment(payment_id):
    """Undo a wrongly entered payment."""
    db = get_measurements_db()
    p = db.execute("SELECT * FROM m_payments WHERE id = ?", (payment_id,)).fetchone()
    if not p:
        return jsonify({"error": "Payment not found"}), 404
    db.execute("DELETE FROM m_payments WHERE id = ?", (payment_id,))
    recompute_order(db, p["order_id"])
    db.commit()
    return jsonify(order_payload(db, _get_order(db, p["order_id"])))


# ---------------------------------------------------------------------------
# Printable receipt (page, not API)
# ---------------------------------------------------------------------------
@measurements_pages_bp.route("/measurements/orders/<int:order_id>/receipt")
@staff_or_admin_required
def order_receipt(order_id):
    db = get_measurements_db()
    order = _get_order(db, order_id)
    if not order:
        return "Order not found", 404
    return render_template("measurements_receipt.html", o=order_payload(db, order))
