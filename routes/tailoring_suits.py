"""Suits Tailoring — routes.

A second, fully independent order book living in the same tailoring.db as
the general Tailoring Delivery System (routes/tailoring.py), but with its
own tables. An order here is identified by (book_no, order_number) rather
than order_number alone, because a physical suit order book gets replaced
over time and the new book's numbering can restart from 1 — something the
general system's single globally-unique order_number could never allow.

Everything else (stages, split, photos, payments, dashboard, customers) is
a straight parallel of routes/tailoring.py, kept as its own module rather
than a shared abstraction so the two books can evolve independently without
risking each other.
"""
import io
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from flask import Blueprint, jsonify, request, render_template
from db.tailoring import get_tailoring_db, STAGES, GARMENT_TYPES, IST_NOW
from services.auth import api_login_required, login_required
from services import r2_storage
from utils import normalize_mobile

tailoring_suit_api_bp = Blueprint("tailoring_suit_api", __name__)
tailoring_suit_pages_bp = Blueprint("tailoring_suit_pages", __name__)

# Same physical folder (and R2 bucket) as the general system, and the photos
# are served by that system's existing /tailoring/photos/<filename> route —
# filenames are prefixed "suit" below so the two never collide.
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "tailoring")

MAX_PHOTO_DIM = 1400
PHOTO_JPEG_QUALITY = 82

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_date():
    return datetime.now(IST).date()


def _today_ist():
    return _ist_date().isoformat()


def _is_overdue(order, today_s):
    return (bool(order["delivery_date"]) and order["delivery_date"] < today_s
            and order["stage"] not in ("Full Stitched", "Delivered"))


def _derived_stage(item_stages):
    if not item_stages:
        return STAGES[0]
    return min(item_stages, key=lambda s: STAGES.index(s) if s in STAGES else 0)


def _final_total(total, cloth_balance):
    return round((total or 0) + (cloth_balance or 0), 2)


