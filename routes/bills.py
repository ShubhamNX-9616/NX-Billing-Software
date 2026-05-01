import re
from flask import Blueprint, jsonify, request, session
from db import get_db, generate_bill_number
from db.connection import _current_fy
from auth import login_required, admin_required, staff_or_admin_required, api_login_required, api_admin_required
from utils import normalize_mobile, validate_indian_mobile, r2
from services.billing import (
    validate_and_calculate_items,
    calculate_bill_totals,
    validate_payments,
    parse_advance,
    find_or_create_customer,
)
from services.inventory import deduct_stock, restore_stock

bills_bp = Blueprint("bills", __name__)

VALID_PAYMENT_MODES = {"Cash", "Card", "UPI", "Combination"}


# ---------------------------------------------------------------------------
# GET /api/bills
# ---------------------------------------------------------------------------
@bills_bp.route("/bills", methods=["GET"])
@api_admin_required
def get_bills():
    try:
        search = request.args.get("search", "").strip()
        db = get_db()
        if search:
            like = f"%{search}%"
            rows = db.execute(
                """
                SELECT id, bill_number, customer_id, customer_name_snapshot,
                       customer_mobile_snapshot, bill_date,
                       subtotal, total_discount, final_total, total_savings,
                       payment_mode_type, salesperson_name, advance_paid, remaining,
                       status, created_at
                FROM bills
                WHERE bill_number LIKE ?
                   OR customer_name_snapshot LIKE ?
                   OR customer_mobile_snapshot LIKE ?
                ORDER BY created_at DESC
                """,
                (like, like, like),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT id, bill_number, customer_id, customer_name_snapshot,
                       customer_mobile_snapshot, bill_date,
                       subtotal, total_discount, final_total, total_savings,
                       payment_mode_type, salesperson_name, advance_paid, remaining,
                       status, created_at
                FROM bills
                ORDER BY created_at DESC
                """
            ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/bills/search
# ---------------------------------------------------------------------------
@bills_bp.route("/bills/search", methods=["GET"])
@api_admin_required
def search_bills():
    try:
        bill_number = request.args.get("billNumber", "").strip()
        mobile = request.args.get("mobile", "").strip()
        name = request.args.get("name", "").strip()

        db = get_db()
        conditions = []
        params = []

        if bill_number:
            conditions.append("bill_number LIKE ?")
            params.append(f"%{bill_number}%")
        if mobile:
            norm = normalize_mobile(mobile)
            conditions.append("customer_mobile_snapshot LIKE ?")
            params.append(f"%{norm}%")
        if name:
            conditions.append("customer_name_snapshot LIKE ?")
            params.append(f"%{name}%")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = db.execute(
            f"""
            SELECT id, bill_number, customer_name_snapshot,
                   customer_mobile_snapshot, bill_date,
                   subtotal, total_discount, final_total, total_savings,
                   payment_mode_type, salesperson_name, advance_paid, remaining,
                   status, created_at
            FROM bills
            {where}
            ORDER BY created_at DESC
            """,
            params,
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/bills/<id>
# ---------------------------------------------------------------------------
@bills_bp.route("/bills/<int:bill_id>", methods=["GET"])
@api_admin_required
def get_bill(bill_id):
    try:
        db = get_db()
        bill = db.execute(
            "SELECT * FROM bills WHERE id = ?", (bill_id,)
        ).fetchone()
        if not bill:
            return jsonify({"error": "Bill not found"}), 404

        items = db.execute(
            """
            SELECT cloth_type, company_name, quality_number,
                   quantity, unit_label, mrp, rate_after_disc,
                   discount_percent, discount_amount, line_total, final_amount,
                   inventory_item_id
            FROM bill_items
            WHERE bill_id = ?
            ORDER BY id
            """,
            (bill_id,),
        ).fetchall()
        payments = db.execute(
            "SELECT payment_method, amount FROM bill_payments WHERE bill_id = ? ORDER BY id",
            (bill_id,),
        ).fetchall()

        gross_final_total = r2(sum(float(i["final_amount"] or 0) for i in items))
        stored_round_off = float(bill["round_off"] or 0)
        if stored_round_off > 0:
            round_off = stored_round_off
        else:
            round_off = max(r2(gross_final_total - float(bill["final_total"] or 0)), 0.0)

        result = dict(bill)
        result["gross_final_total"] = gross_final_total
        result["round_off"] = round_off
        result["items"] = [dict(i) for i in items]
        result["payments"] = [dict(p) for p in payments]
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /api/bills
# ---------------------------------------------------------------------------
@bills_bp.route("/bills", methods=["POST"])
@api_login_required
def create_bill():
    db = None
    try:
        body = request.get_json(force=True, silent=True) or {}

        customer_name     = (body.get("customer_name")     or "").strip()
        customer_mobile   = (body.get("customer_mobile")   or "").strip()
        bill_date         = (body.get("bill_date")         or "").strip()
        payment_mode_type = (body.get("payment_mode_type") or "").strip()
        salesperson_name  = (body.get("salesperson_name")  or "").strip()
        items             = body.get("items",    [])
        payments          = body.get("payments", [])

        errors = []
        if not customer_name:    errors.append("customer_name is required")
        if not customer_mobile:  errors.append("customer_mobile is required")
        if not bill_date:        errors.append("bill_date is required")
        if not salesperson_name: errors.append("salesperson_name is required")
        if payment_mode_type not in VALID_PAYMENT_MODES:
            errors.append(f"payment_mode_type must be one of {sorted(VALID_PAYMENT_MODES)}")
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400

        norm_mobile = normalize_mobile(customer_mobile)
        if not validate_indian_mobile(norm_mobile):
            return jsonify({"error": "Invalid Indian mobile number"}), 400

        db = get_db()

        salesperson = db.execute(
            "SELECT name FROM salespersons WHERE lower(name) = lower(?)", (salesperson_name,)
        ).fetchone()
        if not salesperson:
            return jsonify({"error": "Invalid sales person"}), 400
        salesperson_name = salesperson["name"]

        calculated_items          = validate_and_calculate_items(db, items)
        totals                    = calculate_bill_totals(calculated_items, body.get("round_off"))
        validate_payments(payments, totals["final_total"])
        advance_paid, remaining   = parse_advance(body.get("advance_paid"), totals["final_total"])
        customer_id               = find_or_create_customer(db, customer_name, norm_mobile)
        bill_number               = generate_bill_number(db)

        # Attach inventory_item_id from raw request to calculated items
        for raw, calc in zip(items, calculated_items):
            inv_id = raw.get("inventory_item_id")
            calc["inventory_item_id"] = int(inv_id) if inv_id else None

        bill_cursor = db.execute(
            """
            INSERT INTO bills (
                bill_number, customer_id,
                customer_name_snapshot, customer_mobile_snapshot,
                bill_date, subtotal, total_discount, final_total,
                total_savings, advance_paid, remaining, salesperson_name, payment_mode_type,
                round_off
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bill_number, customer_id,
                customer_name, norm_mobile, bill_date,
                totals["subtotal"], totals["total_discount"], totals["final_total"],
                totals["total_savings"], advance_paid, remaining,
                salesperson_name, payment_mode_type,
                totals["round_off"],
            ),
        )
        bill_id = bill_cursor.lastrowid

        db.executemany(
            """
            INSERT INTO bill_items (
                bill_id, cloth_type, company_name, quality_number,
                quantity, unit_label, mrp, line_total,
                discount_percent, discount_amount, rate_after_disc, final_amount,
                inventory_item_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    bill_id,
                    i["cloth_type"], i["company_name"], i["quality_number"],
                    i["quantity"], i["unit_label"], i["mrp"], i["line_total"],
                    i["discount_percent"], i["discount_amount"], i["rate_after_disc"], i["final_amount"],
                    i["inventory_item_id"],
                )
                for i in calculated_items
            ],
        )
        db.executemany(
            "INSERT INTO bill_payments (bill_id, payment_method, amount) VALUES (?, ?, ?)",
            [(bill_id, p["payment_method"], float(p["amount"])) for p in payments],
        )

        # Deduct inventory stock for linked items (soft warn — never blocks)
        username = session.get("username")
        for i in calculated_items:
            if i["inventory_item_id"]:
                deduct_stock(db, i["inventory_item_id"], i["quantity"], bill_id, username)

        db.commit()

        return jsonify({
            "id":                       bill_id,
            "bill_number":              bill_number,
            "customer_id":              customer_id,
            "customer_name":            customer_name,
            "customer_mobile":          norm_mobile,
            "customer_name_snapshot":   customer_name,
            "customer_mobile_snapshot": norm_mobile,
            "bill_date":                bill_date,
            "subtotal":                 totals["subtotal"],
            "total_discount":           totals["total_discount"],
            "gross_final_total":        totals["gross_final_total"],
            "final_total":              totals["final_total"],
            "round_off":                totals["round_off"],
            "total_savings":            totals["total_savings"],
            "advance_paid":             advance_paid,
            "remaining":                remaining,
            "salesperson_name":         salesperson_name,
            "payment_mode_type":        payment_mode_type,
        }), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/bills/<id>
# ---------------------------------------------------------------------------
@bills_bp.route("/bills/<int:bill_id>", methods=["PUT"])
@api_admin_required
def update_bill(bill_id):
    db = None
    try:
        body = request.get_json(force=True, silent=True) or {}

        customer_name     = (body.get("customer_name")     or "").strip()
        customer_mobile   = (body.get("customer_mobile")   or "").strip()
        bill_date         = (body.get("bill_date")         or "").strip()
        payment_mode_type = (body.get("payment_mode_type") or "").strip()
        salesperson_name  = (body.get("salesperson_name")  or "").strip()
        items             = body.get("items",    [])
        payments          = body.get("payments", [])

        errors = []
        if not customer_name:    errors.append("customer_name is required")
        if not customer_mobile:  errors.append("customer_mobile is required")
        if not bill_date:        errors.append("bill_date is required")
        if not salesperson_name: errors.append("salesperson_name is required")
        if payment_mode_type not in VALID_PAYMENT_MODES:
            errors.append(f"payment_mode_type must be one of {sorted(VALID_PAYMENT_MODES)}")
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400

        norm_mobile = normalize_mobile(customer_mobile)
        if not validate_indian_mobile(norm_mobile):
            return jsonify({"error": "Invalid Indian mobile number"}), 400

        db = get_db()

        salesperson = db.execute(
            "SELECT name FROM salespersons WHERE lower(name) = lower(?)", (salesperson_name,)
        ).fetchone()
        if not salesperson:
            return jsonify({"error": "Invalid sales person"}), 400
        salesperson_name = salesperson["name"]

        existing_bill = db.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not existing_bill:
            return jsonify({"error": "Bill not found"}), 404

        calculated_items        = validate_and_calculate_items(db, items)
        totals                  = calculate_bill_totals(calculated_items, body.get("round_off"))
        validate_payments(payments, totals["final_total"])
        advance_paid, remaining = parse_advance(body.get("advance_paid"), totals["final_total"])
        customer_id             = find_or_create_customer(db, customer_name, norm_mobile)

        # Attach inventory_item_id from raw request to calculated items
        for raw, calc in zip(items, calculated_items):
            inv_id = raw.get("inventory_item_id")
            calc["inventory_item_id"] = int(inv_id) if inv_id else None

        # Restore stock for old linked items before deleting them
        username = session.get("username")
        old_items = db.execute(
            "SELECT inventory_item_id, quantity FROM bill_items WHERE bill_id = ? AND inventory_item_id IS NOT NULL",
            (bill_id,),
        ).fetchall()
        for old in old_items:
            restore_stock(db, old["inventory_item_id"], old["quantity"], bill_id, username)

        db.execute("DELETE FROM bill_items    WHERE bill_id = ?", (bill_id,))
        db.execute("DELETE FROM bill_payments WHERE bill_id = ?", (bill_id,))

        db.execute("""
            UPDATE bills SET
                customer_id              = ?,
                customer_name_snapshot   = ?,
                customer_mobile_snapshot = ?,
                bill_date                = ?,
                subtotal                 = ?,
                total_discount           = ?,
                final_total              = ?,
                total_savings            = ?,
                advance_paid             = ?,
                remaining                = ?,
                salesperson_name         = ?,
                payment_mode_type        = ?,
                round_off                = ?,
                updated_at               = datetime('now','localtime')
            WHERE id = ?
        """, (
            customer_id, customer_name, norm_mobile, bill_date,
            totals["subtotal"], totals["total_discount"], totals["final_total"],
            totals["total_savings"], advance_paid, remaining,
            salesperson_name, payment_mode_type,
            totals["round_off"],
            bill_id,
        ))

        db.executemany(
            """
            INSERT INTO bill_items (
                bill_id, cloth_type, company_name, quality_number,
                quantity, unit_label, mrp, line_total,
                discount_percent, discount_amount, rate_after_disc, final_amount,
                inventory_item_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    bill_id,
                    i["cloth_type"], i["company_name"], i["quality_number"],
                    i["quantity"], i["unit_label"], i["mrp"], i["line_total"],
                    i["discount_percent"], i["discount_amount"], i["rate_after_disc"], i["final_amount"],
                    i["inventory_item_id"],
                )
                for i in calculated_items
            ],
        )
        db.executemany(
            "INSERT INTO bill_payments (bill_id, payment_method, amount) VALUES (?, ?, ?)",
            [(bill_id, p["payment_method"], float(p["amount"])) for p in payments],
        )

        # Deduct inventory stock for newly linked items
        for i in calculated_items:
            if i["inventory_item_id"]:
                deduct_stock(db, i["inventory_item_id"], i["quantity"], bill_id, username)

        db.commit()

        return jsonify({
            "id":                       bill_id,
            "bill_number":              existing_bill["bill_number"],
            "customer_id":              customer_id,
            "customer_name_snapshot":   customer_name,
            "customer_mobile_snapshot": norm_mobile,
            "bill_date":                bill_date,
            "subtotal":                 totals["subtotal"],
            "total_discount":           totals["total_discount"],
            "gross_final_total":        totals["gross_final_total"],
            "final_total":              totals["final_total"],
            "round_off":                totals["round_off"],
            "total_savings":            totals["total_savings"],
            "advance_paid":             advance_paid,
            "remaining":                remaining,
            "salesperson_name":         salesperson_name,
            "payment_mode_type":        payment_mode_type,
        }), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/bills/<id>  — hard delete + renumber higher bills
