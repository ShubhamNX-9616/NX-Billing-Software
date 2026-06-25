import re
from datetime import date
from flask import Blueprint, jsonify, request
from db import get_db, generate_inst_bill_number
from auth import api_login_required, api_admin_required
from utils import r2

inst_bills_bp = Blueprint("institution_bills", __name__)

VALID_INST_PAYMENT_MODES = {"Cash", "Card", "UPI", "Cheque", "NEFT", "Combination"}


@inst_bills_bp.route("/institution-bills", methods=["POST"])
@api_login_required
def create_institution_bill():
    body = request.get_json(force=True) or {}

    company_name          = (body.get("company_name")          or "").strip()
    company_address       = (body.get("company_address")       or "").strip()
    contact_person_name   = (body.get("contact_person_name")   or "").strip()
    contact_person_mobile = (body.get("contact_person_mobile") or "").strip()
    bill_date             = (body.get("bill_date")             or "").strip()
    salesperson_name      = (body.get("salesperson_name")      or "").strip()
    payment_mode_type     = (body.get("payment_mode_type")     or "").strip()
    items                 = body.get("items", [])
    payments              = body.get("payments", [])
    advance_paid          = r2(float(body.get("advance_paid") or 0))

    errors = []
    if not company_name: errors.append("company_name is required")
    if not bill_date:    errors.append("bill_date is required")
    if not salesperson_name:      errors.append("salesperson_name is required")
    if not items:                 errors.append("At least one item is required")
    if payment_mode_type and payment_mode_type not in VALID_INST_PAYMENT_MODES:
        errors.append("Invalid payment_mode_type")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    db = get_db()

    calc_items = []
    subtotal = 0.0
    for item in items:
        qty_per_pc       = r2(float(item.get("quantity_per_pc")    or 0))
        rate_per_m       = r2(float(item.get("rate_per_m")         or 0))
        no_of_pcs        = int(item.get("no_of_pcs")               or 0)
        stitching_per_unit = r2(float(item.get("stitching_per_unit") or 0))
        total            = r2((qty_per_pc * rate_per_m * no_of_pcs) + (no_of_pcs * stitching_per_unit))
        subtotal        += total
        calc_items.append({
            "cloth_type":        (item.get("cloth_type")    or "").strip(),
            "company_name":      (item.get("company_name")  or "").strip(),
            "quality_number":    (item.get("quality_number") or "").strip(),
            "quantity_per_pc":   qty_per_pc,
            "rate_per_m":        rate_per_m,
            "no_of_pcs":         no_of_pcs,
            "stitching_per_unit": stitching_per_unit,
            "total":             total,
        })

    subtotal    = r2(subtotal)
    final_total = subtotal
    remaining   = r2(max(0, final_total - advance_paid))
    stored_mode = payment_mode_type or "Pending"

    bill_number = generate_inst_bill_number(db)

    cursor = db.execute(
        """
        INSERT INTO institution_bills (
            bill_number, company_name, company_address, contact_person_name, contact_person_mobile,
            bill_date, subtotal, final_total, advance_paid, remaining,
            salesperson_name, payment_mode_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+5 hours', '+30 minutes'))
        """,
        (bill_number, company_name, company_address, contact_person_name, contact_person_mobile,
         bill_date, subtotal, final_total, advance_paid, remaining,
         salesperson_name, stored_mode),
    )
    bill_id = cursor.lastrowid

    db.executemany(
        """
        INSERT INTO institution_bill_items
            (bill_id, cloth_type, company_name, quality_number,
             quantity_per_pc, rate_per_m, no_of_pcs, stitching_per_unit, total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(bill_id, i["cloth_type"], i["company_name"], i["quality_number"],
          i["quantity_per_pc"], i["rate_per_m"], i["no_of_pcs"], i["stitching_per_unit"], i["total"])
         for i in calc_items],
    )

    if payments:
        db.executemany(
            "INSERT INTO institution_bill_payments (bill_id, payment_method, amount) VALUES (?, ?, ?)",
            [(bill_id, p["payment_method"], float(p["amount"])) for p in payments],
        )

    db.commit()

    return jsonify({
        "id":                   bill_id,
        "bill_number":          bill_number,
        "company_name":         company_name,
        "contact_person_name":  contact_person_name,
        "contact_person_mobile": contact_person_mobile,
        "bill_date":            bill_date,
        "salesperson_name":     salesperson_name,
        "subtotal":             subtotal,
        "final_total":          final_total,
        "advance_paid":         advance_paid,
        "remaining":            remaining,
        "payment_mode_type":    stored_mode,
        "items":                calc_items,
        "payments":             [{"payment_method": p["payment_method"], "amount": float(p["amount"])} for p in payments],
    }), 201


@inst_bills_bp.route("/institution-bills", methods=["GET"])
@api_login_required
def list_institution_bills():
    db = get_db()
    rows = db.execute("""
        SELECT ib.*, COUNT(ibi.id) AS item_count
        FROM institution_bills ib
        LEFT JOIN institution_bill_items ibi ON ibi.bill_id = ib.id
        GROUP BY ib.id
        ORDER BY ib.id DESC
    """).fetchall()
    return jsonify([dict(r) for r in rows])


@inst_bills_bp.route("/institution-bills/search", methods=["GET"])
@api_login_required
def search_institution_bills():
    bill_number = (request.args.get("billNumber") or "").strip()
    company     = (request.args.get("name")        or "").strip()
    contact     = (request.args.get("mobile")      or "").strip()

    db = get_db()
    conditions, params = [], []
    if bill_number:
        conditions.append("ib.bill_number LIKE ?")
        params.append(f"%{bill_number}%")
    if company:
        conditions.append("ib.company_name LIKE ?")
        params.append(f"%{company}%")
    if contact:
        conditions.append("ib.contact_person_name LIKE ?")
        params.append(f"%{contact}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = db.execute(f"""
        SELECT ib.*, COUNT(ibi.id) AS item_count
        FROM institution_bills ib
        LEFT JOIN institution_bill_items ibi ON ibi.bill_id = ib.id
        {where}
        GROUP BY ib.id
        ORDER BY ib.id DESC
    """, params).fetchall()
    return jsonify([dict(r) for r in rows])


@inst_bills_bp.route("/institution-bills/<int:bill_id>", methods=["GET"])
@api_login_required
def get_institution_bill(bill_id):
    db = get_db()
    bill = db.execute(
        "SELECT * FROM institution_bills WHERE id = ?", (bill_id,)
    ).fetchone()
    if not bill:
        return jsonify({"error": "Not found"}), 404

    items = db.execute(
        "SELECT * FROM institution_bill_items WHERE bill_id = ? ORDER BY id", (bill_id,)
    ).fetchall()

    payments = db.execute(
        "SELECT payment_method, amount FROM institution_bill_payments WHERE bill_id = ? ORDER BY id",
        (bill_id,),
    ).fetchall()

    return jsonify({
        "bill":     dict(bill),
        "items":    [dict(i) for i in items],
        "payments": [dict(p) for p in payments],
    })


# ---------------------------------------------------------------------------
# PUT /api/institution-bills/<id>  — update bill
# ---------------------------------------------------------------------------
@inst_bills_bp.route("/institution-bills/<int:bill_id>", methods=["PUT"])
@api_login_required
def update_institution_bill(bill_id):
    db = get_db()
    existing = db.execute("SELECT id, status FROM institution_bills WHERE id = ?", (bill_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Bill not found"}), 404
    if existing["status"] == "cancelled":
        return jsonify({"error": "Cannot edit a cancelled bill"}), 400

    body = request.get_json(force=True) or {}
    company_name          = (body.get("company_name")          or "").strip()
    company_address       = (body.get("company_address")       or "").strip()
    contact_person_name   = (body.get("contact_person_name")   or "").strip()
    contact_person_mobile = (body.get("contact_person_mobile") or "").strip()
    bill_date             = (body.get("bill_date")             or "").strip()
    salesperson_name      = (body.get("salesperson_name")      or "").strip()
    payment_mode_type     = (body.get("payment_mode_type")     or "").strip()
    items                 = body.get("items", [])
    payments              = body.get("payments", [])
    advance_paid          = r2(float(body.get("advance_paid") or 0))

    errors = []
    if not company_name:   errors.append("company_name is required")
    if not bill_date:      errors.append("bill_date is required")
    if not salesperson_name: errors.append("salesperson_name is required")
    if not items:          errors.append("At least one item is required")
    if payment_mode_type and payment_mode_type not in VALID_INST_PAYMENT_MODES:
        errors.append("Invalid payment_mode_type")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    calc_items = []
    subtotal = 0.0
    for item in items:
        qty_per_pc         = r2(float(item.get("quantity_per_pc")    or 0))
        rate_per_m         = r2(float(item.get("rate_per_m")         or 0))
        no_of_pcs          = int(item.get("no_of_pcs")               or 0)
        stitching_per_unit = r2(float(item.get("stitching_per_unit") or 0))
        total              = r2((qty_per_pc * rate_per_m * no_of_pcs) + (no_of_pcs * stitching_per_unit))
        subtotal          += total
        calc_items.append({
            "cloth_type":        (item.get("cloth_type")    or "").strip(),
            "company_name":      (item.get("company_name")  or "").strip(),
            "quality_number":    (item.get("quality_number") or "").strip(),
            "quantity_per_pc":   qty_per_pc,
            "rate_per_m":        rate_per_m,
            "no_of_pcs":         no_of_pcs,
            "stitching_per_unit": stitching_per_unit,
            "total":             total,
        })

    subtotal    = r2(subtotal)
    final_total = subtotal
    remaining   = r2(max(0, final_total - advance_paid))
    stored_mode = payment_mode_type or "Pending"

    try:
        db.execute(
            """
            UPDATE institution_bills SET
                company_name = ?, company_address = ?, contact_person_name = ?, contact_person_mobile = ?,
                bill_date = ?, salesperson_name = ?, subtotal = ?, final_total = ?,
                advance_paid = ?, remaining = ?, payment_mode_type = ?,
                updated_at = datetime('now', '+5 hours', '+30 minutes')
            WHERE id = ?
            """,
            (company_name, company_address, contact_person_name, contact_person_mobile,
             bill_date, salesperson_name, subtotal, final_total,
             advance_paid, remaining, stored_mode, bill_id),
        )
        db.execute("DELETE FROM institution_bill_items    WHERE bill_id = ?", (bill_id,))
        db.execute("DELETE FROM institution_bill_payments WHERE bill_id = ?", (bill_id,))

        db.executemany(
            """INSERT INTO institution_bill_items
               (bill_id, cloth_type, company_name, quality_number,
                quantity_per_pc, rate_per_m, no_of_pcs, stitching_per_unit, total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(bill_id, i["cloth_type"], i["company_name"], i["quality_number"],
              i["quantity_per_pc"], i["rate_per_m"], i["no_of_pcs"], i["stitching_per_unit"], i["total"])
             for i in calc_items],
        )
        if payments:
            db.executemany(
                "INSERT INTO institution_bill_payments (bill_id, payment_method, amount) VALUES (?, ?, ?)",
                [(bill_id, p["payment_method"], float(p["amount"])) for p in payments],
            )
        db.commit()
    except Exception as e:
        try: db.rollback()
        except Exception: pass
        return jsonify({"error": str(e)}), 500

    bill = db.execute("SELECT * FROM institution_bills WHERE id = ?", (bill_id,)).fetchone()
    return jsonify({
        "id":          bill_id,
        "bill_number": bill["bill_number"],
        "final_total": final_total,
        "advance_paid": advance_paid,
        "remaining":   remaining,
        "items":       calc_items,
        "payments":    [{"payment_method": p["payment_method"], "amount": float(p["amount"])} for p in payments],
    }), 200


