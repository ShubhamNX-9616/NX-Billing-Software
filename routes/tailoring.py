"""Tailoring Delivery System — routes.

Fully separate from the billing system: uses tailoring.db via db.tailoring,
its own upload folder, and its own page + share templates.
"""
import hashlib
import hmac
import io
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from flask import (Blueprint, current_app, jsonify, request, render_template,
                   redirect, send_from_directory)
from db.tailoring import get_tailoring_db, STAGES, GARMENT_TYPES, IST_NOW
from services.auth import api_login_required, login_required
from services import r2_storage
from utils import normalize_mobile

tailoring_api_bp = Blueprint("tailoring_api", __name__)
tailoring_pages_bp = Blueprint("tailoring_pages", __name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "tailoring")

MAX_PHOTO_DIM = 1400          # px, longest side after resize
PHOTO_JPEG_QUALITY = 82


IST = timezone(timedelta(hours=5, minutes=30))


def _ist_date():
    """Actual IST calendar date as a date object, independent of the host's
    timezone. date.today() returns the host-local date, which lags real IST on
    a UTC (or USA) host — so yesterday's deliveries were not flagged overdue
    until the host clock itself rolled past midnight. Deriving IST from UTC+5:30
    keeps date comparisons correct wherever the app runs."""
    return datetime.now(IST).date()


def _today_ist():
    return _ist_date().isoformat()


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


def _final_total(total, cloth_balance):
    """Stitching total plus any pending cloth money — advance/balance are
    tracked against this combined figure, not the stitching total alone."""
    return round((total or 0) + (cloth_balance or 0), 2)


def _split_off_unit(db, item, qty, stage):
    """Peel `qty` units off `item` into a new row with the given stage.
    Returns the new row's id. Caller commits."""
    remaining_qty = item["qty"] - qty
    remaining_amount = round(remaining_qty * item["rate"], 2)
    split_amount = round(qty * item["rate"], 2)
    db.execute("UPDATE tailoring_items SET qty = ?, amount = ? WHERE id = ?",
               (remaining_qty, remaining_amount, item["id"]))
    cur = db.execute(
        """INSERT INTO tailoring_items
           (order_id, garment_type, qty, rate, amount, stage, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (item["order_id"], item["garment_type"], qty, item["rate"],
         split_amount, stage, item["notes"]),
    )
    return cur.lastrowid


def _sync_delivered_at(db, order_id):
    """Keep the order's delivered_at in step with its item stages.

    Stamped the first time every garment reads Delivered, cleared if any item
    is rolled back — the weekly report needs the date an order was handed
    over, and item stages on their own only record that it happened.
    Caller commits."""
    stages = [r["stage"] for r in db.execute(
        "SELECT stage FROM tailoring_items WHERE order_id = ?", (order_id,)).fetchall()]
    if stages and all(s == "Delivered" for s in stages):
        db.execute(
            f"""UPDATE tailoring_orders
               SET delivered_at = COALESCE(delivered_at, {IST_NOW}) WHERE id = ?""",
            (order_id,))
    else:
        db.execute("UPDATE tailoring_orders SET delivered_at = NULL WHERE id = ?",
                   (order_id,))


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
    order["final_total"] = _final_total(order["total"], order["cloth_balance"])
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
        cloth_balance = float(body.get("cloth_balance") or 0)
        if cloth_balance < 0:
            return jsonify({"error": "Cloth balance cannot be negative"}), 400

        total = round(sum(i["amount"] for i in items), 2)
        final_total = _final_total(total, cloth_balance)
        if advance > final_total:
            return jsonify({"error": "Advance cannot exceed the total"}), 400
        balance = round(final_total - advance, 2)

        db = get_tailoring_db()
        if db.execute("SELECT 1 FROM tailoring_orders WHERE order_number = ?",
                      (order_number,)).fetchone():
            return jsonify({"error": f"Order number {order_number} already exists"}), 400
        try:
            cur = db.execute(
                """INSERT INTO tailoring_orders
                   (order_number, order_date, customer_name, mobile, address,
                    trial_date, delivery_date, total, advance, balance,
                    payment_mode, cloth_balance, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (order_number, order_date, customer_name, mobile, address,
                 trial_date, delivery_date, total, advance, balance,
                 payment_mode, cloth_balance, notes),
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
        _sync_delivered_at(db, order_id)   # items may be created already Delivered
        db.commit()

        order = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, order)), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Sort options for the orders list. Dates can be NULL, so every date key puts