# ---------------------------------------------------------------------------
@bills_bp.route("/bills/<int:bill_id>", methods=["DELETE"])
@api_admin_required
def delete_bill(bill_id):
    try:
        db = get_db()

        # 1. Check bill exists
        bill = db.execute(
            "SELECT bill_number FROM bills WHERE id = ?", (bill_id,)
        ).fetchone()
        if not bill:
            return jsonify({"error": "Bill not found"}), 404

        # 2–3. Parse the numeric part and FY.
        # Supports "SHN-0003/26-27" (new) and "SHN-0003" (old format).
        bill_number = bill["bill_number"]
        m = re.match(r'^SHN-(\d+)(?:/(.+))?$', bill_number)
        if not m:
            return jsonify({"error": "Unexpected bill_number format"}), 500
        deleted_num = int(m.group(1))
        bill_fy     = m.group(2)  # e.g. "26-27", or None for old-format bills

        # 4. Restore inventory stock for linked items before deleting
        inv_items = db.execute(
            "SELECT inventory_item_id, quantity FROM bill_items WHERE bill_id = ? AND inventory_item_id IS NOT NULL",
            (bill_id,),
        ).fetchall()
        for inv in inv_items:
            restore_stock(db, inv["inventory_item_id"], inv["quantity"], bill_id, session.get("username"))

        # 5. Delete items
        db.execute("DELETE FROM bill_items    WHERE bill_id = ?", (bill_id,))
        # 6. Delete payments
        db.execute("DELETE FROM bill_payments WHERE bill_id = ?", (bill_id,))
        # 7. Delete the bill itself
        db.execute("DELETE FROM bills WHERE id = ?", (bill_id,))

        # 8. Renumber bills in the same FY with a higher number than the deleted one
        if bill_fy:
            higher_bills = db.execute(
                """
                SELECT id, bill_number FROM bills
                WHERE bill_number LIKE ?
                  AND CAST(SUBSTR(bill_number, 5) AS INTEGER) > ?
                ORDER BY CAST(SUBSTR(bill_number, 5) AS INTEGER) ASC
                """,
                (f"SHN-%/{bill_fy}", deleted_num),
            ).fetchall()
            for b in higher_bills:
                bm = re.match(r'^SHN-(\d+)/(.+)$', b["bill_number"])
                if bm:
                    db.execute(
                        "UPDATE bills SET bill_number = ? WHERE id = ?",
                        (f"SHN-{int(bm.group(1)) - 1:04d}/{bm.group(2)}", b["id"]),
                    )
        else:
            higher_bills = db.execute(
                """
                SELECT id, bill_number FROM bills
                WHERE bill_number NOT LIKE '%/%'
                  AND CAST(SUBSTR(bill_number, 5) AS INTEGER) > ?
                ORDER BY CAST(SUBSTR(bill_number, 5) AS INTEGER) ASC
                """,
                (deleted_num,),
            ).fetchall()
            for b in higher_bills:
                bm = re.match(r'^SHN-(\d+)$', b["bill_number"])
                if bm:
                    db.execute(
                        "UPDATE bills SET bill_number = ? WHERE id = ?",
                        (f"SHN-{int(bm.group(1)) - 1:04d}", b["id"]),
                    )

        # 9. Sync seq next_val to the new max for the current FY
        fy = _current_fy()
        db.execute(
            "UPDATE bill_number_seq SET next_val = "
            "(SELECT COALESCE(MAX(CAST(SUBSTR(bill_number, 5) AS INTEGER)), 0) "
            "FROM bills WHERE bill_number LIKE ?) "
            "WHERE id = 1",
            (f"SHN-%/{fy}",),
        )

        db.commit()

        return jsonify({
            "success": True,
            "message": "Bill deleted and remaining bills renumbered",
        }), 200

    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/bills/<id>/cancel  — mark cancelled, restore inventory