# ---------------------------------------------------------------------------
# PUT /api/institution-bills/<id>/cancel
# ---------------------------------------------------------------------------
@inst_bills_bp.route("/institution-bills/<int:bill_id>/cancel", methods=["PUT"])
@api_login_required
def cancel_institution_bill(bill_id):
    try:
        db = get_db()
        bill = db.execute("SELECT id, status FROM institution_bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            return jsonify({"error": "Bill not found"}), 404
        if bill["status"] == "cancelled":
            return jsonify({"error": "Bill is already cancelled"}), 400
        db.execute(
            "UPDATE institution_bills SET status = 'cancelled', updated_at = datetime('now', '+5 hours', '+30 minutes') WHERE id = ?",
            (bill_id,),
        )
        db.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        try: db.rollback()
        except Exception: pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/institution-bills/<id>/restore
# ---------------------------------------------------------------------------
@inst_bills_bp.route("/institution-bills/<int:bill_id>/restore", methods=["PUT"])
@api_admin_required
def restore_institution_bill(bill_id):
    try:
        db = get_db()
        bill = db.execute("SELECT id, status FROM institution_bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            return jsonify({"error": "Bill not found"}), 404
        if bill["status"] != "cancelled":
            return jsonify({"error": "Bill is not cancelled"}), 400
        db.execute(
            "UPDATE institution_bills SET status = 'active', updated_at = datetime('now', '+5 hours', '+30 minutes') WHERE id = ?",
            (bill_id,),
        )
        db.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        try: db.rollback()
        except Exception: pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/institution-bills/<id>  — hard delete + renumber
# ---------------------------------------------------------------------------
@inst_bills_bp.route("/institution-bills/<int:bill_id>", methods=["DELETE"])
@api_admin_required
def delete_institution_bill(bill_id):
    try:
        db = get_db()
        bill = db.execute("SELECT bill_number FROM institution_bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            return jsonify({"error": "Bill not found"}), 404

        bill_number = bill["bill_number"]
        m = re.match(r'^INST-(\d+)/(.+)$', bill_number)
        if not m:
            return jsonify({"error": "Unexpected bill_number format"}), 500
        deleted_num = int(m.group(1))
        bill_fy     = m.group(2)

        db.execute("DELETE FROM institution_bill_items    WHERE bill_id = ?", (bill_id,))
        db.execute("DELETE FROM institution_bill_payments WHERE bill_id = ?", (bill_id,))
        db.execute("DELETE FROM institution_bills         WHERE id = ?",      (bill_id,))

        higher_bills = db.execute(
            """
            SELECT id, bill_number FROM institution_bills
            WHERE bill_number LIKE ?
              AND CAST(SUBSTR(bill_number, 6) AS INTEGER) > ?
            ORDER BY CAST(SUBSTR(bill_number, 6) AS INTEGER) ASC
            """,
            (f"INST-%/{bill_fy}", deleted_num),
        ).fetchall()
        for b in higher_bills:
            bm = re.match(r'^INST-(\d+)/(.+)$', b["bill_number"])
            if bm:
                db.execute(
                    "UPDATE institution_bills SET bill_number = ? WHERE id = ?",
                    (f"INST-{int(bm.group(1)) - 1:04d}/{bm.group(2)}", b["id"]),
                )

        fy_now = _inst_current_fy()
        db.execute(
            "UPDATE inst_bill_number_seq SET next_val = "
            "(SELECT COALESCE(MAX(CAST(SUBSTR(bill_number, 6) AS INTEGER)), 0) "
            "FROM institution_bills WHERE bill_number LIKE ?) "
            "WHERE id = 1",
            (f"INST-%/{fy_now}",),
        )
        db.commit()
        return jsonify({"success": True, "message": "Institution bill deleted and renumbered"}), 200
    except Exception as e:
        try: db.rollback()
        except Exception: pass
        return jsonify({"error": str(e)}), 500


def _inst_current_fy():
    today = date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{str(start)[2:]}-{str(start + 1)[2:]}"
