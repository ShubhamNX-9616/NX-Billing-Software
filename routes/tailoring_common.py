"""Everything Tailoring and Suits have in common.

Two order books live in tailoring.db with the same shape: the general Tailoring Delivery
System and the Suits book (routes/tailoring.py and routes/tailoring_suits.py). They used to
be two copies of ~1,000 lines each, so every fix had to be made twice. The shared logic now
lives here once, in OrderBook; each module only supplies its configuration (table names,
URL prefix, whether orders carry a book number, ...) and whatever is truly its own.
"""
import io
import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import jsonify, request

from db.connection import begin_write, get_db
from db.tailoring import GARMENT_TYPES, IST_NOW, STAGES, get_tailoring_db
from services import r2_storage
from services.auth import api_login_required
from services.customer_lookup import customer_index
from services.errors import server_error
from utils import clean_iso_date, finite_float, money_float, normalize_mobile

MAX_PHOTO_DIM = 1400          # px, longest side after resize
PHOTO_JPEG_QUALITY = 82
IST = timezone(timedelta(hours=5, minutes=30))
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
_LIST_ROW_FIELDS = ("id", "order_number", "customer_name", "mobile", "trial_date",
                    "delivery_date", "stage", "balance", "cloth_balance")
# Historical orders backfilled from the old Drive measurement archive (see
# scripts/import_drive_measurements.py). They're all closed/delivered and only ever
# relevant to a measurement lookup, never to the live prep board - excluded from the
# unfiltered browse/count views so those don't pay to load and build a full payload
# (items+photos+payments) for ~1000 dead rows on every request. A search query (q)
# still reaches them, since that's exactly when someone wants an old measurement.
# Only the general Tailoring book has them (OrderBook.exclude_archive).
ARCHIVE_EXCLUDE_SQL = "(notes IS NULL OR notes NOT LIKE 'Imported from Drive archive%')"


# ----------------------------------------------------------------------
# Pure helpers (no database)
# ----------------------------------------------------------------------

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
        rate = finite_float(it.get("rate") or 0, "Rate")
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


def _parse_book_no(body):
    """Which physical order book this entry was written in - required, since order
    numbers only avoid clashing within the same book (suits only)."""
    raw = str(body.get("book_no") or "").strip()
    if not raw:
        raise ValueError("Book number is required")
    return raw


def _parse_order_number(body):
    """The order number is typed from the paper receipt book — required."""
    raw = str(body.get("order_number") or "").strip()
    if not raw:
        raise ValueError("Order number is required (copy it from the receipt book)")
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError("Order number must be a positive number")
    return int(raw)


# ----------------------------------------------------------------------
# One order book
# ----------------------------------------------------------------------