# the blanks last regardless of direction (hence the separate has-value flag).
SORTS = {
    "order-desc":    (lambda o: o["order_number"], True),
    "order-asc":     (lambda o: o["order_number"], False),
    "delivery-asc":  (lambda o: (not o["delivery_date"], o["delivery_date"] or ""), False),
    "delivery-desc": (lambda o: (o["delivery_date"] or "",), True),
    "trial-asc":     (lambda o: (not o["trial_date"], o["trial_date"] or ""), False),
    "date-desc":     (lambda o: o["order_date"] or "", True),
    "date-asc":      (lambda o: o["order_date"] or "", False),
    "balance-desc":  (lambda o: o["balance"], True),
    "name-asc":      (lambda o: (o["customer_name"] or "").lower(), False),
}
DEFAULT_SORT = "order-desc"


# ---------------------------------------------------------------------------
# GET /api/tailoring/orders?q=&stage=&due=&sort=
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders", methods=["GET"])
@api_login_required
def list_orders():
    db = get_tailoring_db()
    q     = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "").strip()
    due   = (request.args.get("due") or "").strip()
    sort  = (request.args.get("sort") or "").strip()
    if sort not in SORTS:
        sort = DEFAULT_SORT

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

    key, reverse = SORTS[sort]
    orders.sort(key=key, reverse=reverse)

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
        "cloth_balance": order["cloth_balance"],
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
    today = _ist_date()
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


def _customer_index(db):
    """Name/mobile/address per customer, derived from orders.

    Unlike /tailoring/customers this reads the orders table directly instead
    of building full order payloads, so it is cheap enough to call on every
    keystroke of the order form's customer lookup. Mobiles are stored raw, so
    they are normalized here to make '+91 98765 43210' and '9876543210' match.
    Rows ascend by order_number, so the most recent spelling and address win.
    """
    index = {}
    rows = db.execute(
        "SELECT customer_name, mobile, address FROM tailoring_orders "
        "ORDER BY order_number"
    ).fetchall()
    for r in rows:
        norm = normalize_mobile(r["mobile"] or "")
        key = norm or "name:" + (r["customer_name"] or "").strip().lower()
        c = index.setdefault(key, {"customer_name": "", "mobile": "", "address": ""})
        c["customer_name"] = r["customer_name"]
        if r["mobile"]:
            c["mobile"] = r["mobile"]
        if r["address"]:
            c["address"] = r["address"]
    return index


# ---------------------------------------------------------------------------
# GET /api/tailoring/customers/search?mobile= — existing-customer lookup
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/customers/search", methods=["GET"])
@api_login_required
def tailoring_customer_search():
    raw = (request.args.get("mobile") or "").strip()
    if not raw:
        return jsonify({"error": "mobile param required"}), 400
    norm = normalize_mobile(raw)
    if len(norm) != 10:
        return jsonify({"found": False})
    customer = _customer_index(get_tailoring_db()).get(norm)
    if not customer:
        return jsonify({"found": False})
    return jsonify({"found": True, "customer": customer})


# ---------------------------------------------------------------------------
# GET /api/tailoring/customers/suggest?q= — name typeahead
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/customers/suggest", methods=["GET"])
@api_login_required
def tailoring_customer_suggest():
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    matches = [c for c in _customer_index(get_tailoring_db()).values()
               if q in (c["customer_name"] or "").lower()]
    matches.sort(key=lambda c: (c["customer_name"] or "").lower())
    return jsonify(matches[:8])