# ---------------------------------------------------------------------------
@bills_bp.route("/bills/<int:bill_id>/cancel", methods=["PUT"])
@api_admin_required
def cancel_bill(bill_id):
    try:
        db = get_db()
        bill = db.execute("SELECT id, status FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            return jsonify({"error": "Bill not found"}), 404
        if bill["status"] == "cancelled":
            return jsonify({"error": "Bill is already cancelled"}), 400

        inv_items = db.execute(
            "SELECT inventory_item_id, quantity FROM bill_items "
            "WHERE bill_id = ? AND inventory_item_id IS NOT NULL",
            (bill_id,),
        ).fetchall()
        for inv in inv_items:
            restore_stock(db, inv["inventory_item_id"], inv["quantity"], bill_id, session.get("username"))

        db.execute(
            "UPDATE bills SET status = 'cancelled', updated_at = datetime('now','localtime') WHERE id = ?",
            (bill_id,),
        )
        db.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/bills/<id>/restore  — reactivate a cancelled bill, re-deduct inventory
# ---------------------------------------------------------------------------
@bills_bp.route("/bills/<int:bill_id>/restore", methods=["PUT"])
@api_admin_required
def restore_bill(bill_id):
    try:
        db = get_db()
        bill = db.execute("SELECT id, status FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            return jsonify({"error": "Bill not found"}), 404
        if bill["status"] != "cancelled":
            return jsonify({"error": "Bill is not cancelled"}), 400

        inv_items = db.execute(
            "SELECT inventory_item_id, quantity FROM bill_items "
            "WHERE bill_id = ? AND inventory_item_id IS NOT NULL",
            (bill_id,),
        ).fetchall()
        for inv in inv_items:
            deduct_stock(db, inv["inventory_item_id"], inv["quantity"], bill_id, session.get("username"))

        db.execute(
            "UPDATE bills SET status = 'active', updated_at = datetime('now','localtime') WHERE id = ?",
            (bill_id,),
        )
        db.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500