class OrderBook:
    """One order book: its tables, its URLs, and the few behaviours that differ.

    key             short name ("tailoring" / "suits")
    prefix          URL prefix of its API routes (under /api), e.g. "/tailoring/suits"
    orders / items / photos / payments / rates
                    the five tables of this book in tailoring.db
    upload_dir      callable returning the photo folder (a callable so tests can repoint it)
    photo_prefix    start of uploaded photo file names ("order" / "suitorder"), so the two
                    books can share one folder without ever colliding
    has_book_no     orders are identified by (book_no, order_number): a physical suit order
                    book is replaced over time and its numbering restarts, which one
                    globally-unique order_number could never allow. False: order_number alone.
    exclude_archive hide the one-off import of old Drive measurements from the live board
    slim_list       the orders list sends trimmed rows + a photo count instead of full orders
    """

    def __init__(self, *, key, prefix, orders, items, photos, payments, rates, upload_dir,
                 photo_prefix, has_book_no=False, exclude_archive=False, slim_list=False):
        self.key = key
        self.prefix = prefix
        self.orders, self.items, self.photos = orders, items, photos
        self.payments, self.rates = payments, rates
        self.upload_dir = upload_dir
        self.photo_prefix = photo_prefix
        self.has_book_no = has_book_no
        self.exclude_archive = exclude_archive
        self.slim_list = slim_list

    # ---- order numbers --------------------------------------------------

    def _number_exists(self, db, order_number, book_no):
        if self.has_book_no:
            return db.execute(
                f"SELECT 1 FROM {self.orders} WHERE book_no = ? AND order_number = ?",
                (book_no, order_number)).fetchone() is not None
        return db.execute(f"SELECT 1 FROM {self.orders} WHERE order_number = ?",
                          (order_number,)).fetchone() is not None

    def _number_taken_message(self, order_number, book_no):
        if self.has_book_no:
            return f"Order number {order_number} already exists in Book {book_no}"
        return f"Order number {order_number} already exists"


    # ---- database helpers ----------------------------------------------

    def _split_off_unit(self, db, item, qty, stage):
        """Peel `qty` units off `item` into a new row with the given stage.
        Returns the new row's id. Caller commits."""
        remaining_qty = item["qty"] - qty
        remaining_amount = round(remaining_qty * item["rate"], 2)
        split_amount = round(qty * item["rate"], 2)
        db.execute(f"UPDATE {self.items} SET qty = ?, amount = ? WHERE id = ?",
                   (remaining_qty, remaining_amount, item["id"]))
        cur = db.execute(
            f"""INSERT INTO {self.items}
               (order_id, garment_type, qty, rate, amount, stage, stitched_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["order_id"], item["garment_type"], qty, item["rate"],
             split_amount, stage, item["stitched_at"], item["notes"]),
        )
        return cur.lastrowid

    def _sync_stage_stamps(self, db, order_id):
        """Keep each garment's stitched_at and the order's delivered_at in step
        with the item stages. Caller commits.

        stitched_at is per garment: stamped the first time that piece reads Full
        Stitched, cleared if it is sent back for alteration. The weekly report
        counts the pieces finished in a week, so an order-level date would be
        wrong — it would push a shirt finished on Monday into whatever week its
        slowest sibling is done. 'Delivered' counts as past Full Stitched, so a
        garment handed over without pausing there still counts as stitched.

        delivered_at stays on the order: the hand-over is one event for the whole
        order, stamped once every garment reads Delivered and cleared if any is
        rolled back."""
        db.execute(
            f"""UPDATE {self.items} SET stitched_at = COALESCE(stitched_at, {IST_NOW})
               WHERE order_id = ? AND stage IN ('Full Stitched', 'Delivered')""",
            (order_id,))
        db.execute(
            f"""UPDATE {self.items} SET stitched_at = NULL
               WHERE order_id = ? AND stage NOT IN ('Full Stitched', 'Delivered')""",
            (order_id,))
        stages = [r["stage"] for r in db.execute(
            f"SELECT stage FROM {self.items} WHERE order_id = ?", (order_id,)).fetchall()]
        if stages and all(s == "Delivered" for s in stages):
            db.execute(
                f"""UPDATE {self.orders}
                   SET delivered_at = COALESCE(delivered_at, {IST_NOW}) WHERE id = ?""",
                (order_id,))
        else:
            db.execute(f"UPDATE {self.orders} SET delivered_at = NULL WHERE id = ?",
                       (order_id,))

    def order_payload(self, db, order_row):
        order = dict(order_row)
        items = [dict(r) for r in db.execute(
            f"SELECT * FROM {self.items} WHERE order_id = ? ORDER BY id", (order["id"],)
        ).fetchall()]
        photos = [dict(r) for r in db.execute(
            f"SELECT * FROM {self.photos} WHERE order_id = ? ORDER BY id", (order["id"],)
        ).fetchall()]
        for it in items:
            it["photos"] = [p for p in photos if p["item_id"] == it["id"]]
        order["items"] = items
        order["photos"] = photos          # all photos (incl. per-item ones)
        order["general_photos"] = [p for p in photos if not p["item_id"]]
        order["stage"] = _derived_stage([i["stage"] for i in items])
        order["final_total"] = _final_total(order["total"], order["cloth_balance"])
        payments = [dict(r) for r in db.execute(
            f"SELECT * FROM {self.payments} WHERE order_id = ? ORDER BY id", (order["id"],)
        ).fetchall()]
        order["payments"] = payments
        # Orders from before payment history existed (or edited via the old
        # set-total endpoint) may have paid more than the recorded entries.
        order["unrecorded_paid"] = round(
            order["advance"] - sum(p["amount"] for p in payments), 2)
        return order

    def order_payloads_bulk(self, db, order_rows, with_photos=True):
        """Same shape as [order_payload(db, r) for r in order_rows], but fetches
        items/photos/payments for every order in 3 queries total instead of 3
        per order — the list/dashboard/report endpoints were doing 1+3N queries
        for N orders, which dominates load time once N is more than a handful."""
        order_rows = list(order_rows)
        if not order_rows:
            return []
        ids = [r["id"] for r in order_rows]
        placeholders = ",".join("?" * len(ids))

        items_by_order, photos_by_order, payments_by_order = {}, {}, {}
        for r in db.execute(
            f"SELECT * FROM {self.items} WHERE order_id IN ({placeholders}) ORDER BY id", ids
        ).fetchall():
            items_by_order.setdefault(r["order_id"], []).append(dict(r))
        if with_photos:  # callers that only need counts/summaries skip this query
            for r in db.execute(
                f"SELECT * FROM {self.photos} WHERE order_id IN ({placeholders}) ORDER BY id", ids
            ).fetchall():
                photos_by_order.setdefault(r["order_id"], []).append(dict(r))
        for r in db.execute(
            f"SELECT * FROM {self.payments} WHERE order_id IN ({placeholders}) ORDER BY id", ids
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

    def _remember_garment_rates(self, db, items):
        """Save each item's rate as that garment's new default, so the next order
        auto-fills the current stitching price instead of the operator retyping
        it. A blank/zero rate is not remembered, so leaving the field empty can
        never wipe out an already-saved default."""
        for it in items:
            if it["rate"] > 0:
                db.execute(
                    f"""INSERT INTO {self.rates} (garment_type, rate, updated_at)
                       VALUES (?, ?, {IST_NOW})
                       ON CONFLICT(garment_type) DO UPDATE
                       SET rate = excluded.rate, updated_at = excluded.updated_at""",
                    (it["garment_type"], it["rate"]),
                )

    def _customer_index(self, db):
        """Name/mobile/address per customer, derived from orders.

        Unlike /tailoring/customers this reads the orders table directly instead
        of building full order payloads, so it is cheap enough to call on every
        keystroke of the order form's customer lookup. Mobiles are stored raw, so
        they are normalized here to make '+91 98765 43210' and '9876543210' match.
        Rows ascend by order_number, so the most recent spelling and address win.
        Billing customers and suit-order customers are included too (see
        services/customer_lookup.py), so someone saved there autofills here.
        """
        return customer_index(db, get_db(), f"{self.orders}")

    def _order_brief(self, order):
        """Compact order summary for dashboard lists (no photos)."""
        brief = {
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
        if self.has_book_no:
            brief["book_no"] = order["book_no"]
        return brief

    # ---- request handlers ----------------------------------------------

    def meta(self):
        db = get_tailoring_db()
        rates = {r["garment_type"]: r["rate"] for r in
                  db.execute(f"SELECT garment_type, rate FROM {self.rates}").fetchall()}
        payload = {"stages": STAGES, "garment_types": GARMENT_TYPES, "garment_rates": rates}
        if self.has_book_no:
            # Sticky Book No default: whichever book the most recently created order used,
            # so a shop working through one book does not retype it every time.
            last = db.execute(
                f"SELECT book_no FROM {self.orders} ORDER BY id DESC LIMIT 1").fetchone()
            payload["last_book_no"] = last["book_no"] if last else ""
        return jsonify(payload)

    def create_order(self):
        try:
            body = request.get_json(force=True, silent=True) or {}

            customer_name = (body.get("customer_name") or "").strip()
            if not customer_name:
                return jsonify({"error": "Customer name is required"}), 400

            try:
                items = _parse_items(body)
                order_number = _parse_order_number(body)
                book_no = _parse_book_no(body) if self.has_book_no else None
            except ValueError as ve:
                return jsonify({"error": str(ve)}), 400

            mobile        = (body.get("mobile") or "").strip() or None
            address       = (body.get("address") or "").strip() or None
            order_date    = clean_iso_date(body.get("order_date"), "Order date") or _today_ist()
            trial_date    = clean_iso_date(body.get("trial_date"), "Trial date")
            delivery_date = clean_iso_date(body.get("delivery_date"), "Delivery date")
            payment_mode  = (body.get("payment_mode") or "").strip() or None
            notes         = (body.get("notes") or "").strip() or None
            advance       = money_float(body.get("advance") or 0, "Advance")
            if advance < 0:
                return jsonify({"error": "Advance cannot be negative"}), 400
            cloth_balance = money_float(body.get("cloth_balance") or 0, "Cloth balance")
            if cloth_balance < 0:
                return jsonify({"error": "Cloth balance cannot be negative"}), 400

            total = round(sum(i["amount"] for i in items), 2)
            final_total = _final_total(total, cloth_balance)
            if advance > final_total:
                return jsonify({"error": "Advance cannot exceed the total"}), 400
            balance = round(final_total - advance, 2)

            db = get_tailoring_db()
            if self._number_exists(db, order_number, book_no):
                return jsonify({"error": self._number_taken_message(order_number, book_no)}), 400
            columns = ["order_number", "order_date", "customer_name", "mobile", "address",
                       "trial_date", "delivery_date", "total", "advance", "balance",
                       "payment_mode", "cloth_balance", "notes"]
            values = [order_number, order_date, customer_name, mobile, address,
                      trial_date, delivery_date, total, advance, balance,
                      payment_mode, cloth_balance, notes]
            if self.has_book_no:
                columns.insert(0, "book_no")
                values.insert(0, book_no)
            try:
                cur = db.execute(
                    f"INSERT INTO {self.orders} ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' * len(columns))})", values)
            except sqlite3.IntegrityError:
                # Two devices saved the same number in the same instant — the
                # SELECT above missed it, but the UNIQUE constraint catches it.
                return jsonify({"error": self._number_taken_message(order_number, book_no)}), 400
            order_id = cur.lastrowid
            for it in items:
                db.execute(
                    f"""INSERT INTO {self.items}
                       (order_id, garment_type, qty, rate, amount, stage, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (order_id, it["garment_type"], it["qty"], it["rate"],
                     it["amount"], it["stage"], it["notes"]),
                )
            self._remember_garment_rates(db, items)
            if advance > 0:
                db.execute(
                    f"INSERT INTO {self.payments} (order_id, amount, mode, note) "
                    "VALUES (?, ?, ?, 'Advance')",
                    (order_id, advance, payment_mode),
                )
            self._sync_stage_stamps(db, order_id)   # items may be created already Delivered
            db.commit()

            order = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
            return jsonify(self.order_payload(db, order)), 201

        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return server_error(e)

    def list_orders(self):
        db = get_tailoring_db()
        q     = (request.args.get("q") or "").strip()
        stage = (request.args.get("stage") or "").strip()
        due   = (request.args.get("due") or "").strip()
        pay   = (request.args.get("pay") or "").strip()
        sort = (request.args.get("sort") or "").strip()
        if sort not in SORTS:
            sort = DEFAULT_SORT

        # The board (no search) and the badge counts read the same rows, so build
        # that payload once; only a search needs a second, wider query. Photos
        # aren't loaded: a list row shows only how many there are (photo_count).
        live_sql = f"SELECT * FROM {self.orders}"
        if self.exclude_archive:
            live_sql += f" WHERE {ARCHIVE_EXCLUDE_SQL}"
        with_photos = not self.slim_list
        all_orders = self.order_payloads_bulk(db, db.execute(live_sql).fetchall(),
                                               with_photos=with_photos)

        sql = f"SELECT * FROM {self.orders}"
        where, params = [], []
        if q:
            q_digits = q.replace(" ", "")
            if q_digits.isdigit():
                # A digits-only query is either the start of an order number or
                # the start of a mobile number, never both: order numbers count
                # up from 1 while real Indian mobiles always start 6-9, so
                # prefix-matching both (instead of the old "contains anywhere")
                # finds the right one without also pulling in unrelated orders
                # whose mobile just happens to contain the same digits somewhere
                # in the middle.
                # (a suits order is also found by the start of its book number)
                fields = ["CAST(order_number AS TEXT) LIKE ?", "norm_mobile(mobile) LIKE ?"]
                if self.has_book_no:
                    fields.append("book_no LIKE ?")
                where.append("(" + " OR ".join(fields) + ")")
                params += [f"{q_digits}%"] * len(fields)
            else:
                where.append("customer_name LIKE ?")
                params.append(f"%{q}%")
        elif self.exclude_archive:
            where.append(ARCHIVE_EXCLUDE_SQL)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY order_number DESC"

        if q:
            orders = self.order_payloads_bulk(db, db.execute(sql, params).fetchall(),
                                               with_photos=with_photos)
        else:
            orders = list(all_orders)

        if stage:
            orders = [o for o in orders if o["stage"] == stage]

        today = _today_ist()
        if due == "trial-today":
            orders = [o for o in orders if o["trial_date"] == today and o["stage"] != "Delivered"]
        elif due == "delivery-today":
            orders = [o for o in orders if o["delivery_date"] == today and o["stage"] != "Delivered"]
        elif due == "overdue":
            orders = [o for o in orders if _is_overdue(o, today)]

        if pay == "due":
            orders = [o for o in orders if o["balance"] > 0]
        elif pay == "paid":
            orders = [o for o in orders if o["balance"] <= 0]

        key, reverse = SORTS[sort]
        orders.sort(key=key, reverse=reverse)

        if self.slim_list:
            # Rows only need what the list draws (the detail modal fetches the full
            # order by id), so send a trimmed shape instead of every column.
            photo_counts = dict(db.execute(
                f"SELECT order_id, COUNT(*) FROM {self.photos} GROUP BY order_id").fetchall())
            orders = [
                {**{k: o[k] for k in _LIST_ROW_FIELDS},
                 "items": [{"garment_type": i["garment_type"], "qty": i["qty"], "stage": i["stage"]}
                           for i in o["items"]],
                 "photo_count": photo_counts.get(o["id"], 0)}
                for o in orders
            ]

        # Dashboard counts (computed over all orders, ignoring the filters) —
        # these badges describe the live board, so the archive stays excluded
        # here even while q is searching it.
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

    def dashboard(self):
        db = get_tailoring_db()
        today = _ist_date()
        today_s = today.isoformat()
        tomorrow_s = (today + timedelta(days=1)).isoformat()

        # _order_brief never shows photos, so don't load them.
        live_sql = f"SELECT * FROM {self.orders}"
        if self.exclude_archive:
            live_sql += f" WHERE {ARCHIVE_EXCLUDE_SQL}"
        orders = self.order_payloads_bulk(db, db.execute(live_sql).fetchall(), with_photos=False)
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
                "order_list": [self._order_brief(o) for o in due],
            })

        overdue_orders = [o for o in open_orders if _is_overdue(o, today_s)]
        overdue = sorted((self._order_brief(o) for o in overdue_orders),
                         key=lambda b: b["delivery_date"])
        for b in overdue:
            b["days_late"] = (today - date.fromisoformat(b["delivery_date"])).days

        # Same shape as a `days` entry, so the dashboard can show everything already
        # past its delivery date as one more card at the head of the day strip.
        # "trials" here means trial dates that have come and gone while the order is
        # still being stitched — the missed-trial counterpart of a day's booked ones.
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

        # Fully stitched, delivery date arrived/passed (or never set) — the
        # customer needs a reminder call to come and collect.
        ready_waiting = sorted(
            (self._order_brief(o) for o in open_orders
             if o["stage"] == "Full Stitched"
             and (not o["delivery_date"] or o["delivery_date"] <= today_s)),
            key=lambda b: b["delivery_date"] or "",
        )
        for b in ready_waiting:
            if b["delivery_date"] and b["delivery_date"] < today_s:
                b["days_waiting"] = (today - date.fromisoformat(b["delivery_date"])).days

        def due_on(field, ds):
            return [self._order_brief(o) for o in open_orders if o[field] == ds]

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

    def customer_search(self):
        raw = (request.args.get("mobile") or "").strip()
        if not raw:
            return jsonify({"error": "mobile param required"}), 400
        norm = normalize_mobile(raw)
        if len(norm) != 10:
            return jsonify({"found": False})
        customer = self._customer_index(get_tailoring_db()).get(norm)
        if not customer:
            return jsonify({"found": False})
        return jsonify({"found": True, "customer": customer})

    def customer_suggest(self):
        q = (request.args.get("q") or "").strip().lower()
        if len(q) < 2:
            return jsonify([])
        matches = [c for c in self._customer_index(get_tailoring_db()).values()
                   if q in (c["customer_name"] or "").lower()]
        matches.sort(key=lambda c: (c["customer_name"] or "").lower())
        return jsonify(matches[:8])

    def customers(self):
        """Tailoring has no customers table; group orders by mobile number
        (falling back to the name when no mobile was recorded). Mobiles are
        normalized so the same person entered as '+91 98765 43210' and
        '9876543210' groups into one customer, matching _customer_index()."""
        db = get_tailoring_db()
        q = (request.args.get("q") or "").strip().lower()

        orders = self.order_payloads_bulk(db, db.execute(
            f"SELECT * FROM {self.orders} ORDER BY order_number").fetchall())

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

    def get_order(self, order_id):
        db = get_tailoring_db()
        row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return jsonify({"error": "Order not found"}), 404
        return jsonify(self.order_payload(db, row))

    def update_order(self, order_id):
        try:
            body = request.get_json(force=True, silent=True) or {}
            db = get_tailoring_db()
            begin_write(db)
            existing = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
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
                book_no = None
                if self.has_book_no:
                    book_no = (_parse_book_no(body) if "book_no" in body else existing["book_no"])
            except ValueError as ve:
                return jsonify({"error": str(ve)}), 400

            moved = order_number != existing["order_number"] or (
                self.has_book_no and book_no != existing["book_no"])
            if moved and self._number_exists(db, order_number, book_no):
                return jsonify({"error": self._number_taken_message(order_number, book_no)}), 400

            mobile        = (body.get("mobile") or "").strip() or None
            address       = (body.get("address") or "").strip() or None
            order_date    = clean_iso_date(body.get("order_date"), "Order date") or existing["order_date"]
            trial_date    = clean_iso_date(body.get("trial_date"), "Trial date")
            delivery_date = clean_iso_date(body.get("delivery_date"), "Delivery date")
            payment_mode  = (body.get("payment_mode") or "").strip() or None
            notes         = (body.get("notes") or "").strip() or None
            advance       = money_float(body.get("advance") or 0, "Advance")
            if advance < 0:
                return jsonify({"error": "Advance cannot be negative"}), 400
            cloth_balance = money_float(body.get("cloth_balance") or 0, "Cloth balance")
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
                f"SELECT id FROM {self.items} WHERE order_id = ?", (order_id,)).fetchall()}
            sent_ids = set()
            for it in items:
                iid = it.get("id")
                if iid and int(iid) in old_ids:
                    iid = int(iid)
                    sent_ids.add(iid)
                    db.execute(
                        f"""UPDATE {self.items}
                           SET garment_type = ?, qty = ?, rate = ?, amount = ?, notes = ?
                           WHERE id = ? AND order_id = ?""",
                        (it["garment_type"], it["qty"], it["rate"], it["amount"],
                         it["notes"], iid, order_id),
                    )
                else:
                    db.execute(
                        f"""INSERT INTO {self.items}
                           (order_id, garment_type, qty, rate, amount, stage, notes)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (order_id, it["garment_type"], it["qty"], it["rate"],
                         it["amount"], it["stage"], it["notes"]),
                    )
            for gone in old_ids - sent_ids:
                db.execute(f"DELETE FROM {self.items} WHERE id = ?", (gone,))
            self._remember_garment_rates(db, items)

            book_sql = "book_no = ?, " if self.has_book_no else ""
            params = [book_no] if self.has_book_no else []
            params += [order_number, customer_name, mobile, address, order_date, trial_date,
                       delivery_date, total, advance, balance, payment_mode, cloth_balance,
                       notes, order_id]
            try:
                db.execute(
                    f"""UPDATE {self.orders}
                       SET {book_sql}order_number = ?, customer_name = ?, mobile = ?, address = ?,
                           order_date = ?, trial_date = ?, delivery_date = ?, total = ?,
                           advance = ?, balance = ?, payment_mode = ?, cloth_balance = ?, notes = ?,
                           updated_at = {IST_NOW}
                       WHERE id = ?""", params)
            except sqlite3.IntegrityError:
                # Another save took this number in the instant between our check and write.
                return jsonify({"error": self._number_taken_message(order_number, book_no)}), 400
            # Item rows were reconciled above — deleting the last pending garment
            # can make the order fully delivered (or a new one can un-deliver it).
            self._sync_stage_stamps(db, order_id)
            db.commit()
            row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
            return jsonify(self.order_payload(db, row))

        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return server_error(e)

    def update_item_stage(self, item_id):
        body = request.get_json(force=True, silent=True) or {}
        stage = (body.get("stage") or "").strip()
        if stage not in STAGES:
            return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
        db = get_tailoring_db()
        item = db.execute(f"SELECT * FROM {self.items} WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return jsonify({"error": "Item not found"}), 404
        db.execute(f"UPDATE {self.items} SET stage = ? WHERE id = ?", (stage, item_id))
        db.execute(f"UPDATE {self.orders} SET updated_at = {IST_NOW} WHERE id = ?",
                   (item["order_id"],))
        self._sync_stage_stamps(db, item["order_id"])
        db.commit()
        row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (item["order_id"],)).fetchone()
        return jsonify(self.order_payload(db, row))

    def split_item(self, item_id):
        body = request.get_json(force=True, silent=True) or {}
        try:
            split_qty = int(body.get("qty") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "qty must be a whole number"}), 400
        db = get_tailoring_db()
        item = db.execute(f"SELECT * FROM {self.items} WHERE id = ?", (item_id,)).fetchone()
        if not item:
            return jsonify({"error": "Item not found"}), 404
        if split_qty <= 0 or split_qty >= item["qty"]:
            return jsonify({"error": f"qty to split off must be between 1 and {item['qty'] - 1}"}), 400

        self._split_off_unit(db, item, split_qty, item["stage"])
        db.execute(f"UPDATE {self.orders} SET updated_at = {IST_NOW} WHERE id = ?",
                   (item["order_id"],))
        db.commit()
        row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (item["order_id"],)).fetchone()
        return jsonify(self.order_payload(db, row))

    def update_order_stage(self, order_id):
        body = request.get_json(force=True, silent=True) or {}
        stage = (body.get("stage") or "").strip()
        if stage not in STAGES:
            return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
        db = get_tailoring_db()
        row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return jsonify({"error": "Order not found"}), 404
        db.execute(f"UPDATE {self.items} SET stage = ? WHERE order_id = ?", (stage, order_id))
        db.execute(f"UPDATE {self.orders} SET updated_at = {IST_NOW} WHERE id = ?", (order_id,))
        self._sync_stage_stamps(db, order_id)
        db.commit()
        row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
        return jsonify(self.order_payload(db, row))

    def update_payment(self, order_id):
        try:
            body = request.get_json(force=True, silent=True) or {}
            db = get_tailoring_db()
            begin_write(db)
            row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
            if not row:
                return jsonify({"error": "Order not found"}), 404

            advance = money_float(body.get("advance", row["advance"]), "Advance")
            payment_mode = (body.get("payment_mode") or row["payment_mode"] or "").strip() or None
            if advance < 0:
                return jsonify({"error": "Advance cannot be negative"}), 400
            final_total = _final_total(row["total"], row["cloth_balance"])
            if advance > final_total:
                return jsonify({"error": "Paid amount cannot exceed the total"}), 400
            balance = round(final_total - advance, 2)

            db.execute(
                f"""UPDATE {self.orders}
                   SET advance = ?, balance = ?, payment_mode = ?, updated_at = {IST_NOW}
                   WHERE id = ?""",
                (advance, balance, payment_mode, order_id),
            )
            db.commit()
            row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
            return jsonify(self.order_payload(db, row))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return server_error(e)

    def update_cloth_balance(self, order_id):
        try:
            body = request.get_json(force=True, silent=True) or {}
            db = get_tailoring_db()
            begin_write(db)
            row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
            if not row:
                return jsonify({"error": "Order not found"}), 404

            cloth_balance = money_float(body.get("cloth_balance") or 0, "Cloth balance")
            if cloth_balance < 0:
                return jsonify({"error": "Cloth balance cannot be negative"}), 400
            final_total = _final_total(row["total"], cloth_balance)
            if row["advance"] > final_total:
                return jsonify({"error":
                    f"Already recorded ₹{row['advance']:.2f} paid, which is more than "
                    f"the new total of ₹{final_total:.2f} — lower the advance first"}), 400
            balance = round(final_total - row["advance"], 2)

            db.execute(
                f"""UPDATE {self.orders} SET cloth_balance = ?, balance = ?, updated_at = {IST_NOW}
                   WHERE id = ?""",
                (cloth_balance, balance, order_id),
            )
            db.commit()
            row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
            return jsonify(self.order_payload(db, row))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return server_error(e)

    def record_payment(self, order_id):
        try:
            body = request.get_json(force=True, silent=True) or {}
            db = get_tailoring_db()
            begin_write(db)
            row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
            if not row:
                return jsonify({"error": "Order not found"}), 404

            try:
                amount = round(money_float(body.get("amount") or 0, "Amount"), 2)
            except (TypeError, ValueError):
                return jsonify({"error": "Amount must be a number"}), 400
            if amount <= 0:
                return jsonify({"error": "Amount must be greater than zero"}), 400
            mode = (body.get("mode") or "").strip() or None
            paid_at = clean_iso_date(body.get("paid_at"), "Payment date") or _today_ist()

            final_total = _final_total(row["total"], row["cloth_balance"])
            new_advance = round(row["advance"] + amount, 2)
            if new_advance > final_total:
                return jsonify({"error":
                    f"This would make total paid ₹{new_advance:.2f}, "
                    f"more than the order total ₹{final_total:.2f}"}), 400

            db.execute(
                f"INSERT INTO {self.payments} (order_id, amount, mode, paid_at) VALUES (?, ?, ?, ?)",
                (order_id, amount, mode, paid_at),
            )
            db.execute(
                f"""UPDATE {self.orders}
                   SET advance = ?, balance = ?, payment_mode = ?, updated_at = {IST_NOW}
                   WHERE id = ?""",
                (new_advance, round(final_total - new_advance, 2),
                 mode or row["payment_mode"], order_id),
            )
            db.commit()
            row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
            return jsonify(self.order_payload(db, row)), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return server_error(e)

    def delete_payment(self, payment_id):
        try:
            db = get_tailoring_db()
            begin_write(db)
            p = db.execute(f"SELECT * FROM {self.payments} WHERE id = ?", (payment_id,)).fetchone()
            if not p:
                return jsonify({"error": "Payment not found"}), 404
            order = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?",
                               (p["order_id"],)).fetchone()

            db.execute(f"DELETE FROM {self.payments} WHERE id = ?", (payment_id,))
            final_total = _final_total(order["total"], order["cloth_balance"])
            new_advance = max(0.0, round(order["advance"] - p["amount"], 2))
            db.execute(
                f"""UPDATE {self.orders}
                   SET advance = ?, balance = ?, updated_at = {IST_NOW}
                   WHERE id = ?""",
                (new_advance, round(final_total - new_advance, 2), order["id"]),
            )
            db.commit()
            row = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order["id"],)).fetchone()
            return jsonify(self.order_payload(db, row))
        except Exception as e:
            return server_error(e)

    def delete_order(self, order_id):
        db = get_tailoring_db()
        row = db.execute(f"SELECT id FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
        if not row:
            return jsonify({"error": "Order not found"}), 404
        photos = db.execute(
            f"SELECT filename FROM {self.photos} WHERE order_id = ?", (order_id,)).fetchall()
        db.execute(f"DELETE FROM {self.orders} WHERE id = ?", (order_id,))
        db.commit()
        for p in photos:
            try:
                os.remove(os.path.join(self.upload_dir(), p["filename"]))
            except OSError:
                pass
            if r2_storage.is_configured():
                r2_storage.delete_object(p["filename"])
        return jsonify({"success": True})

    def upload_photo(self, order_id):
        db = get_tailoring_db()
        row = db.execute(f"SELECT id FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
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
                f"SELECT id FROM {self.items} WHERE id = ? AND order_id = ?",
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
        filename = f"{self.photo_prefix}{order_id}-{uuid.uuid4().hex[:10]}.jpg"

        # Prefer Cloudflare R2 (keeps the server's disk quota free); fall back to
        # local disk if R2 isn't configured, or if the upload fails, so a photo
        # is never lost to a storage hiccup.
        stored_on_r2 = r2_storage.is_configured() and r2_storage.upload_bytes(
            buf.getvalue(), filename)
        if not stored_on_r2:
            os.makedirs(self.upload_dir(), exist_ok=True)
            with open(os.path.join(self.upload_dir(), filename), "wb") as f:
                f.write(buf.getvalue())

        db.execute(
            f"INSERT INTO {self.photos} (order_id, item_id, filename) VALUES (?, ?, ?)",
            (order_id, item_id, filename),
        )
        db.commit()
        order = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (order_id,)).fetchone()
        return jsonify(self.order_payload(db, order)), 201

    def delete_photo(self, photo_id):
        db = get_tailoring_db()
        photo = db.execute(f"SELECT * FROM {self.photos} WHERE id = ?", (photo_id,)).fetchone()
        if not photo:
            return jsonify({"error": "Photo not found"}), 404
        db.execute(f"DELETE FROM {self.photos} WHERE id = ?", (photo_id,))
        db.commit()
        try:
            os.remove(os.path.join(self.upload_dir(), photo["filename"]))
        except OSError:
            pass
        if r2_storage.is_configured():
            r2_storage.delete_object(photo["filename"])
        return jsonify({"success": True})

    def move_photo(self, photo_id):
        body = request.get_json(force=True, silent=True) or {}
        raw_item_id = body.get("item_id")
        db = get_tailoring_db()
        photo = db.execute(f"SELECT * FROM {self.photos} WHERE id = ?", (photo_id,)).fetchone()
        if not photo:
            return jsonify({"error": "Photo not found"}), 404

        item_id = None
        if raw_item_id not in (None, "", "null"):
            try:
                item_id = int(raw_item_id)
            except (TypeError, ValueError):
                return jsonify({"error": "item_id must be a number or null"}), 400
            item = db.execute(
                f"SELECT 1 FROM {self.items} WHERE id = ? AND order_id = ?",
                (item_id, photo["order_id"]),
            ).fetchone()
            if not item:
                return jsonify({"error": "That item does not belong to this order"}), 400

        db.execute(f"UPDATE {self.photos} SET item_id = ? WHERE id = ?", (item_id, photo_id))
        db.commit()
        order = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (photo["order_id"],)).fetchone()
        return jsonify(self.order_payload(db, order))

    def set_photo_stage(self, photo_id):
        body = request.get_json(force=True, silent=True) or {}
        stage = (body.get("stage") or "").strip()
        if stage not in STAGES:
            return jsonify({"error": f"stage must be one of: {', '.join(STAGES)}"}), 400
        db = get_tailoring_db()
        photo = db.execute(f"SELECT * FROM {self.photos} WHERE id = ?", (photo_id,)).fetchone()
        if not photo:
            return jsonify({"error": "Photo not found"}), 404
        if not photo["item_id"]:
            return jsonify({"error": "Assign this photo to a garment before setting its stage"}), 400
        item = db.execute(f"SELECT * FROM {self.items} WHERE id = ?", (photo["item_id"],)).fetchone()

        if stage != item["stage"]:
            if item["qty"] > 1:
                new_item_id = self._split_off_unit(db, item, 1, stage)
                db.execute(f"UPDATE {self.photos} SET item_id = ? WHERE id = ?",
                           (new_item_id, photo_id))
            else:
                db.execute(f"UPDATE {self.items} SET stage = ? WHERE id = ?", (stage, item["id"]))
            db.execute(f"UPDATE {self.orders} SET updated_at = {IST_NOW} WHERE id = ?",
                       (item["order_id"],))
            self._sync_stage_stamps(db, item["order_id"])
            db.commit()

        order = db.execute(f"SELECT * FROM {self.orders} WHERE id = ?", (item["order_id"],)).fetchone()
        return jsonify(self.order_payload(db, order))


    # ---- routes ---------------------------------------------------------
    #
    # (rule relative to the book's prefix, HTTP methods, handler method)
    ROUTES = [('/meta', ['GET'], 'meta'),
              ('/orders', ['POST'], 'create_order'),
              ('/orders', ['GET'], 'list_orders'),
              ('/dashboard', ['GET'], 'dashboard'),
              ('/customers/search', ['GET'], 'customer_search'),
              ('/customers/suggest', ['GET'], 'customer_suggest'),
              ('/customers', ['GET'], 'customers'),
              ('/orders/<int:order_id>', ['GET'], 'get_order'),
              ('/orders/<int:order_id>', ['PUT'], 'update_order'),
              ('/items/<int:item_id>/stage', ['PATCH'], 'update_item_stage'),
              ('/items/<int:item_id>/split', ['POST'], 'split_item'),
              ('/orders/<int:order_id>/stage', ['PATCH'], 'update_order_stage'),
              ('/orders/<int:order_id>/payment', ['PATCH'], 'update_payment'),
              ('/orders/<int:order_id>/cloth-balance', ['PATCH'], 'update_cloth_balance'),
              ('/orders/<int:order_id>/payments', ['POST'], 'record_payment'),
              ('/payments/<int:payment_id>', ['DELETE'], 'delete_payment'),
              ('/orders/<int:order_id>', ['DELETE'], 'delete_order'),
              ('/orders/<int:order_id>/photos', ['POST'], 'upload_photo'),
              ('/photos/<int:photo_id>', ['DELETE'], 'delete_photo'),
              ('/photos/<int:photo_id>/item', ['PATCH'], 'move_photo'),
              ('/photos/<int:photo_id>/stage', ['PATCH'], 'set_photo_stage')]

    def register_routes(self, bp):
        """Attach every API route of this book to the blueprint, under self.prefix.
        All of them need a signed-in user."""
        for suffix, methods, name in self.ROUTES:
            bp.add_url_rule(self.prefix + suffix, endpoint=name,
                            view_func=api_login_required(getattr(self, name)), methods=methods)