# ---------------------------------------------------------------------------
# GET /api/tailoring/customers — customer list derived from orders
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/customers", methods=["GET"])
@api_login_required
def tailoring_customers():
    """Tailoring has no customers table; group orders by mobile number
    (falling back to the name when no mobile was recorded). Mobiles are
    normalized so the same person entered as '+91 98765 43210' and
    '9876543210' groups into one customer, matching _customer_index()."""
    db = get_tailoring_db()
    q = (request.args.get("q") or "").strip().lower()

    orders = [_order_payload(db, r) for r in db.execute(
        "SELECT * FROM tailoring_orders ORDER BY order_number").fetchall()]

    groups = {}
    for o in orders:
        key = (normalize_mobile(o["mobile"] or "")
               or "name:" + o["customer_name"].strip().lower())
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
        if o["mobile"]:
            g["mobile"] = o["mobile"]
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
        # Digits in the query are matched against the normalized mobile, so
        # searching '9876543210' finds a number stored as '+91 98765 43210'.
        q_digits = normalize_mobile(q)
        def _matches(c):
            mobile = c["mobile"] or ""
            return (q in c["customer_name"].lower()
                    or q in mobile
                    or (bool(q_digits) and q_digits in normalize_mobile(mobile)))
        customers = [c for c in customers if _matches(c)]
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
        cloth_balance = float(body.get("cloth_balance") or 0)
        if cloth_balance < 0:
            return jsonify({"error": "Cloth balance cannot be negative"}), 400

        total = round(sum(i["amount"] for i in items), 2)
        final_total = _final_total(total, cloth_balance)
        if advance > final_total:
            return jsonify({"error": "Advance cannot exceed the total"}), 400
        balance = round(final_total - advance, 2)

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
                       advance = ?, balance = ?, payment_mode = ?, cloth_balance = ?, notes = ?,
                       updated_at = {IST_NOW}
                   WHERE id = ?""",
                (order_number, customer_name, mobile, address, order_date, trial_date,
                 delivery_date, total, advance, balance, payment_mode, cloth_balance,
                 notes, order_id),
            )
        except sqlite3.IntegrityError:
            # Another save took this number in the instant between our check and write.
            return jsonify({"error": f"Order number {order_number} already exists"}), 400
        # Item rows were reconciled above — deleting the last pending garment
        # can make the order fully delivered (or a new one can un-deliver it).
        _sync_delivered_at(db, order_id)
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
    _sync_delivered_at(db, item["order_id"])
    db.commit()
    row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (item["order_id"],)).fetchone()
    return jsonify(_order_payload(db, row))


# ---------------------------------------------------------------------------
# POST /api/tailoring/items/<id>/split — peel N units off into their own row
# so a subset of a multi-qty item (e.g. 1 of 3 shirts) can advance stage
# independently of the rest.
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/items/<int:item_id>/split", methods=["POST"])
@api_login_required
def split_item(item_id):
    body = request.get_json(force=True, silent=True) or {}
    try:
        split_qty = int(body.get("qty") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "qty must be a whole number"}), 400
    db = get_tailoring_db()
    item = db.execute("SELECT * FROM tailoring_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404
    if split_qty <= 0 or split_qty >= item["qty"]:
        return jsonify({"error": f"qty to split off must be between 1 and {item['qty'] - 1}"}), 400

    _split_off_unit(db, item, split_qty, item["stage"])
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
    _sync_delivered_at(db, order_id)
    db.commit()
    row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
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
        final_total = _final_total(row["total"], row["cloth_balance"])
        if advance > final_total:
            return jsonify({"error": "Paid amount cannot exceed the total"}), 400
        balance = round(final_total - advance, 2)

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
# PATCH /api/tailoring/orders/<id>/cloth-balance — pending payment for the
# cloth itself, separate from the stitching total/advance/balance above, so
# staff can see it before handing over the finished garment.
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/orders/<int:order_id>/cloth-balance", methods=["PATCH"])
@api_login_required
def update_cloth_balance(order_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_tailoring_db()
        row = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return jsonify({"error": "Order not found"}), 404

        cloth_balance = float(body.get("cloth_balance") or 0)
        if cloth_balance < 0:
            return jsonify({"error": "Cloth balance cannot be negative"}), 400
        final_total = _final_total(row["total"], cloth_balance)
        if row["advance"] > final_total:
            return jsonify({"error":
                f"Already recorded ₹{row['advance']:.2f} paid, which is more than "
                f"the new total of ₹{final_total:.2f} — lower the advance first"}), 400
        balance = round(final_total - row["advance"], 2)

        db.execute(
            f"""UPDATE tailoring_orders SET cloth_balance = ?, balance = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (cloth_balance, balance, order_id),
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

        final_total = _final_total(row["total"], row["cloth_balance"])
        new_advance = round(row["advance"] + amount, 2)
        if new_advance > final_total:
            return jsonify({"error":
                f"This would make total paid ₹{new_advance:.2f}, "
                f"more than the order total ₹{final_total:.2f}"}), 400

        db.execute(
            "INSERT INTO tailoring_payments (order_id, amount, mode) VALUES (?, ?, ?)",
            (order_id, amount, mode),
        )
        db.execute(
            f"""UPDATE tailoring_orders
               SET advance = ?, balance = ?, payment_mode = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (new_advance, round(final_total - new_advance, 2),
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
        final_total = _final_total(order["total"], order["cloth_balance"])
        new_advance = max(0.0, round(order["advance"] - p["amount"], 2))
        db.execute(
            f"""UPDATE tailoring_orders
               SET advance = ?, balance = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (new_advance, round(final_total - new_advance, 2), order["id"]),
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
        if r2_storage.is_configured():
            r2_storage.delete_object(p["filename"])
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

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=PHOTO_JPEG_QUALITY, optimize=True)
    filename = f"order{order_id}-{uuid.uuid4().hex[:10]}.jpg"

    # Prefer Cloudflare R2 (keeps the server's disk quota free); fall back to
    # local disk if R2 isn't configured, or if the upload fails, so a photo
    # is never lost to a storage hiccup.
    stored_on_r2 = r2_storage.is_configured() and r2_storage.upload_bytes(
        buf.getvalue(), filename)
    if not stored_on_r2:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
            f.write(buf.getvalue())

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
    if r2_storage.is_configured():
        r2_storage.delete_object(photo["filename"])
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/photos/<id>/item — reassign a photo to a different
# item line of the same order (or to "General" with item_id: null). Needed
# because a photo's item link is only ever set at upload time — e.g. after
# splitting "Shirt x3" into separate rows, a photo of one specific shirt has
# to be moved onto its split-off row by hand.
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/photos/<int:photo_id>/item", methods=["PATCH"])
@api_login_required
def move_photo(photo_id):
    body = request.get_json(force=True, silent=True) or {}
    raw_item_id = body.get("item_id")
    db = get_tailoring_db()
    photo = db.execute("SELECT * FROM tailoring_photos WHERE id = ?", (photo_id,)).fetchone()
    if not photo:
        return jsonify({"error": "Photo not found"}), 404

    item_id = None
    if raw_item_id not in (None, "", "null"):
        try:
            item_id = int(raw_item_id)
        except (TypeError, ValueError):
            return jsonify({"error": "item_id must be a number or null"}), 400
        item = db.execute(
            "SELECT 1 FROM tailoring_items WHERE id = ? AND order_id = ?",
            (item_id, photo["order_id"]),
        ).fetchone()
        if not item:
            return jsonify({"error": "That item does not belong to this order"}), 400

    db.execute("UPDATE tailoring_photos SET item_id = ? WHERE id = ?", (item_id, photo_id))
    db.commit()
    order = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (photo["order_id"],)).fetchone()
    return jsonify(_order_payload(db, order))


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/photos/<id>/stage — advance the one garment this photo
# shows to a new stage, in a single action. If it shares a row with other
# not-yet-photographed units (qty > 1), that unit is split off first and this
# photo follows it — so the user never has to think about splitting or
# reassigning photos by hand, just "this one is ready".
# ---------------------------------------------------------------------------
@tailoring_api_bp.route("/tailoring/photos/<int:photo_id>/stage", methods=["PATCH"])
@api_login_required
def set_photo_stage(photo_id):
    body = request.get_json(force=True, silent=True) or {}
    stage = (body.get("stage") or "").strip()
    if stage not in STAGES:
        return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
    db = get_tailoring_db()
    photo = db.execute("SELECT * FROM tailoring_photos WHERE id = ?", (photo_id,)).fetchone()
    if not photo:
        return jsonify({"error": "Photo not found"}), 404
    if not photo["item_id"]:
        return jsonify({"error": "Assign this photo to a garment before setting its stage"}), 400
    item = db.execute("SELECT * FROM tailoring_items WHERE id = ?", (photo["item_id"],)).fetchone()

    if stage != item["stage"]:
        if item["qty"] > 1:
            new_item_id = _split_off_unit(db, item, 1, stage)
            db.execute("UPDATE tailoring_photos SET item_id = ? WHERE id = ?",
                       (new_item_id, photo_id))
        else:
            db.execute("UPDATE tailoring_items SET stage = ? WHERE id = ?", (stage, item["id"]))
        db.execute(f"UPDATE tailoring_orders SET updated_at = {IST_NOW} WHERE id = ?",
                   (item["order_id"],))
        _sync_delivered_at(db, item["order_id"])
        db.commit()

    order = db.execute("SELECT * FROM tailoring_orders WHERE id = ?", (item["order_id"],)).fetchone()
    return jsonify(_order_payload(db, order))


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
    today = _ist_date()
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
            "cloth_balance": o["cloth_balance"],
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
    today = _ist_date()
    valid = {_report_token(today.isoformat()),
             _report_token((today - timedelta(days=1)).isoformat())}
    if token not in valid:
        return ("<h3 style='font-family:sans-serif;text-align:center;margin-top:40px;'>"
                "This report link has expired. Please ask the shop for today's link."
                "</h3>"), 404
    data = _build_report_data()
    return render_template("tailoring_report.html", shared=True,
                           share_path=None, **data)