def _split_off_unit(db, item, qty, stage):
    remaining_qty = item["qty"] - qty
    remaining_amount = round(remaining_qty * item["rate"], 2)
    split_amount = round(qty * item["rate"], 2)
    db.execute("UPDATE tailoring_suit_items SET qty = ?, amount = ? WHERE id = ?",
               (remaining_qty, remaining_amount, item["id"]))
    cur = db.execute(
        """INSERT INTO tailoring_suit_items
           (order_id, garment_type, qty, rate, amount, stage, stitched_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (item["order_id"], item["garment_type"], qty, item["rate"],
         split_amount, stage, item["stitched_at"], item["notes"]),
    )
    return cur.lastrowid


def _sync_stage_stamps(db, order_id):
    db.execute(
        f"""UPDATE tailoring_suit_items SET stitched_at = COALESCE(stitched_at, {IST_NOW})
           WHERE order_id = ? AND stage IN ('Full Stitched', 'Delivered')""",
        (order_id,))
    db.execute(
        """UPDATE tailoring_suit_items SET stitched_at = NULL
           WHERE order_id = ? AND stage NOT IN ('Full Stitched', 'Delivered')""",
        (order_id,))
    stages = [r["stage"] for r in db.execute(
        "SELECT stage FROM tailoring_suit_items WHERE order_id = ?", (order_id,)).fetchall()]
    if stages and all(s == "Delivered" for s in stages):
        db.execute(
            f"""UPDATE tailoring_suit_orders
               SET delivered_at = COALESCE(delivered_at, {IST_NOW}) WHERE id = ?""",
            (order_id,))
    else:
        db.execute("UPDATE tailoring_suit_orders SET delivered_at = NULL WHERE id = ?",
                   (order_id,))


def _order_payload(db, order_row):
    order = dict(order_row)
    items = [dict(r) for r in db.execute(
        "SELECT * FROM tailoring_suit_items WHERE order_id = ? ORDER BY id", (order["id"],)
    ).fetchall()]
    photos = [dict(r) for r in db.execute(
        "SELECT * FROM tailoring_suit_photos WHERE order_id = ? ORDER BY id", (order["id"],)
    ).fetchall()]
    for it in items:
        it["photos"] = [p for p in photos if p["item_id"] == it["id"]]
    order["items"] = items
    order["photos"] = photos
    order["general_photos"] = [p for p in photos if not p["item_id"]]
    order["stage"] = _derived_stage([i["stage"] for i in items])
    order["final_total"] = _final_total(order["total"], order["cloth_balance"])
    payments = [dict(r) for r in db.execute(
        "SELECT * FROM tailoring_suit_payments WHERE order_id = ? ORDER BY id", (order["id"],)
    ).fetchall()]
    order["payments"] = payments
    order["unrecorded_paid"] = round(
        order["advance"] - sum(p["amount"] for p in payments), 2)
    return order


def _order_payloads_bulk(db, order_rows):
    """Same shape as [_order_payload(db, r) for r in order_rows], but fetches
    items/photos/payments for every order in 3 queries total instead of 3
    per order — mirrors tailoring.py's _order_payloads_bulk."""
    order_rows = list(order_rows)
    if not order_rows:
        return []
    ids = [r["id"] for r in order_rows]
    placeholders = ",".join("?" * len(ids))

    items_by_order, photos_by_order, payments_by_order = {}, {}, {}
    for r in db.execute(
        f"SELECT * FROM tailoring_suit_items WHERE order_id IN ({placeholders}) ORDER BY id", ids
    ).fetchall():
        items_by_order.setdefault(r["order_id"], []).append(dict(r))
    for r in db.execute(
        f"SELECT * FROM tailoring_suit_photos WHERE order_id IN ({placeholders}) ORDER BY id", ids
    ).fetchall():
        photos_by_order.setdefault(r["order_id"], []).append(dict(r))
    for r in db.execute(
        f"SELECT * FROM tailoring_suit_payments WHERE order_id IN ({placeholders}) ORDER BY id", ids
    ).fetchall():
        payments_by_order.setdefault(r["order_id"], []).append(dict(r))

    orders = []
    for row in order_rows:
        order = dict(row)
        items = items_by_order.get(order["id"], [])
        photos = photos_by_order.get(order["id"], [])
        for it in items:
            it["photos"] = [p for p in photos if p["item_id"] == it["id"]]
        order["items"] = items
        order["photos"] = photos
        order["general_photos"] = [p for p in photos if not p["item_id"]]
        order["stage"] = _derived_stage([i["stage"] for i in items])
        order["final_total"] = _final_total(order["total"], order["cloth_balance"])
        payments = payments_by_order.get(order["id"], [])
        order["payments"] = payments
        order["unrecorded_paid"] = round(
            order["advance"] - sum(p["amount"] for p in payments), 2)
        orders.append(order)
    return orders


def _parse_items(body):
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
    raw = str(body.get("order_number") or "").strip()
    if not raw:
        raise ValueError("Order number is required (copy it from the receipt book)")
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError("Order number must be a positive number")
    return int(raw)


def _parse_book_no(body):
    """Which physical order book this entry was written in — required, since
    order numbers only avoid clashing within the same book."""
    raw = str(body.get("book_no") or "").strip()
    if not raw:
        raise ValueError("Book number is required")
    return raw


# ---------------------------------------------------------------------------
# GET /api/tailoring/suits/meta
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/meta", methods=["GET"])
@api_login_required
def suit_meta():
    db = get_tailoring_db()
    rates = {r["garment_type"]: r["rate"] for r in
              db.execute("SELECT garment_type, rate FROM tailoring_suit_garment_rates").fetchall()}
    # Sticky Book No default: whichever book the most recently-created order
    # used, so a shop working through one book doesn't retype it every time.
    last = db.execute(
        "SELECT book_no FROM tailoring_suit_orders ORDER BY id DESC LIMIT 1").fetchone()
    return jsonify({
        "stages": STAGES,
        "garment_types": GARMENT_TYPES,
        "garment_rates": rates,
        "last_book_no": last["book_no"] if last else "",
    })


def _remember_garment_rates(db, items):
    for it in items:
        if it["rate"] > 0:
            db.execute(
                f"""INSERT INTO tailoring_suit_garment_rates (garment_type, rate, updated_at)
                   VALUES (?, ?, {IST_NOW})
                   ON CONFLICT(garment_type) DO UPDATE
                   SET rate = excluded.rate, updated_at = excluded.updated_at""",
                (it["garment_type"], it["rate"]),
            )


# ---------------------------------------------------------------------------
# POST /api/tailoring/suits/orders
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders", methods=["POST"])
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
            book_no = _parse_book_no(body)
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
        if db.execute("SELECT 1 FROM tailoring_suit_orders WHERE book_no = ? AND order_number = ?",
                      (book_no, order_number)).fetchone():
            return jsonify({"error":
                f"Order number {order_number} already exists in Book {book_no}"}), 400
        try:
            cur = db.execute(
                """INSERT INTO tailoring_suit_orders
                   (book_no, order_number, order_date, customer_name, mobile, address,
                    trial_date, delivery_date, total, advance, balance,
                    payment_mode, cloth_balance, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (book_no, order_number, order_date, customer_name, mobile, address,
                 trial_date, delivery_date, total, advance, balance,
                 payment_mode, cloth_balance, notes),
            )
        except sqlite3.IntegrityError:
            return jsonify({"error":
                f"Order number {order_number} already exists in Book {book_no}"}), 400
        order_id = cur.lastrowid
        for it in items:
            db.execute(
                """INSERT INTO tailoring_suit_items
                   (order_id, garment_type, qty, rate, amount, stage, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (order_id, it["garment_type"], it["qty"], it["rate"],
                 it["amount"], it["stage"], it["notes"]),
            )
        _remember_garment_rates(db, items)
        if advance > 0:
            db.execute(
                "INSERT INTO tailoring_suit_payments (order_id, amount, mode, note) "
                "VALUES (?, ?, ?, 'Advance')",
                (order_id, advance, payment_mode),
            )
        _sync_stage_stamps(db, order_id)
        db.commit()

        order = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, order)), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
