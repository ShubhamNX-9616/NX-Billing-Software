import re
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from database import get_db, generate_bill_number

bills_bp = Blueprint("bills", __name__)

VALID_PAYMENT_MODES = {"Cash", "Card", "UPI", "Combination"}
VALID_PAYMENT_METHODS = {"Cash", "Card", "UPI"}


def normalize_mobile(raw):
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    return digits


# ---------------------------------------------------------------------------
# GET /api/bills
# ---------------------------------------------------------------------------
@bills_bp.route("/bills", methods=["GET"])
def get_bills():
    try:
        search = request.args.get("search", "").strip()
        db = get_db()
        if search:
            like = f"%{search}%"
            rows = db.execute(
                """
                SELECT id, bill_number, customer_name_snapshot,
                       customer_mobile_snapshot, bill_date,
                       subtotal, total_discount, final_total, total_savings,
                       payment_mode_type, advance_paid, remaining, created_at
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
                SELECT id, bill_number, customer_name_snapshot,
                       customer_mobile_snapshot, bill_date,
                       subtotal, total_discount, final_total, total_savings,
                       payment_mode_type, advance_paid, remaining, created_at
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
                   payment_mode_type, advance_paid, remaining, created_at
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
                   discount_percent, discount_amount, line_total, final_amount
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

        result = dict(bill)
        result["items"] = [dict(i) for i in items]
        result["payments"] = [dict(p) for p in payments]
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# POST /api/bills
# ---------------------------------------------------------------------------
@bills_bp.route("/bills", methods=["POST"])
def create_bill():
    try:
        body = request.get_json(force=True, silent=True) or {}

        # 1. Validate required top-level fields
        customer_name = (body.get("customer_name") or "").strip()
        customer_mobile = (body.get("customer_mobile") or "").strip()
        bill_date = (body.get("bill_date") or "").strip()
        payment_mode_type = (body.get("payment_mode_type") or "").strip()
        items = body.get("items", [])
        payments = body.get("payments", [])

        errors = []
        if not customer_name:
            errors.append("customer_name is required")
        if not customer_mobile:
            errors.append("customer_mobile is required")
        if not bill_date:
            errors.append("bill_date is required")
        if payment_mode_type not in VALID_PAYMENT_MODES:
            errors.append(f"payment_mode_type must be one of {sorted(VALID_PAYMENT_MODES)}")
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400

        # 2. Validate Indian mobile (10 digits after normalization)
        norm_mobile = normalize_mobile(customer_mobile)
        if not re.fullmatch(r"[6-9]\d{9}", norm_mobile):
            return jsonify({"error": "Invalid Indian mobile number"}), 400

        # 3. Validate items array is not empty
        if not items or not isinstance(items, list):
            return jsonify({"error": "items array cannot be empty"}), 400

        db = get_db()

        # Fetch valid cloth types from DB
        valid_cloth_types = {
            row["type_name"]: dict(row)
            for row in db.execute("SELECT type_name, has_company FROM cloth_types").fetchall()
        }

        # 4 & 5. Validate and recalculate each item server-side
        calculated_items = []
        for idx, item in enumerate(items):
            prefix = f"Item {idx + 1}"
            cloth_type = (item.get("cloth_type") or "").strip()
            company_name = (item.get("company_name") or "").strip()
            quality_number = (item.get("quality_number") or "").strip() or None
            try:
                quantity = float(item["quantity"])
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": f"{prefix}: quantity must be a number"}), 400
            try:
                mrp = float(item["mrp"])
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": f"{prefix}: mrp must be a number"}), 400
            try:
                discount_percent = float(item.get("discount_percent", 0))
            except (TypeError, ValueError):
                return jsonify({"error": f"{prefix}: discount_percent must be a number"}), 400

            if cloth_type not in valid_cloth_types:
                return jsonify({"error": f"{prefix}: invalid cloth_type '{cloth_type}'"}), 400
            has_company = valid_cloth_types[cloth_type]["has_company"]
            if has_company and not company_name:
                return jsonify({"error": f"{prefix}: company_name is required"}), 400
            # Unit label is determined server-side from cloth_type
            unit_label = "m" if cloth_type in ("Shirting", "Suiting") else "pcs"
            if quantity <= 0:
                return jsonify({"error": f"{prefix}: quantity must be > 0"}), 400
            if mrp < 0:
                return jsonify({"error": f"{prefix}: mrp cannot be negative"}), 400
            if not (0 <= discount_percent <= 100):
                return jsonify({"error": f"{prefix}: discount_percent must be 0–100"}), 400

            disc_per_unit   = round(mrp * discount_percent / 100, 2)
            rate_after_disc = round(mrp - disc_per_unit, 2)
            final_amount    = round(rate_after_disc * quantity, 2)
            line_total      = round(mrp * quantity, 2)
            discount_amount = round(line_total - final_amount, 2)

            calculated_items.append({
                "cloth_type": cloth_type,
                "company_name": company_name,
                "quality_number": quality_number,
                "quantity": quantity,
                "unit_label": unit_label,
                "mrp": mrp,
                "line_total": line_total,
                "discount_percent": discount_percent,
                "discount_amount": discount_amount,
                "rate_after_disc": rate_after_disc,
                "final_amount": final_amount,
            })

        subtotal = round(sum(i["line_total"] for i in calculated_items), 2)
        total_discount = round(sum(i["discount_amount"] for i in calculated_items), 2)
        final_total = round(sum(i["final_amount"] for i in calculated_items), 2)
        total_savings = total_discount

        # 6. Validate payments sum == final_total
        if not payments or not isinstance(payments, list):
            return jsonify({"error": "payments array cannot be empty"}), 400

        for p in payments:
            if (p.get("payment_method") or "") not in VALID_PAYMENT_METHODS:
                return jsonify({"error": f"payment_method must be one of {sorted(VALID_PAYMENT_METHODS)}"}), 400
            try:
                float(p["amount"])
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": "payment amount must be a number"}), 400

        payments_sum = round(sum(float(p["amount"]) for p in payments), 2)
        if abs(payments_sum - final_total) > 0.01:
            return jsonify({
                "error": f"Payments sum ({payments_sum}) does not match final_total ({final_total})"
            }), 400

        # 6b. Advance paid
        try:
            advance_paid = round(float(body.get("advance_paid", 0) or 0), 2)
        except (TypeError, ValueError):
            advance_paid = 0.0
        if advance_paid < 0:
            return jsonify({"error": "advance_paid cannot be negative"}), 400
        if advance_paid > final_total:
            return jsonify({"error": "advance_paid cannot exceed final_total"}), 400
        remaining = round(final_total - advance_paid, 2)

        # 7. Find or create customer
        customer_id = None
        existing = db.execute(
            "SELECT id FROM customers WHERE normalized_mobile = ?", (norm_mobile,)
        ).fetchone()
        if existing:
            customer_id = existing["id"]
            db.execute(
                "UPDATE customers SET name = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (customer_name, customer_id),
            )
        else:
            cursor = db.execute(
                """
                INSERT INTO customers (name, mobile, normalized_mobile)
                VALUES (?, ?, ?)
                """,
                (customer_name, norm_mobile, norm_mobile),
            )
            customer_id = cursor.lastrowid

        # 8 & 9. Generate bill_number and insert all in one transaction.
        bill_number = generate_bill_number(db)

        bill_cursor = db.execute(
            """
            INSERT INTO bills (
                bill_number, customer_id,
                customer_name_snapshot, customer_mobile_snapshot,
                bill_date, subtotal, total_discount, final_total,
                total_savings, advance_paid, remaining, payment_mode_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bill_number, customer_id,
                customer_name, norm_mobile,
                bill_date, subtotal, total_discount, final_total,
                total_savings, advance_paid, remaining, payment_mode_type,
            ),
        )
        bill_id = bill_cursor.lastrowid

        db.executemany(
            """
            INSERT INTO bill_items (
                bill_id, cloth_type, company_name, quality_number,
                quantity, unit_label, mrp, line_total,
                discount_percent, discount_amount, rate_after_disc, final_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    bill_id,
                    i["cloth_type"], i["company_name"], i["quality_number"],
                    i["quantity"], i["unit_label"], i["mrp"], i["line_total"],
                    i["discount_percent"], i["discount_amount"], i["rate_after_disc"], i["final_amount"],
                )
                for i in calculated_items
            ],
        )

        db.executemany(
            "INSERT INTO bill_payments (bill_id, payment_method, amount) VALUES (?, ?, ?)",
            [(bill_id, p["payment_method"], float(p["amount"])) for p in payments],
        )

        db.commit()

        # 10. Return created bill summary
        return jsonify({
            "id": bill_id,
            "bill_number": bill_number,
            "customer_id": customer_id,
            "customer_name_snapshot": customer_name,
            "customer_mobile_snapshot": norm_mobile,
            "bill_date": bill_date,
            "subtotal": subtotal,
            "total_discount": total_discount,
            "final_total": final_total,
            "total_savings": total_savings,
            "advance_paid": advance_paid,
            "remaining": remaining,
            "payment_mode_type": payment_mode_type,
        }), 201

    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# PUT /api/bills/<id>
# ---------------------------------------------------------------------------
@bills_bp.route("/bills/<int:bill_id>", methods=["PUT"])
def update_bill(bill_id):
    try:
        body = request.get_json(force=True, silent=True) or {}

        # 1. Validate required fields (same rules as POST)
        customer_name     = (body.get("customer_name") or "").strip()
        customer_mobile   = (body.get("customer_mobile") or "").strip()
        bill_date         = (body.get("bill_date") or "").strip()
        payment_mode_type = (body.get("payment_mode_type") or "").strip()
        items             = body.get("items", [])
        payments          = body.get("payments", [])

        errors = []
        if not customer_name:
            errors.append("customer_name is required")
        if not customer_mobile:
            errors.append("customer_mobile is required")
        if not bill_date:
            errors.append("bill_date is required")
        if payment_mode_type not in VALID_PAYMENT_MODES:
            errors.append(f"payment_mode_type must be one of {sorted(VALID_PAYMENT_MODES)}")
        if errors:
            return jsonify({"error": "; ".join(errors)}), 400

        norm_mobile = normalize_mobile(customer_mobile)
        if not re.fullmatch(r"[6-9]\d{9}", norm_mobile):
            return jsonify({"error": "Invalid Indian mobile number"}), 400

        if not items or not isinstance(items, list):
            return jsonify({"error": "items array cannot be empty"}), 400

        db = get_db()

        # Check bill exists
        existing_bill = db.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not existing_bill:
            return jsonify({"error": "Bill not found"}), 404

        # 2. Validate and recalculate items server-side
        valid_cloth_types = {
            row["type_name"]: dict(row)
            for row in db.execute("SELECT type_name, has_company FROM cloth_types").fetchall()
        }

        calculated_items = []
        for idx, item in enumerate(items):
            prefix        = f"Item {idx + 1}"
            cloth_type    = (item.get("cloth_type") or "").strip()
            company_name  = (item.get("company_name") or "").strip()
            quality_number = (item.get("quality_number") or "").strip() or None
            try:
                quantity = float(item["quantity"])
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": f"{prefix}: quantity must be a number"}), 400
            try:
                mrp = float(item["mrp"])
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": f"{prefix}: mrp must be a number"}), 400
            try:
                discount_percent = float(item.get("discount_percent", 0))
            except (TypeError, ValueError):
                return jsonify({"error": f"{prefix}: discount_percent must be a number"}), 400

            if cloth_type not in valid_cloth_types:
                return jsonify({"error": f"{prefix}: invalid cloth_type '{cloth_type}'"}), 400
            has_company = valid_cloth_types[cloth_type]["has_company"]
            if has_company and not company_name:
                return jsonify({"error": f"{prefix}: company_name is required"}), 400
            unit_label = "m" if cloth_type in ("Shirting", "Suiting") else "pcs"
            if quantity <= 0:
                return jsonify({"error": f"{prefix}: quantity must be > 0"}), 400
            if mrp < 0:
                return jsonify({"error": f"{prefix}: mrp cannot be negative"}), 400
            if not (0 <= discount_percent <= 100):
                return jsonify({"error": f"{prefix}: discount_percent must be 0–100"}), 400

            disc_per_unit   = round(mrp * discount_percent / 100, 2)
            rate_after_disc = round(mrp - disc_per_unit, 2)
            final_amount    = round(rate_after_disc * quantity, 2)
            line_total      = round(mrp * quantity, 2)
            discount_amount = round(line_total - final_amount, 2)

            calculated_items.append({
                "cloth_type": cloth_type, "company_name": company_name,
                "quality_number": quality_number, "quantity": quantity,
                "unit_label": unit_label, "mrp": mrp, "line_total": line_total,
                "discount_percent": discount_percent, "discount_amount": discount_amount,
                "rate_after_disc": rate_after_disc, "final_amount": final_amount,
            })

        subtotal       = round(sum(i["line_total"]      for i in calculated_items), 2)
        total_discount = round(sum(i["discount_amount"] for i in calculated_items), 2)
        final_total    = round(sum(i["final_amount"]    for i in calculated_items), 2)
        total_savings  = total_discount

        # 3. Validate payments sum == final_total
        if not payments or not isinstance(payments, list):
            return jsonify({"error": "payments array cannot be empty"}), 400

        for p in payments:
            if (p.get("payment_method") or "") not in VALID_PAYMENT_METHODS:
                return jsonify({"error": f"payment_method must be one of {sorted(VALID_PAYMENT_METHODS)}"}), 400
            try:
                float(p["amount"])
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": "payment amount must be a number"}), 400

        payments_sum = round(sum(float(p["amount"]) for p in payments), 2)
        if abs(payments_sum - final_total) > 0.01:
            return jsonify({
                "error": f"Payments sum ({payments_sum}) does not match final_total ({final_total})"
            }), 400

        try:
            advance_paid = round(float(body.get("advance_paid", 0) or 0), 2)
        except (TypeError, ValueError):
            advance_paid = 0.0
        if advance_paid < 0:
            return jsonify({"error": "advance_paid cannot be negative"}), 400
        if advance_paid > final_total:
            return jsonify({"error": "advance_paid cannot exceed final_total"}), 400
        remaining = round(final_total - advance_paid, 2)

        # 4f. Find or create customer
        customer_id = None
        existing_cust = db.execute(
            "SELECT id FROM customers WHERE normalized_mobile = ?", (norm_mobile,)
        ).fetchone()
        if existing_cust:
            customer_id = existing_cust["id"]
            db.execute(
                "UPDATE customers SET name = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (customer_name, customer_id),
            )
        else:
            cur = db.execute(
                "INSERT INTO customers (name, mobile, normalized_mobile) VALUES (?, ?, ?)",
                (customer_name, norm_mobile, norm_mobile),
            )
            customer_id = cur.lastrowid

        # 4a-e. Replace items and payments, update bill header
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
                payment_mode_type        = ?,
                updated_at               = datetime('now','localtime')
            WHERE id = ?
        """, (
            customer_id, customer_name, norm_mobile,
            bill_date, subtotal, total_discount, final_total,
            total_savings, advance_paid, remaining, payment_mode_type,
            bill_id,
        ))

        db.executemany(
            """
            INSERT INTO bill_items (
                bill_id, cloth_type, company_name, quality_number,
                quantity, unit_label, mrp, line_total,
                discount_percent, discount_amount, rate_after_disc, final_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    bill_id,
                    i["cloth_type"], i["company_name"], i["quality_number"],
                    i["quantity"], i["unit_label"], i["mrp"], i["line_total"],
                    i["discount_percent"], i["discount_amount"], i["rate_after_disc"], i["final_amount"],
                )
                for i in calculated_items
            ],
        )

        db.executemany(
            "INSERT INTO bill_payments (bill_id, payment_method, amount) VALUES (?, ?, ?)",
            [(bill_id, p["payment_method"], float(p["amount"])) for p in payments],
        )

        db.commit()

        # 6. Return updated bill
        return jsonify({
            "id":                      bill_id,
            "bill_number":             existing_bill["bill_number"],
            "customer_id":             customer_id,
            "customer_name_snapshot":  customer_name,
            "customer_mobile_snapshot": norm_mobile,
            "bill_date":               bill_date,
            "subtotal":                subtotal,
            "total_discount":          total_discount,
            "final_total":             final_total,
            "total_savings":           total_savings,
            "advance_paid":            advance_paid,
            "remaining":               remaining,
            "payment_mode_type":       payment_mode_type,
        }), 200

    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# DELETE /api/bills/<id>  — hard delete + renumber higher bills
# ---------------------------------------------------------------------------
@bills_bp.route("/bills/<int:bill_id>", methods=["DELETE"])
def delete_bill(bill_id):
    try:
        db = get_db()

        # 1. Check bill exists
        bill = db.execute(
            "SELECT bill_number FROM bills WHERE id = ?", (bill_id,)
        ).fetchone()
        if not bill:
            return jsonify({"error": "Bill not found"}), 404

        # 2–3. Parse the numeric part (e.g. "SHN-0003" → 3)
        bill_number = bill["bill_number"]
        try:
            deleted_num = int(bill_number.split("-")[1])
        except (IndexError, ValueError):
            return jsonify({"error": "Unexpected bill_number format"}), 500

        # 4. Delete items
        db.execute("DELETE FROM bill_items    WHERE bill_id = ?", (bill_id,))
        # 5. Delete payments
        db.execute("DELETE FROM bill_payments WHERE bill_id = ?", (bill_id,))
        # 6. Delete the bill itself
        db.execute("DELETE FROM bills WHERE id = ?", (bill_id,))

        # 7. Renumber all bills whose number was higher than the deleted one
        higher_bills = db.execute(
            """
            SELECT id, bill_number
            FROM bills
            WHERE CAST(SUBSTR(bill_number, 5) AS INTEGER) > ?
            ORDER BY CAST(SUBSTR(bill_number, 5) AS INTEGER) ASC
            """,
            (deleted_num,),
        ).fetchall()

        for b in higher_bills:
            current_num     = int(b["bill_number"].split("-")[1])
            new_bill_number = f"SHN-{(current_num - 1):04d}"
            db.execute(
                "UPDATE bills SET bill_number = ? WHERE id = ?",
                (new_bill_number, b["id"]),
            )

        # 8. Commit everything atomically
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
# GET /api/analytics/summary
# ---------------------------------------------------------------------------
@bills_bp.route("/analytics/summary", methods=["GET"])
def analytics_summary():
    try:
        db = get_db()
        now = datetime.now()
        today_str   = now.strftime("%Y-%m-%d")
        this_month  = now.strftime("%Y-%m")
        this_year   = now.strftime("%Y")

        overall = db.execute("""
            SELECT
                COUNT(DISTINCT b.id)                                                     AS total_bills,
                COALESCE(SUM(b.final_total), 0)                                          AS total_sales,
                COUNT(DISTINCT b.customer_id)                                            AS total_customers,
                COALESCE(SUM(cp.cash), 0)                                                AS total_cash,
                COALESCE(SUM(cp.card), 0)                                                AS total_card,
                COALESCE(SUM(cp.upi), 0)                                                 AS total_upi,
                COALESCE(SUM(CASE WHEN b.payment_mode_type='Combination'
                                  THEN b.final_total ELSE 0 END), 0)                     AS total_combination
            FROM bills b
            LEFT JOIN (
                SELECT bill_id,
                    SUM(CASE WHEN payment_method='Cash' THEN amount ELSE 0 END) AS cash,
                    SUM(CASE WHEN payment_method='Card' THEN amount ELSE 0 END) AS card,
                    SUM(CASE WHEN payment_method='UPI'  THEN amount ELSE 0 END) AS upi
                FROM bill_payments GROUP BY bill_id
            ) cp ON cp.bill_id = b.id
            WHERE b.status != 'cancelled'
        """).fetchone()

        today_row = db.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(final_total),0) AS sales "
            "FROM bills WHERE status != 'cancelled' AND bill_date = ?",
            (today_str,)
        ).fetchone()

        month_row = db.execute(
            "SELECT COALESCE(SUM(final_total),0) AS sales "
            "FROM bills WHERE status != 'cancelled' AND strftime('%Y-%m', bill_date) = ?",
            (this_month,)
        ).fetchone()

        year_row = db.execute(
            "SELECT COALESCE(SUM(final_total),0) AS sales "
            "FROM bills WHERE status != 'cancelled' AND strftime('%Y', bill_date) = ?",
            (this_year,)
        ).fetchone()

        return jsonify({
            "total_bills":        int(overall["total_bills"] or 0),
            "total_sales":        round(float(overall["total_sales"] or 0), 2),
            "total_customers":    int(overall["total_customers"] or 0),
            "total_cash":         round(float(overall["total_cash"] or 0), 2),
            "total_card":         round(float(overall["total_card"] or 0), 2),
            "total_upi":          round(float(overall["total_upi"] or 0), 2),
            "total_combination":  round(float(overall["total_combination"] or 0), 2),
            "today_bills":        int(today_row["cnt"] or 0),
            "today_sales":        round(float(today_row["sales"] or 0), 2),
            "this_month_sales":   round(float(month_row["sales"] or 0), 2),
            "this_year_sales":    round(float(year_row["sales"] or 0), 2),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /api/analytics?period=daily|monthly|yearly
# ---------------------------------------------------------------------------
@bills_bp.route("/analytics", methods=["GET"])
def get_analytics():
    try:
        period = request.args.get("period", "monthly")
        db     = get_db()
        today  = datetime.now().date()

        # Build ordered bucket list and date filter
        if period == "daily":
            buckets = [
                (today - timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(29, -1, -1)
            ]
            date_filter = f"b.bill_date >= '{buckets[0]}'"
            group_expr  = "strftime('%Y-%m-%d', b.bill_date)"

        elif period == "yearly":
            buckets = [str(today.year - i) for i in range(4, -1, -1)]
            date_filter = f"strftime('%Y', b.bill_date) >= '{buckets[0]}'"
            group_expr  = "strftime('%Y', b.bill_date)"

        else:  # monthly (default)
            buckets = []
            for i in range(11, -1, -1):
                total_m  = today.year * 12 + (today.month - 1) - i
                b_year   = total_m // 12
                b_month  = (total_m % 12) + 1
                buckets.append(f"{b_year:04d}-{b_month:02d}")
            date_filter = f"strftime('%Y-%m', b.bill_date) >= '{buckets[0]}'"
            group_expr  = "strftime('%Y-%m', b.bill_date)"

        rows = db.execute(f"""
            SELECT
                {group_expr}                                                              AS bucket,
                SUM(b.final_total)                                                        AS total_sales,
                COUNT(b.id)                                                               AS bill_count,
                COALESCE(SUM(cp.cash), 0)                                                AS cash,
                COALESCE(SUM(cp.card), 0)                                                AS card,
                COALESCE(SUM(cp.upi), 0)                                                 AS upi,
                COALESCE(SUM(CASE WHEN b.payment_mode_type='Combination'
                                  THEN b.final_total ELSE 0 END), 0)                     AS combination
            FROM bills b
            LEFT JOIN (
                SELECT bill_id,
                    SUM(CASE WHEN payment_method='Cash' THEN amount ELSE 0 END) AS cash,
                    SUM(CASE WHEN payment_method='Card' THEN amount ELSE 0 END) AS card,
                    SUM(CASE WHEN payment_method='UPI'  THEN amount ELSE 0 END) AS upi
                FROM bill_payments GROUP BY bill_id
            ) cp ON cp.bill_id = b.id
            WHERE b.status != 'cancelled'
              AND {date_filter}
            GROUP BY bucket
            ORDER BY bucket ASC
        """).fetchall()

        data_map = {r["bucket"]: dict(r) for r in rows}

        result = []
        for bucket in buckets:
            row = data_map.get(bucket, {})
            if period == "daily":
                label = datetime.strptime(bucket, "%Y-%m-%d").strftime("%d %b")
            elif period == "monthly":
                label = datetime.strptime(bucket + "-01", "%Y-%m-%d").strftime("%b %Y")
            else:
                label = bucket

            result.append({
                "label":       label,
                "bucket":      bucket,
                "total_sales": round(float(row.get("total_sales") or 0), 2),
                "cash":        round(float(row.get("cash") or 0), 2),
                "card":        round(float(row.get("card") or 0), 2),
                "upi":         round(float(row.get("upi") or 0), 2),
                "combination": round(float(row.get("combination") or 0), 2),
                "bill_count":  int(row.get("bill_count") or 0),
            })

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