# ---------------------------------------------------------------------------
# Weekly report — a look back over one Monday-to-Sunday week: what came in,
# what went out, what is still on the table. Work only, no money, because it
# goes to the same tailor as the daily report.
# ---------------------------------------------------------------------------
WEEKLY_SHARE_MAX_AGE_DAYS = 27      # ~3 weeks of shared links stay openable


def _week_bounds(ref):
    """Monday and Sunday of the week containing `ref`."""
    start = ref - timedelta(days=ref.weekday())
    return start, start + timedelta(days=6)


def _default_week_start(today):
    """Week to open by default. On a Monday the new week is still empty, so
    show the one that just ended — that is when the shop looks back at it."""
    start, _ = _week_bounds(today)
    return start - timedelta(days=7) if today.weekday() == 0 else start


def _parse_week_arg(raw, today):
    """Monday of the week asked for in ?week=YYYY-MM-DD; any date inside the
    week works. Falls back to the default week if missing or unparseable."""
    try:
        return _week_bounds(date.fromisoformat(str(raw)[:10]))[0]
    except (TypeError, ValueError):
        return _default_week_start(today)


def _weekly_report_token(week_start_s):
    """Unguessable token for the public weekly link, tied to the week it shows."""
    secret = str(current_app.secret_key or "tailoring-report")
    return hmac.new(secret.encode(), f"tailor-week:{week_start_s}".encode(),
                    hashlib.sha256).hexdigest()[:20]