# GET /api/tailoring/suits/orders?q=&stage=&due=&sort=
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders", methods=["GET"])
@api_login_required
def list_orders():
    db = get_tailoring_db()
    q     = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "").strip()
    due   = (request.args.get("due") or "").strip()
    sort  = (request.args.get("sort") or "").strip()
    if sort not in SORTS:
        sort = DEFAULT_SORT

    sql = "SELECT * FROM tailoring_suit_orders"
    where, params = [], []
    if q:
        q_digits = q.replace(" ", "")
        if q_digits.isdigit():
            # See routes/tailoring.py's list_orders for why prefix-matching
            # (not "contains anywhere") avoids false hits: order/book numbers
            # count up from small integers while real Indian mobiles always
            # start 6-9, so the two search spaces don't collide.
            where.append(
                "(CAST(order_number AS TEXT) LIKE ? OR norm_mobile(mobile) LIKE ? OR book_no LIKE ?)"
            )
            params += [f"{q_digits}%", f"{q_digits}%", f"{q_digits}%"]
        else:
            where.append("customer_name LIKE ?")
            params.append(f"%{q}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY order_number DESC"

    orders = _order_payloads_bulk(db, db.execute(sql, params).fetchall())

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

    all_orders = _order_payloads_bulk(
        db, db.execute("SELECT * FROM tailoring_suit_orders").fetchall())
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
# GET /api/tailoring/suits/dashboard
# ---------------------------------------------------------------------------
def _order_brief(order):
    return {
        "id": order["id"],
        "order_number": order["order_number"],
        "book_no": order["book_no"],
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


@tailoring_suit_api_bp.route("/tailoring/suits/dashboard", methods=["GET"])
@api_login_required
def suit_dashboard():
    db = get_tailoring_db()
    today = _ist_date()
    today_s = today.isoformat()
    tomorrow_s = (today + timedelta(days=1)).isoformat()

    orders = _order_payloads_bulk(
        db, db.execute("SELECT * FROM tailoring_suit_orders").fetchall())
    open_orders = [o for o in orders if o["stage"] != "Delivered"]

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

    overdue_orders = [o for o in open_orders if _is_overdue(o, today_s)]
    overdue = sorted((_order_brief(o) for o in overdue_orders),
                     key=lambda b: b["delivery_date"])
    for b in overdue:
        b["days_late"] = (today - date.fromisoformat(b["delivery_date"])).days

    overdue_garments = {}
    for o in overdue_orders:
        for i in o["items"]:
            if i["stage"] != "Delivered":
                overdue_garments[i["garment_type"]] = \
                    overdue_garments.get(i["garment_type"], 0) + i["qty"]
    overdue_day = {
        "orders": len(overdue),
        "garments": overdue_garments,
        "trials": sum(1 for o in open_orders
                      if o["trial_date"] and o["trial_date"] < today_s
                      and o["stage"] != "Full Stitched"),
        "order_list": overdue,
    }

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
        "overdue_day": overdue_day,
        "overdue": overdue,
        "ready_waiting": ready_waiting,
        "deliveries_today": due_on("delivery_date", today_s),
        "deliveries_tomorrow": due_on("delivery_date", tomorrow_s),
        "trials_today": due_on("trial_date", today_s),
        "trials_tomorrow": due_on("trial_date", tomorrow_s),
    })


