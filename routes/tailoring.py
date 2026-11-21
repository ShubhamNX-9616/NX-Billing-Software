"""Tailoring Delivery System — routes.

Fully separate from the billing system: uses tailoring.db via db.tailoring, its own
upload folder, and its own page + share templates.

Orders, payments, photos, the dashboard and the customer lookups are shared with the
Suits book and live in routes/tailoring_common.py (OrderBook). This module configures the
general Tailoring book and holds what only it has: the printable daily and weekly reports
(the daily one also pulls in the Suits entries), the public receipt, photo serving and
the page.
"""
import hashlib
import hmac
import os
from datetime import date, timedelta

from flask import (Blueprint, current_app, jsonify, redirect, render_template, request,
                   send_from_directory)

from db.tailoring import STAGES, get_tailoring_db
# MAX_PHOTO_DIM / PHOTO_JPEG_QUALITY / _ist_date are imported here for other modules,
# scripts and tests that reach them through routes.tailoring.
from routes.tailoring_common import (ARCHIVE_EXCLUDE_SQL, MAX_PHOTO_DIM,  # noqa: F401
                                     PHOTO_JPEG_QUALITY, OrderBook, _is_overdue, _ist_date)
from routes.tailoring_suits import build_suit_report_entries
from services import r2_storage
from services.auth import login_required

tailoring_api_bp = Blueprint("tailoring_api", __name__)
tailoring_pages_bp = Blueprint("tailoring_pages", __name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "tailoring")

BOOK = OrderBook(
    key="tailoring", prefix="/tailoring",
    orders="tailoring_orders", items="tailoring_items", photos="tailoring_photos",
    payments="tailoring_payments", rates="tailoring_garment_rates",
    upload_dir=lambda: UPLOAD_DIR,          # a callable so tests can repoint UPLOAD_DIR
    photo_prefix="order",
    exclude_archive=True, slim_list=True,
)
BOOK.register_routes(tailoring_api_bp)


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

    orders = BOOK.order_payloads_bulk(
        db, db.execute(f"SELECT * FROM tailoring_orders WHERE {ARCHIVE_EXCLUDE_SQL}").fetchall())
    open_orders = [o for o in orders if o["stage"] != "Delivered"]

    def entry(o, mode):
        """mode 'trial': work needed until Trial Ready; else until Full Stitched."""
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
    trials = [entry(o, "trial") for o in open_orders
              if o["trial_date"] == tomorrow_s]

    # The shop wants one combined report, not a separate one for the Suits
    # book — fold its overdue/tomorrow work in here rather than as its own page.
    suit_data = build_suit_report_entries(today, tomorrow_s)
    overdue = sorted(overdue + suit_data["overdue"], key=lambda e: e["delivery_date"])
    deliveries_today = deliveries_today + suit_data["deliveries_today"]
    deliveries = deliveries + suit_data["deliveries"]
    trials = trials + suit_data["trials"]

    return {"overdue": overdue, "deliveries_today": deliveries_today, "deliveries": deliveries,
            "trials": trials, "today": today_s, "tomorrow": tomorrow_s}


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

    orders = BOOK.order_payloads_bulk(
        db, db.execute(f"SELECT * FROM tailoring_orders WHERE {ARCHIVE_EXCLUDE_SQL}").fetchall())

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

    # Garments whose own stitching finished during the week, tallied by type —
    # the week's output as counts, not another order listing. A piece counts in
    # the week it came off the machine even if the rest of its order is still
    # being sewn. Order numbers ride along so the tailor can trace a lot back to
    # its receipt; nothing else is shown.
    stitched_tally = {}
    stitched_orders = set()
    for o in sorted(orders, key=lambda o: o["order_number"]):
        for i in o["items"]:
            if not in_week(i["stitched_at"]):
                continue
            stitched_orders.add(o["order_number"])
            e = stitched_tally.setdefault(i["garment_type"], {"qty": 0, "orders": []})
            e["qty"] += i["qty"]
            if o["order_number"] not in e["orders"]:
                e["orders"].append(o["order_number"])
    stitched_garments = sorted(
        ({"garment_type": g, **v} for g, v in stitched_tally.items()),
        key=lambda g: (-g["qty"], g["garment_type"]))

    # Trials that fell in the week, and whether the garments got that far
    trials = sorted(
        (brief(o, done=o["stage"] in ("Trial Ready", "Alteration", "Full Stitched", "Delivered"))
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
        # Left to stitch — same rule as the dashboard day cards.
        pending_garments += sum(i["qty"] for i in o["items"]
                                if i["stage"] not in ("Full Stitched", "Delivered"))

    overdue = sorted(
        (brief(o, days_late=(today - date.fromisoformat(o["delivery_date"])).days)
         for o in open_orders if _is_overdue(o, today_s)),
        key=lambda e: e["delivery_date"])

    totals = {
        "orders_taken": len(taken),
        "garments_taken": sum(e["qty"] for e in taken),
        "garments_stitched": sum(g["qty"] for g in stitched_garments),
        "stitched_orders": len(stitched_orders),
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
        "stitched_garments": stitched_garments,
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
    # Filenames are random UUIDs and never rewritten, so browsers may cache
    # them for a year (also saves the redirect hop on repeat views).
    one_year = 31536000
    if os.path.isfile(os.path.join(os.path.abspath(UPLOAD_DIR), filename)):
        return send_from_directory(os.path.abspath(UPLOAD_DIR), filename, max_age=one_year)
    if r2_storage.is_configured():
        resp = redirect(r2_storage.public_url(filename))
        resp.headers["Cache-Control"] = f"public, max-age={one_year}"
        return resp
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
    order = BOOK.order_payload(db, row)
    return render_template("tailoring_receipt.html", order=order)