def _merge_garments(items):
    """One line per garment type. Advancing part of a multi-qty item splits it
    into its own row (see _split_off_unit), which would otherwise print the
    same garment twice — the weekly report only cares about the count."""
    merged = {}
    for i in items:
        merged[i["garment_type"]] = merged.get(i["garment_type"], 0) + i["qty"]
    return [{"garment_type": g, "qty": q} for g, q in merged.items()]


def _build_weekly_report_data(week_start):
    """Everything that happened in one week, plus where the shop stands today."""
    db = get_tailoring_db()
    today = _ist_date()
    today_s = today.isoformat()
    week_end = week_start + timedelta(days=6)
    start_s, end_s = week_start.isoformat(), week_end.isoformat()

    def in_week(value):
        """True for a date or timestamp string landing inside the week."""
        return bool(value) and start_s <= str(value)[:10] <= end_s

    orders = [_order_payload(db, r) for r in
              db.execute("SELECT * FROM tailoring_orders").fetchall()]

    def brief(o, **extra):
        e = {
            "order_number": o["order_number"],
            "customer_name": o["customer_name"],
            "order_date": o["order_date"],
            "trial_date": o["trial_date"],
            "delivery_date": o["delivery_date"],
            "delivered_on": str(o["delivered_at"])[:10] if o["delivered_at"] else None,
            "stage": o["stage"],
            "notes": o["notes"],
            "items": _merge_garments(o["items"]),
            "qty": sum(i["qty"] for i in o["items"]),
        }
        e.update(extra)
        return e

    # Orders booked during the week
    taken = sorted((brief(o) for o in orders if in_week(o["order_date"])),
                   key=lambda e: (e["order_date"], e["order_number"]))

    # Orders handed over during the week (order-level: every garment Delivered)
    delivered = sorted((brief(o) for o in orders if in_week(o["delivered_at"])),
                       key=lambda e: (e["delivered_on"], e["order_number"]))

    # Trials that fell in the week, and whether the garments got that far
    trials = sorted(
        (brief(o, done=o["stage"] in ("Trial Ready", "Full Stitched", "Delivered"))
         for o in orders if in_week(o["trial_date"])),
        key=lambda e: (e["trial_date"], e["order_number"]))

    # Deliveries promised for the week — kept, ready but uncollected, or missed
    def promised_status(o):
        if o["delivered_at"]:
            return "Delivered"
        return "Ready to collect" if o["stage"] == "Full Stitched" else "Still pending"

    due = sorted((brief(o, status=promised_status(o))
                  for o in orders if in_week(o["delivery_date"])),
                 key=lambda e: (e["delivery_date"], e["order_number"]))

    # Garment-type tally: what came in against what went out
    tally = {}
    for e in taken:
        for i in e["items"]:
            tally.setdefault(i["garment_type"], {"taken": 0, "delivered": 0})["taken"] += i["qty"]
    for e in delivered:
        for i in e["items"]:
            tally.setdefault(i["garment_type"], {"taken": 0, "delivered": 0})["delivered"] += i["qty"]
    garments = sorted(({"garment_type": k, **v} for k, v in tally.items()),
                      key=lambda g: (-(g["taken"] + g["delivered"]), g["garment_type"]))

    # Day-by-day strip, Monday to Sunday
    days = []
    for n in range(7):
        day = week_start + timedelta(days=n)
        ds = day.isoformat()
        days.append({
            "date": ds,
            "weekday": day.strftime("%a"),
            "taken": sum(1 for e in taken if e["order_date"] == ds),
            "delivered": sum(1 for e in delivered if e["delivered_on"] == ds),
            "trials": sum(1 for e in trials if e["trial_date"] == ds),
            "is_future": ds > today_s,
        })

    # Where things stand right now — open work is not week-bound, it is what
    # the tailor still has in hand when they read this.
    open_orders = [o for o in orders if o["stage"] != "Delivered"]
    pending_stages = {s: 0 for s in STAGES[:-1]}
    pending_garments = 0
    for o in open_orders:
        pending_stages[o["stage"]] = pending_stages.get(o["stage"], 0) + 1
        pending_garments += sum(i["qty"] for i in o["items"] if i["stage"] != "Delivered")

    overdue = sorted(
        (brief(o, days_late=(today - date.fromisoformat(o["delivery_date"])).days)
         for o in open_orders if _is_overdue(o, today_s)),
        key=lambda e: e["delivery_date"])

    totals = {
        "orders_taken": len(taken),
        "garments_taken": sum(e["qty"] for e in taken),
        "orders_delivered": len(delivered),
        "garments_delivered": sum(e["qty"] for e in delivered),
        "trials": len(trials),
        "due": len(due),
        "due_kept": sum(1 for e in due if e["status"] == "Delivered"),
        "open_orders": len(open_orders),
        "pending_garments": pending_garments,
        "overdue": len(overdue),
    }

    next_start = week_start + timedelta(days=7)
    return {
        "week_start": start_s, "week_end": end_s, "today": today_s,
        "prev_week": (week_start - timedelta(days=7)).isoformat(),
        "next_week": next_start.isoformat(),
        "has_next": next_start <= today,
        "is_current_week": start_s <= today_s <= end_s,
        "taken": taken, "delivered": delivered, "trials": trials, "due": due,
        "garments": garments, "days": days, "overdue": overdue,
        "pending_stages": pending_stages, "totals": totals,
    }


