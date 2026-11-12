"""Measurements trial — routes.

Fully separate from the tailoring and suits systems: uses measurements.db via
db.measurements and its own upload folder. Registered only when
MEASUREMENTS_ENABLED is set (see app.py).

Customers are keyed on normalized mobile number. Each customer can hold any
number of saved measurements (one row per garment taken).
"""
import io
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, jsonify, render_template, request,
                   send_from_directory)

from db.measurements import IST_NOW, get_measurements_db
from services.auth import api_staff_or_admin_required, staff_or_admin_required
from services.measurement_fields import (DEFAULT_STATUS, GARMENTS, STATUSES,
                                         clean_values, piece_count)
from utils import normalize_mobile, validate_indian_mobile

measurements_api_bp = Blueprint("measurements_api", __name__)
measurements_pages_bp = Blueprint("measurements_pages", __name__)

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "measurements")
MAX_PHOTO_DIM = 1400
PHOTO_JPEG_QUALITY = 82

IST = timezone(timedelta(hours=5, minutes=30))
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _today_ist():
    return datetime.now(IST).date().isoformat()


def _clean_date(raw):
    """'' / None -> None, valid YYYY-MM-DD -> itself, anything else -> False."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if DATE_RE.fullmatch(raw):
        try:
            datetime.strptime(raw, "%Y-%m-%d")
            return raw
        except ValueError:
            pass
    return False


def _customer_dict(c):
    return {"id": c["id"], "mobile": c["mobile"], "name": c["name"],
            "address": c["address"] or ""}


def _load_values(raw):
    try:
        values = json.loads(raw or "{}")
    except ValueError:
        return {}
    return values if isinstance(values, dict) else {}


def _measurement_dict(m):
    values = _load_values(m["values_json"])
    garment = GARMENTS.get(m["garment_type"], {})
    return {
        "id": m["id"],
        "customer_id": m["customer_id"],
        "garment_type": m["garment_type"],
        "garment_label": garment.get("label", m["garment_type"].title()),
        "values": values,
        "notes": m["notes"] or "",
        "image_url": f"/measurements/photos/{m['image']}" if m["image"] else None,
        "order_date": m["order_date"],
        "trial_date": m["trial_date"],
        "delivery_date": m["delivery_date"],
        "status": m["status"],
        "created_at": m["created_at"],
    }


def _customer_payload(db, customer):
    rows = db.execute(
        "SELECT * FROM m_measurements WHERE customer_id = ? ORDER BY id DESC",
        (customer["id"],),
    ).fetchall()
    out = _customer_dict(customer)
    out["measurements"] = [_measurement_dict(r) for r in rows]
    return out


def _remove_photo_file(filename):
    if not filename:
        return
    path = os.path.join(os.path.abspath(UPLOAD_DIR), os.path.basename(filename))
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Meta / status
# ---------------------------------------------------------------------------
@measurements_api_bp.route("/measurements/status", methods=["GET"])
@api_staff_or_admin_required
def measurements_status():
    db = get_measurements_db()
    customers = db.execute("SELECT COUNT(*) FROM m_customers").fetchone()[0]
    measurements = db.execute("SELECT COUNT(*) FROM m_measurements").fetchone()[0]
    return jsonify({"customers": customers, "measurements": measurements})


@measurements_api_bp.route("/measurements/meta", methods=["GET"])
@api_staff_or_admin_required
def measurements_meta():
    return jsonify({
        "statuses": STATUSES,
        "garments": [{"type": t, "label": g["label"], "fields": g["fields"]}
                     for t, g in GARMENTS.items()],
        "today": _today_ist(),
    })


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
@measurements_api_bp.route("/measurements/customers", methods=["GET"])
@api_staff_or_admin_required
def list_customers():
    """Search by name or mobile; with no query, the most recently added."""
    q = (request.args.get("q") or "").strip()
    db = get_measurements_db()
    sql = ("SELECT c.*, (SELECT COUNT(*) FROM m_measurements m "
           "WHERE m.customer_id = c.id) AS n FROM m_customers c")
    params = []
    if q:
        digits = re.sub(r"\D", "", q)
        clauses = ["c.name LIKE ?"]
        params.append(f"%{q}%")
        if digits:
            clauses.append("c.mobile LIKE ?")
            params.append(f"%{digits}%")
        sql += " WHERE " + " OR ".join(clauses)
    sql += " ORDER BY c.id DESC LIMIT 50"
    rows = db.execute(sql, params).fetchall()
    return jsonify([dict(_customer_dict(r), measurement_count=r["n"]) for r in rows])


@measurements_api_bp.route("/measurements/customers", methods=["POST"])
@api_staff_or_admin_required
def create_customer():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    mobile = normalize_mobile(str(data.get("mobile") or ""))
    address = (data.get("address") or "").strip()
    if not name:
        return jsonify({"error": "Customer name is required"}), 400
    if not validate_indian_mobile(mobile):
        return jsonify({"error": "Enter a valid 10-digit mobile number"}), 400

    db = get_measurements_db()
    existing = db.execute("SELECT * FROM m_customers WHERE mobile = ?", (mobile,)).fetchone()
    if existing:
        return jsonify({"error": "A customer with this mobile already exists",
                        "customer": _customer_dict(existing)}), 409
    cur = db.execute(
        "INSERT INTO m_customers (mobile, name, address) VALUES (?, ?, ?)",
        (mobile, name, address or None),
    )
    db.commit()
    row = db.execute("SELECT * FROM m_customers WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(_customer_payload(db, row)), 201


@measurements_api_bp.route("/measurements/customers/<int:customer_id>", methods=["GET"])
@api_staff_or_admin_required
def get_customer(customer_id):
    db = get_measurements_db()
    row = db.execute("SELECT * FROM m_customers WHERE id = ?", (customer_id,)).fetchone()
    if not row:
        return jsonify({"error": "Customer not found"}), 404
    return jsonify(_customer_payload(db, row))


@measurements_api_bp.route("/measurements/customers/<int:customer_id>", methods=["PUT"])
@api_staff_or_admin_required
def update_customer(customer_id):
    db = get_measurements_db()
    row = db.execute("SELECT * FROM m_customers WHERE id = ?", (customer_id,)).fetchone()
    if not row:
        return jsonify({"error": "Customer not found"}), 404
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    mobile = normalize_mobile(str(data.get("mobile") or row["mobile"]))
    address = (data.get("address") or "").strip()
    if not name:
        return jsonify({"error": "Customer name is required"}), 400
    if not validate_indian_mobile(mobile):
        return jsonify({"error": "Enter a valid 10-digit mobile number"}), 400
    clash = db.execute("SELECT id FROM m_customers WHERE mobile = ? AND id != ?",
                       (mobile, customer_id)).fetchone()
    if clash:
        return jsonify({"error": "Another customer already uses this mobile"}), 409
    db.execute("UPDATE m_customers SET name = ?, mobile = ?, address = ? WHERE id = ?",
               (name, mobile, address or None, customer_id))
    db.commit()
    row = db.execute("SELECT * FROM m_customers WHERE id = ?", (customer_id,)).fetchone()
    return jsonify(_customer_payload(db, row))


@measurements_api_bp.route("/measurements/customers/<int:customer_id>", methods=["DELETE"])
@api_staff_or_admin_required
def delete_customer(customer_id):
    db = get_measurements_db()
    row = db.execute("SELECT id FROM m_customers WHERE id = ?", (customer_id,)).fetchone()
    if not row:
        return jsonify({"error": "Customer not found"}), 404
    images = [r["image"] for r in db.execute(
        "SELECT image FROM m_measurements WHERE customer_id = ?", (customer_id,))]
    db.execute("DELETE FROM m_customers WHERE id = ?", (customer_id,))
    db.commit()
    for img in images:
        _remove_photo_file(img)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------
def _parse_measurement_body(data, garment_type):
    """Validate the shared create/update fields. Returns (fields, error)."""
    values, err = clean_values(garment_type, data.get("values") or {})
    if err:
        return None, err
    dates = {}
    for key in ("order_date", "trial_date", "delivery_date"):
        d = _clean_date(data.get(key))
        if d is False:
            return None, f"Invalid {key.replace('_', ' ')}"
        dates[key] = d
    return {
        "values_json": json.dumps(values),
        "notes": (data.get("notes") or "").strip() or None,
        **dates,
    }, None


@measurements_api_bp.route("/measurements/customers/<int:customer_id>/measurements",
                           methods=["POST"])
@api_staff_or_admin_required
def create_measurement(customer_id):
    db = get_measurements_db()
    if not db.execute("SELECT 1 FROM m_customers WHERE id = ?", (customer_id,)).fetchone():
        return jsonify({"error": "Customer not found"}), 404
    data = request.get_json(silent=True) or {}
    garment_type = (data.get("garment_type") or "").strip().lower()
    if garment_type not in GARMENTS:
        return jsonify({"error": "Choose a garment"}), 400
    fields, err = _parse_measurement_body(data, garment_type)
    if err:
        return jsonify({"error": err}), 400
    order_date = fields["order_date"] or _today_ist()
    cur = db.execute(
        "INSERT INTO m_measurements (customer_id, garment_type, values_json, notes, "
        "order_date, trial_date, delivery_date, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (customer_id, garment_type, fields["values_json"], fields["notes"],
         order_date, fields["trial_date"], fields["delivery_date"], DEFAULT_STATUS),
    )
    db.commit()
    row = db.execute("SELECT * FROM m_measurements WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(_measurement_dict(row)), 201


@measurements_api_bp.route("/measurements/<int:measurement_id>", methods=["GET"])
@api_staff_or_admin_required
def get_measurement(measurement_id):
    db = get_measurements_db()
    row = db.execute("SELECT * FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    if not row:
        return jsonify({"error": "Measurement not found"}), 404
    return jsonify(_measurement_dict(row))


@measurements_api_bp.route("/measurements/<int:measurement_id>", methods=["PUT"])
@api_staff_or_admin_required
def update_measurement(measurement_id):
    db = get_measurements_db()
    row = db.execute("SELECT * FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    if not row:
        return jsonify({"error": "Measurement not found"}), 404
    data = request.get_json(silent=True) or {}
    # The garment type is fixed once taken; to change it, take a new measurement.
    fields, err = _parse_measurement_body(data, row["garment_type"])
    if err:
        return jsonify({"error": err}), 400
    db.execute(
        f"UPDATE m_measurements SET values_json = ?, notes = ?, order_date = ?, "
        f"trial_date = ?, delivery_date = ?, updated_at = ({IST_NOW}) WHERE id = ?",
        (fields["values_json"], fields["notes"], fields["order_date"] or row["order_date"],
         fields["trial_date"], fields["delivery_date"], measurement_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    return jsonify(_measurement_dict(row))


@measurements_api_bp.route("/measurements/<int:measurement_id>/status", methods=["PATCH"])
@api_staff_or_admin_required
def update_status(measurement_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in STATUSES:
        return jsonify({"error": "Invalid status"}), 400
    db = get_measurements_db()
    if not db.execute("SELECT 1 FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone():
        return jsonify({"error": "Measurement not found"}), 404
    db.execute(f"UPDATE m_measurements SET status = ?, updated_at = ({IST_NOW}) WHERE id = ?",
               (status, measurement_id))
    db.commit()
    row = db.execute("SELECT * FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    return jsonify(_measurement_dict(row))


@measurements_api_bp.route("/measurements/<int:measurement_id>", methods=["DELETE"])
@api_staff_or_admin_required
def delete_measurement(measurement_id):
    db = get_measurements_db()
    row = db.execute("SELECT image FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    if not row:
        return jsonify({"error": "Measurement not found"}), 404
    db.execute("DELETE FROM m_measurements WHERE id = ?", (measurement_id,))
    db.commit()
    _remove_photo_file(row["image"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Fabric photo (one per measurement; uploading again replaces it)
# ---------------------------------------------------------------------------
@measurements_api_bp.route("/measurements/<int:measurement_id>/photo", methods=["POST"])
@api_staff_or_admin_required
def upload_photo(measurement_id):
    db = get_measurements_db()
    row = db.execute("SELECT * FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    if not row:
        return jsonify({"error": "Measurement not found"}), 404
    file = request.files.get("photo")
    if not file:
        return jsonify({"error": "No photo provided"}), 400
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
    filename = f"m{measurement_id}-{uuid.uuid4().hex[:10]}.jpg"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
        f.write(buf.getvalue())

    old = row["image"]
    db.execute(f"UPDATE m_measurements SET image = ?, updated_at = ({IST_NOW}) WHERE id = ?",
               (filename, measurement_id))
    db.commit()
    _remove_photo_file(old)
    row = db.execute("SELECT * FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    return jsonify(_measurement_dict(row)), 201


@measurements_api_bp.route("/measurements/<int:measurement_id>/photo", methods=["DELETE"])
@api_staff_or_admin_required
def delete_photo(measurement_id):
    db = get_measurements_db()
    row = db.execute("SELECT image FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    if not row:
        return jsonify({"error": "Measurement not found"}), 404
    db.execute(f"UPDATE m_measurements SET image = NULL, updated_at = ({IST_NOW}) WHERE id = ?",
               (measurement_id,))
    db.commit()
    _remove_photo_file(row["image"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# GET /api/measurements/dashboard — delivery and trial preparation view
# ---------------------------------------------------------------------------
# "Open" = anything not yet Delivered. A trial counts as missed once its date
# has passed while the garment is still Measured / In Stitching (i.e. it never
# reached Trial Ready).
MISSED_TRIAL_STATUSES = ("Measured", "In Stitching")
DASHBOARD_DAYS = 15


def _brief(r):
    values = _load_values(r["values_json"])
    garment = GARMENTS.get(r["garment_type"], {})
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "customer_name": r["name"],
        "mobile": r["mobile"],
        "garment_type": r["garment_type"],
        "garment_label": garment.get("label", r["garment_type"].title()),
        "pieces": piece_count(r["garment_type"], values),
        "status": r["status"],
        "order_date": r["order_date"],
        "trial_date": r["trial_date"],
        "delivery_date": r["delivery_date"],
    }


def _garment_totals(briefs):
    totals = {}
    for b in briefs:
        totals[b["garment_label"]] = totals.get(b["garment_label"], 0) + b["pieces"]
    return totals


@measurements_api_bp.route("/measurements/dashboard", methods=["GET"])
@api_staff_or_admin_required
def measurements_dashboard():
    db = get_measurements_db()
    today = datetime.now(IST).date()
    today_s = today.isoformat()
    tomorrow_s = (today + timedelta(days=1)).isoformat()

    counts = {s: 0 for s in STATUSES}
    for r in db.execute("SELECT status, COUNT(*) AS n FROM m_measurements GROUP BY status"):
        counts[r["status"]] = r["n"]

    rows = db.execute(
        "SELECT m.*, c.name, c.mobile FROM m_measurements m "
        "JOIN m_customers c ON c.id = m.customer_id WHERE m.status != 'Delivered'"
    ).fetchall()
    open_items = sorted((_brief(r) for r in rows), key=lambda b: b["customer_name"].lower())

    days = []
    for n in range(DASHBOARD_DAYS):
        ds = (today + timedelta(days=n)).isoformat()
        deliveries = [b for b in open_items if b["delivery_date"] == ds]
        trials = [b for b in open_items if b["trial_date"] == ds]
        days.append({
            "date": ds,
            "deliveries": len(deliveries),
            "trials": len(trials),
            "garments": _garment_totals(deliveries),
            "delivery_list": deliveries,
            "trial_list": trials,
        })

    overdue = sorted((b for b in open_items
                      if b["delivery_date"] and b["delivery_date"] < today_s),
                     key=lambda b: b["delivery_date"])
    for b in overdue:
        b["days_late"] = (today - datetime.strptime(b["delivery_date"], "%Y-%m-%d").date()).days

    missed_trials = sorted((b for b in open_items
                            if b["trial_date"] and b["trial_date"] < today_s
                            and b["status"] in MISSED_TRIAL_STATUSES),
                           key=lambda b: b["trial_date"])

    def due_on(field, ds):
        return [b for b in open_items if b[field] == ds]

    return jsonify({
        "today": today_s,
        "counts": counts,
        "total": sum(counts.values()),
        "open": len(open_items),
        "days": days,
        "overdue": overdue,
        "overdue_garments": _garment_totals(overdue),
        "missed_trials": missed_trials,
        "deliveries_today": due_on("delivery_date", today_s),
        "deliveries_tomorrow": due_on("delivery_date", tomorrow_s),
        "trials_today": due_on("trial_date", today_s),
        "trials_tomorrow": due_on("trial_date", tomorrow_s),
    })


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@measurements_pages_bp.route("/measurements")
@staff_or_admin_required
def measurements_page():
    return render_template("measurements.html")


@measurements_pages_bp.route("/measurements/<int:measurement_id>/print")
@staff_or_admin_required
def measurement_print(measurement_id):
    db = get_measurements_db()
    row = db.execute("SELECT * FROM m_measurements WHERE id = ?", (measurement_id,)).fetchone()
    if not row:
        return "Measurement not found", 404
    customer = db.execute("SELECT * FROM m_customers WHERE id = ?",
                          (row["customer_id"],)).fetchone()
    garment = GARMENTS.get(row["garment_type"], {"label": row["garment_type"].title(),
                                                 "fields": []})
    m = _measurement_dict(row)
    # Split the saved values into the slip's three groups, in form order.
    inch, labels, count = [], [], None
    front, back = [], []
    for f in garment["fields"]:
        v = m["values"].get(f["key"])
        if not v:
            continue
        if f["kind"] == "count":
            count = (f["label"], v)
        elif f["kind"] == "select":
            labels.append((f["label"], v))
        elif f["key"].startswith("front_") and f["key"][6:].isdigit():
            front.append(v)
        elif f["key"].startswith("back_") and f["key"][5:].isdigit():
            back.append(v)
        else:
            inch.append((f["label"], v))
    return render_template("measurements_print.html", m=m, customer=customer,
                           garment_label=garment["label"], count=count, inch=inch,
                           labels=labels, front=front, back=back)


@measurements_pages_bp.route("/measurements/photos/<path:filename>")
@staff_or_admin_required
def measurement_photo_file(filename):
    folder = os.path.abspath(UPLOAD_DIR)
    filename = os.path.basename(filename)
    if not os.path.isfile(os.path.join(folder, filename)):
        return jsonify({"error": "Photo not found"}), 404
    return send_from_directory(folder, filename, max_age=31536000)
