"""Suits Tailoring — routes.

A second, independent order book living in the same tailoring.db as the general Tailoring
Delivery System (routes/tailoring.py), but with its own tables. An order here is
identified by (book_no, order_number) rather than order_number alone, because a physical
suit order book gets replaced over time and the new book's numbering can restart from
1 — something the general system's single globally-unique order_number could never allow.

Everything else (stages, split, photos, payments, dashboard, customers) is the same
behaviour as Tailoring and is shared with it in routes/tailoring_common.py (OrderBook);
this module only configures the Suits book and holds what is its own: the page, the public
receipt (its URL carries the book number) and the entries the combined daily report pulls in.
"""
import os
from datetime import date

from flask import Blueprint, render_template

from db.tailoring import get_tailoring_db
from routes.tailoring_common import OrderBook, _is_overdue
from services.auth import login_required

tailoring_suit_api_bp = Blueprint("tailoring_suit_api", __name__)
tailoring_suit_pages_bp = Blueprint("tailoring_suit_pages", __name__)

# Same physical folder (and R2 bucket) as the general system, and the photos
# are served by that system's existing /tailoring/photos/<filename> route —
# filenames are prefixed "suit" (photo_prefix below) so the two never collide.
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "tailoring")

BOOK = OrderBook(
    key="suits", prefix="/tailoring/suits",
    orders="tailoring_suit_orders", items="tailoring_suit_items", photos="tailoring_suit_photos",
    payments="tailoring_suit_payments", rates="tailoring_suit_garment_rates",
    upload_dir=lambda: UPLOAD_DIR,          # a callable so tests can repoint UPLOAD_DIR
    photo_prefix="suitorder",
    has_book_no=True,
)
BOOK.register_routes(tailoring_suit_api_bp)


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
    order = BOOK.order_payload(db, row)
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

    orders = BOOK.order_payloads_bulk(
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
    deliveries_today = [entry(o, "delivery") for o in open_orders
                        if o["delivery_date"] == today_s
                        and o["stage"] not in ("Full Stitched",)]
    deliveries = [entry(o, "delivery") for o in open_orders
                  if o["delivery_date"] == tomorrow_s
                  and o["stage"] not in ("Full Stitched",)]
    trials = [entry(o, "trial") for o in open_orders if o["trial_date"] == tomorrow_s]

    return {"overdue": overdue, "deliveries_today": deliveries_today,
            "deliveries": deliveries, "trials": trials}