@tailoring_pages_bp.route("/tailoring/report/weekly")
@login_required
def tailoring_weekly_report():
    """Staff view — printable, week picker, WhatsApp button with a share link."""
    week_start = _parse_week_arg(request.args.get("week"), _ist_date())
    data = _build_weekly_report_data(week_start)
    token = _weekly_report_token(data["week_start"])
    share_path = f"/tailoring/report/weekly/share/{data['week_start']}/{token}"
    return render_template("tailoring_weekly_report.html", shared=False,
                           share_path=share_path, **data)


@tailoring_pages_bp.route("/tailoring/report/weekly/share/<week>/<token>")
def tailoring_weekly_report_shared(week, token):
    """Public weekly view opened from the WhatsApp link — no login needed.
    The week is in the URL, so links are retired by age instead of by token."""
    expired = ("<h3 style='font-family:sans-serif;text-align:center;margin-top:40px;'>"
               "This weekly report link has expired. Please ask the shop for a new one."
               "</h3>"), 404
    try:
        week_start = date.fromisoformat(week)
    except ValueError:
        return expired
    if week_start.weekday() != 0:            # only Monday-aligned links are ours
        return expired
    if not hmac.compare_digest(token, _weekly_report_token(week)):
        return expired
    if (_ist_date() - week_start).days > WEEKLY_SHARE_MAX_AGE_DAYS:
        return expired

    data = _build_weekly_report_data(week_start)
    return render_template("tailoring_weekly_report.html", shared=True,
                           share_path=None, **data)


@tailoring_pages_bp.route("/tailoring/photos/<path:filename>")
def tailoring_photo_file(filename):
    """Serve uploaded cloth-sample photos (also used by the public receipt).
    Older photos live on local disk; newer ones are offloaded to R2 — check
    disk first so nothing existing breaks, then redirect to R2 if needed."""
    if os.path.isfile(os.path.join(os.path.abspath(UPLOAD_DIR), filename)):
        return send_from_directory(os.path.abspath(UPLOAD_DIR), filename)
    if r2_storage.is_configured():
        return redirect(r2_storage.public_url(filename))
    return jsonify({"error": "Photo not found"}), 404


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