def _customer_index(db):
    index = {}
    rows = db.execute(
        "SELECT customer_name, mobile, address FROM tailoring_suit_orders "
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
# GET /api/tailoring/suits/customers/search?mobile=
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/customers/search", methods=["GET"])
@api_login_required
def suit_customer_search():
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
# GET /api/tailoring/suits/customers/suggest?q=
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/customers/suggest", methods=["GET"])
@api_login_required
def suit_customer_suggest():
    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    matches = [c for c in _customer_index(get_tailoring_db()).values()
               if q in (c["customer_name"] or "").lower()]
    matches.sort(key=lambda c: (c["customer_name"] or "").lower())
    return jsonify(matches[:8])


# ---------------------------------------------------------------------------
# GET /api/tailoring/suits/customers
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/customers", methods=["GET"])
@api_login_required
def suit_customers():
    db = get_tailoring_db()
    q = (request.args.get("q") or "").strip().lower()

    orders = _order_payloads_bulk(db, db.execute(
        "SELECT * FROM tailoring_suit_orders ORDER BY order_number").fetchall())

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
# GET /api/tailoring/suits/orders/<id>
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders/<int:order_id>", methods=["GET"])
@api_login_required
def get_order(order_id):
    db = get_tailoring_db()
    row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Order not found"}), 404
    return jsonify(_order_payload(db, row))


# ---------------------------------------------------------------------------
# PUT /api/tailoring/suits/orders/<id>
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders/<int:order_id>", methods=["PUT"])
@api_login_required
def update_order(order_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_tailoring_db()
        existing = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Order not found"}), 404

        customer_name = (body.get("customer_name") or "").strip()
        if not customer_name:
            return jsonify({"error": "Customer name is required"}), 400

        try:
            items = _parse_items(body)
            order_number = (_parse_order_number(body)
                            if "order_number" in body else existing["order_number"])
            book_no = _parse_book_no(body) if "book_no" in body else existing["book_no"]
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

        if (order_number, book_no) != (existing["order_number"], existing["book_no"]) and db.execute(
                "SELECT 1 FROM tailoring_suit_orders WHERE book_no = ? AND order_number = ?",
                (book_no, order_number)).fetchone():
            return jsonify({"error":
                f"Order number {order_number} already exists in Book {book_no}"}), 400

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

        old_ids = {r["id"] for r in db.execute(
            "SELECT id FROM tailoring_suit_items WHERE order_id = ?", (order_id,)).fetchall()}
        sent_ids = set()
        for it in items:
            iid = it.get("id")
            if iid and int(iid) in old_ids:
                iid = int(iid)
                sent_ids.add(iid)
                db.execute(
                    """UPDATE tailoring_suit_items
                       SET garment_type = ?, qty = ?, rate = ?, amount = ?, notes = ?
                       WHERE id = ? AND order_id = ?""",
                    (it["garment_type"], it["qty"], it["rate"], it["amount"],
                     it["notes"], iid, order_id),
                )
            else:
                db.execute(
                    """INSERT INTO tailoring_suit_items
                       (order_id, garment_type, qty, rate, amount, stage, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, it["garment_type"], it["qty"], it["rate"],
                     it["amount"], it["stage"], it["notes"]),
                )
        for gone in old_ids - sent_ids:
            db.execute("DELETE FROM tailoring_suit_items WHERE id = ?", (gone,))
        _remember_garment_rates(db, items)

        try:
            db.execute(
                f"""UPDATE tailoring_suit_orders
                   SET book_no = ?, order_number = ?, customer_name = ?, mobile = ?, address = ?,
                       order_date = ?, trial_date = ?, delivery_date = ?, total = ?,
                       advance = ?, balance = ?, payment_mode = ?, cloth_balance = ?, notes = ?,
                       updated_at = {IST_NOW}
                   WHERE id = ?""",
                (book_no, order_number, customer_name, mobile, address, order_date, trial_date,
                 delivery_date, total, advance, balance, payment_mode, cloth_balance,
                 notes, order_id),
            )
        except sqlite3.IntegrityError:
            return jsonify({"error":
                f"Order number {order_number} already exists in Book {book_no}"}), 400
        _sync_stage_stamps(db, order_id)
        db.commit()
        row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, row))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/suits/items/<id>/stage
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/items/<int:item_id>/stage", methods=["PATCH"])
@api_login_required
def update_item_stage(item_id):
    body = request.get_json(force=True, silent=True) or {}
    stage = (body.get("stage") or "").strip()
    if stage not in STAGES:
        return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
    db = get_tailoring_db()
    item = db.execute("SELECT * FROM tailoring_suit_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404
    db.execute("UPDATE tailoring_suit_items SET stage = ? WHERE id = ?", (stage, item_id))
    db.execute(f"UPDATE tailoring_suit_orders SET updated_at = {IST_NOW} WHERE id = ?",
               (item["order_id"],))
    _sync_stage_stamps(db, item["order_id"])
    db.commit()
    row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (item["order_id"],)).fetchone()
    return jsonify(_order_payload(db, row))


# ---------------------------------------------------------------------------
# POST /api/tailoring/suits/items/<id>/split
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/items/<int:item_id>/split", methods=["POST"])
@api_login_required
def split_item(item_id):
    body = request.get_json(force=True, silent=True) or {}
    try:
        split_qty = int(body.get("qty") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "qty must be a whole number"}), 400
    db = get_tailoring_db()
    item = db.execute("SELECT * FROM tailoring_suit_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        return jsonify({"error": "Item not found"}), 404
    if split_qty <= 0 or split_qty >= item["qty"]:
        return jsonify({"error": f"qty to split off must be between 1 and {item['qty'] - 1}"}), 400

    _split_off_unit(db, item, split_qty, item["stage"])
    db.execute(f"UPDATE tailoring_suit_orders SET updated_at = {IST_NOW} WHERE id = ?",
               (item["order_id"],))
    db.commit()
    row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (item["order_id"],)).fetchone()
    return jsonify(_order_payload(db, row))


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/suits/orders/<id>/stage
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders/<int:order_id>/stage", methods=["PATCH"])
@api_login_required
def update_order_stage(order_id):
    body = request.get_json(force=True, silent=True) or {}
    stage = (body.get("stage") or "").strip()
    if stage not in STAGES:
        return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
    db = get_tailoring_db()
    row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Order not found"}), 404
    db.execute("UPDATE tailoring_suit_items SET stage = ? WHERE order_id = ?", (stage, order_id))
    db.execute(f"UPDATE tailoring_suit_orders SET updated_at = {IST_NOW} WHERE id = ?", (order_id,))
    _sync_stage_stamps(db, order_id)
    db.commit()
    row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
    return jsonify(_order_payload(db, row))


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/suits/orders/<id>/payment
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders/<int:order_id>/payment", methods=["PATCH"])
@api_login_required
def update_payment(order_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_tailoring_db()
        row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
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
            f"""UPDATE tailoring_suit_orders
               SET advance = ?, balance = ?, payment_mode = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (advance, balance, payment_mode, order_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PATCH /api/tailoring/suits/orders/<id>/cloth-balance
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders/<int:order_id>/cloth-balance", methods=["PATCH"])
@api_login_required
def update_cloth_balance(order_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_tailoring_db()
        row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
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
            f"""UPDATE tailoring_suit_orders SET cloth_balance = ?, balance = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (cloth_balance, balance, order_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /api/tailoring/suits/orders/<id>/payments
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders/<int:order_id>/payments", methods=["POST"])
@api_login_required
def record_payment(order_id):
    try:
        body = request.get_json(force=True, silent=True) or {}
        db = get_tailoring_db()
        row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
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
            "INSERT INTO tailoring_suit_payments (order_id, amount, mode) VALUES (?, ?, ?)",
            (order_id, amount, mode),
        )
        db.execute(
            f"""UPDATE tailoring_suit_orders
               SET advance = ?, balance = ?, payment_mode = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (new_advance, round(final_total - new_advance, 2),
             mode or row["payment_mode"], order_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
        return jsonify(_order_payload(db, row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/tailoring/suits/payments/<id>
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/payments/<int:payment_id>", methods=["DELETE"])
@api_login_required
def delete_payment(payment_id):
    try:
        db = get_tailoring_db()
        p = db.execute("SELECT * FROM tailoring_suit_payments WHERE id = ?", (payment_id,)).fetchone()
        if not p:
            return jsonify({"error": "Payment not found"}), 404
        order = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?",
                           (p["order_id"],)).fetchone()

        db.execute("DELETE FROM tailoring_suit_payments WHERE id = ?", (payment_id,))
        final_total = _final_total(order["total"], order["cloth_balance"])
        new_advance = max(0.0, round(order["advance"] - p["amount"], 2))
        db.execute(
            f"""UPDATE tailoring_suit_orders
               SET advance = ?, balance = ?, updated_at = {IST_NOW}
               WHERE id = ?""",
            (new_advance, round(final_total - new_advance, 2), order["id"]),
        )
        db.commit()
        row = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order["id"],)).fetchone()
        return jsonify(_order_payload(db, row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/tailoring/suits/orders/<id>
# ---------------------------------------------------------------------------
@tailoring_suit_api_bp.route("/tailoring/suits/orders/<int:order_id>", methods=["DELETE"])
@api_login_required
def delete_order(order_id):
    db = get_tailoring_db()
    row = db.execute("SELECT id FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Order not found"}), 404
    photos = db.execute(
        "SELECT filename FROM tailoring_suit_photos WHERE order_id = ?", (order_id,)).fetchall()
    db.execute("DELETE FROM tailoring_suit_orders WHERE id = ?", (order_id,))
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
@tailoring_suit_api_bp.route("/tailoring/suits/orders/<int:order_id>/photos", methods=["POST"])
@api_login_required
def upload_photo(order_id):
    db = get_tailoring_db()
    row = db.execute("SELECT id FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
    if not row:
        return jsonify({"error": "Order not found"}), 404

    file = request.files.get("photo")
    if not file:
        return jsonify({"error": "No photo provided"}), 400

    item_id_raw = (request.form.get("item_id") or "").strip()
    item_id = None
    if item_id_raw:
        item = db.execute(
            "SELECT id FROM tailoring_suit_items WHERE id = ? AND order_id = ?",
            (item_id_raw, order_id),
        ).fetchone()
        if not item:
            return jsonify({"error": "Item does not belong to this order"}), 400
        item_id = item["id"]

    try:
        from PIL import Image, ImageOps
        img = Image.open(file.stream)
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((MAX_PHOTO_DIM, MAX_PHOTO_DIM))
    except Exception:
        return jsonify({"error": "File is not a valid image"}), 400

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=PHOTO_JPEG_QUALITY, optimize=True)
    filename = f"suitorder{order_id}-{uuid.uuid4().hex[:10]}.jpg"

    stored_on_r2 = r2_storage.is_configured() and r2_storage.upload_bytes(
        buf.getvalue(), filename)
    if not stored_on_r2:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
            f.write(buf.getvalue())

    db.execute(
        "INSERT INTO tailoring_suit_photos (order_id, item_id, filename) VALUES (?, ?, ?)",
        (order_id, item_id, filename),
    )
    db.commit()
    order = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (order_id,)).fetchone()
    return jsonify(_order_payload(db, order)), 201


@tailoring_suit_api_bp.route("/tailoring/suits/photos/<int:photo_id>", methods=["DELETE"])
@api_login_required
def delete_photo(photo_id):
    db = get_tailoring_db()
    photo = db.execute("SELECT * FROM tailoring_suit_photos WHERE id = ?", (photo_id,)).fetchone()
    if not photo:
        return jsonify({"error": "Photo not found"}), 404
    db.execute("DELETE FROM tailoring_suit_photos WHERE id = ?", (photo_id,))
    db.commit()
    try:
        os.remove(os.path.join(UPLOAD_DIR, photo["filename"]))
    except OSError:
        pass
    if r2_storage.is_configured():
        r2_storage.delete_object(photo["filename"])
    return jsonify({"success": True})


@tailoring_suit_api_bp.route("/tailoring/suits/photos/<int:photo_id>/item", methods=["PATCH"])
@api_login_required
def move_photo(photo_id):
    body = request.get_json(force=True, silent=True) or {}
    raw_item_id = body.get("item_id")
    db = get_tailoring_db()
    photo = db.execute("SELECT * FROM tailoring_suit_photos WHERE id = ?", (photo_id,)).fetchone()
    if not photo:
        return jsonify({"error": "Photo not found"}), 404

    item_id = None
    if raw_item_id not in (None, "", "null"):
        try:
            item_id = int(raw_item_id)
        except (TypeError, ValueError):
            return jsonify({"error": "item_id must be a number or null"}), 400
        item = db.execute(
            "SELECT 1 FROM tailoring_suit_items WHERE id = ? AND order_id = ?",
            (item_id, photo["order_id"]),
        ).fetchone()
        if not item:
            return jsonify({"error": "That item does not belong to this order"}), 400

    db.execute("UPDATE tailoring_suit_photos SET item_id = ? WHERE id = ?", (item_id, photo_id))
    db.commit()
    order = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (photo["order_id"],)).fetchone()
    return jsonify(_order_payload(db, order))


@tailoring_suit_api_bp.route("/tailoring/suits/photos/<int:photo_id>/stage", methods=["PATCH"])
@api_login_required
def set_photo_stage(photo_id):
    body = request.get_json(force=True, silent=True) or {}
    stage = (body.get("stage") or "").strip()
    if stage not in STAGES:
        return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
    db = get_tailoring_db()
    photo = db.execute("SELECT * FROM tailoring_suit_photos WHERE id = ?", (photo_id,)).fetchone()
    if not photo:
        return jsonify({"error": "Photo not found"}), 404
    if not photo["item_id"]:
        return jsonify({"error": "Assign this photo to a garment before setting its stage"}), 400
    item = db.execute("SELECT * FROM tailoring_suit_items WHERE id = ?", (photo["item_id"],)).fetchone()

    if stage != item["stage"]:
        if item["qty"] > 1:
            new_item_id = _split_off_unit(db, item, 1, stage)
            db.execute("UPDATE tailoring_suit_photos SET item_id = ? WHERE id = ?",
                       (new_item_id, photo_id))
        else:
            db.execute("UPDATE tailoring_suit_items SET stage = ? WHERE id = ?", (stage, item["id"]))
        db.execute(f"UPDATE tailoring_suit_orders SET updated_at = {IST_NOW} WHERE id = ?",
                   (item["order_id"],))
        _sync_stage_stamps(db, item["order_id"])
        db.commit()

    order = db.execute("SELECT * FROM tailoring_suit_orders WHERE id = ?", (item["order_id"],)).fetchone()
    return jsonify(_order_payload(db, order))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@tailoring_suit_pages_bp.route("/tailoring/suits")
@login_required
def suit_page():
    return render_template("tailoring_suits.html")


@tailoring_suit_pages_bp.route("/tailoring/suits/share/<book_no>/<int:order_number>")
def suit_receipt(book_no, order_number):
    """Public receipt page for a suit order — linked in the WhatsApp message."""
    db = get_tailoring_db()
    row = db.execute(
        "SELECT * FROM tailoring_suit_orders WHERE book_no = ? AND order_number = ?",
        (book_no, order_number),
    ).fetchone()
    if not row:
        return render_template("tailoring_receipt_not_found.html",
                               order_number=order_number), 404
    order = _order_payload(db, row)
    return render_template("tailoring_receipt.html", order=order)


# ---------------------------------------------------------------------------
# Merged into the general Tailoring daily report (routes/tailoring.py) —
# there is deliberately no separate Suits report page, per the shop's
# request for one combined overdue/tomorrow report.
# ---------------------------------------------------------------------------
def build_suit_report_entries(today, tomorrow_s):
    """Same entry shape as tailoring.py's _build_report_data(), tagged with
    book_no so the merged report can tell a suit order's number apart from a
    general order's — the two numbering sequences are independent."""
    db = get_tailoring_db()
    today_s = today.isoformat()

    orders = _order_payloads_bulk(
        db, db.execute("SELECT * FROM tailoring_suit_orders").fetchall())
    open_orders = [o for o in orders if o["stage"] != "Delivered"]

    def entry(o, mode):
        items = []
        for i in o["items"]:
            if i["stage"] == "Delivered":
                continue
            done_stages = ("Trial Ready", "Alteration", "Full Stitched") if mode == "trial" \
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
            "book_no": o["book_no"],
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

    overdue = [entry(o, "overdue") for o in open_orders if _is_overdue(o, today_s)]
    deliveries = [entry(o, "delivery") for o in open_orders
                  if o["delivery_date"] == tomorrow_s
                  and o["stage"] not in ("Full Stitched",)]
    trials = [entry(o, "trial") for o in open_orders if o["trial_date"] == tomorrow_s]

    return {"overdue": overdue, "deliveries": deliveries, "trials": trials}
